# -*- coding: utf-8 -*-
"""改稿逻辑单元测试（FR-08）

跑法（在仓库根目录）：
    python -m unittest C.test_revise -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from verda import Combo, Scene
from verda.loader import load_plants
from verda.recommend import build_pool, recommend
from verda.revise import (EASY_CARE_MAX, INTENTS, MIN_KEEP_RATIO,
                          parse_intent, revise)


class TestIntentParse(unittest.TestCase):
    def test_all_intents_parse(self):
        for intent in INTENTS:
            got = parse_intent(intent.name)
            self.assertIsNotNone(got, "「%s」自己都认不出来" % intent.name)
            self.assertEqual(got.name, intent.name)

    def test_natural_language(self):
        cases = [
            ("能不能换几种好养的", "更好养"),
            ("我家有猫，安全点", "对猫狗安全"),
            ("预算能省一点吗", "预算降一档"),
            ("有点太高了", "再矮一点"),
            ("想更出片一点", "更有张力"),
            ("加点垂下来的", "加一点垂坠"),
            ("想素一点", "更安静"),
            ("看着有点乱，想简单些", "更安静"),
        ]
        for text, expect in cases:
            got = parse_intent(text)
            self.assertIsNotNone(got, "「%s」没认出来" % text)
            self.assertEqual(got.name, expect,
                             "「%s」应该识别为「%s」，实际「%s」"
                             % (text, expect, got.name))

    def test_unknown(self):
        for text in ("今天天气不错", "随便来一个", ""):
            self.assertIsNone(parse_intent(text),
                              "「%s」不该被识别成任何意图" % text)


class TestRevise(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plants = load_plants()
        cls.by_id = {p.plant_id: p for p in cls.plants}
        cls.scene = Scene(room="living", style="nordic", light=2,
                          weekly_minutes=30, has_pet=True, budget=400)
        cls.pool = build_pool(cls.plants, cls.scene)
        plan = recommend(cls.scene, cls.plants)
        cls.base = plan["plans"][0]
        cls.combo = Combo([cls.by_id[x] for x in cls.base["plant_ids"]])

    def _revise(self, instruction):
        return revise(self.combo, self.scene, instruction,
                      pool=self.pool, plants=self.plants)

    def test_all_intents_supported(self):
        """七种指令都不能崩"""
        for intent in INTENTS:
            with self.subTest(intent=intent.name):
                res = self._revise(intent.name)
                self.assertTrue(res.get("supported"), res.get("error"))
                self.assertIn("before", res)
                self.assertIn("after", res)
                self.assertIn("diff", res)

    def test_keep_ratio_at_least_half(self):
        """FR-08：保留原方案 >= 50%，这是硬指标"""
        for intent in INTENTS:
            with self.subTest(intent=intent.name):
                res = self._revise(intent.name)
                ratio = res["diff"]["keep_ratio"]
                self.assertGreaterEqual(
                    ratio, MIN_KEEP_RATIO,
                    "「%s」保留率 %.2f 低于 0.5" % (intent.name, ratio))

    def test_diff_has_all_fields(self):
        res = self._revise("更好养")
        d = res["diff"]
        for k in ("kept", "removed", "added", "keep_ratio",
                  "satisfied", "note"):
            self.assertIn(k, d, "diff 缺字段 %s" % k)

    def test_better_care_satisfied(self):
        """改完「更好养」后，所有植物都该是难度易 + 养护时长短"""
        res = self._revise("更好养")
        for pid in res["after"]["plant_ids"]:
            p = self.by_id[pid]
            self.assertEqual(p.difficulty, "易",
                             "%s 难度不是易" % p.name_cn)
            self.assertLessEqual(p.care_min_week, EASY_CARE_MAX,
                                 "%s 养护 %d 分钟超过 %d"
                                 % (p.name_cn, p.care_min_week, EASY_CARE_MAX))

    def test_pet_safe_satisfied(self):
        """改完「对猫狗安全」后不能有毒株"""
        res = self._revise("对猫狗安全")
        for pid in res["after"]["plant_ids"]:
            self.assertFalse(self.by_id[pid].is_toxic,
                             "%s 有毒" % self.by_id[pid].name_cn)

    def test_shorter_satisfied(self):
        """改完「再矮一点」后最高株应比原来矮"""
        before_max = max(self.by_id[x].height_cm
                         for x in self.base["plant_ids"])
        res = self._revise("再矮一点")
        after_max = max(self.by_id[x].height_cm
                        for x in res["after"]["plant_ids"])
        self.assertLess(after_max, before_max,
                        "改后最高 %.0fcm 没比改前 %.0fcm 矮"
                        % (after_max, before_max))

    def test_boost_improves_dimension(self):
        """「更有张力」应该让形态对比维度变高"""
        before = None
        res = self._revise("更有张力")
        before = next(d for d in self._base_score().dimensions
                      if d.name == "形态对比").score
        after = next(d for d in res["after"]["score"]["dimensions"]
                     if d["name"] == "形态对比")["score"]
        self.assertGreaterEqual(after, before,
                                "形态对比没提升：%.0f -> %.0f" % (before, after))

    def _base_score(self):
        from verda.scoring import score_combo
        return score_combo(self.combo, self.scene)

    def test_weight_change_keeps_plants(self):
        """「更安静」不换植物"""
        res = self._revise("更安静")
        self.assertEqual(res["diff"]["removed"], [])
        self.assertEqual(res["diff"]["added"], [])
        self.assertEqual(res["diff"]["keep_ratio"], 1.0)

    def test_unsupported_returns_error(self):
        res = self._revise("我想吃火锅")
        self.assertFalse(res.get("supported"))
        self.assertIn("error", res)

    def test_scores_in_range(self):
        for intent in INTENTS:
            res = self._revise(intent.name)
            for v in (res["after"]["total"], res["before"]["total"]):
                self.assertGreaterEqual(v, 0.0)
                self.assertLessEqual(v, 100.0)

    def test_no_duplicate_plants(self):
        """改稿后不能出现同一株植物两次"""
        for intent in INTENTS:
            res = self._revise(intent.name)
            ids = res["after"]["plant_ids"]
            self.assertEqual(len(ids), len(set(ids)),
                             "「%s」改出了重复植物：%s" % (intent.name, ids))


def res_ids(plan_dict):
    return plan_dict["plant_ids"]


if __name__ == "__main__":
    unittest.main(verbosity=2)
