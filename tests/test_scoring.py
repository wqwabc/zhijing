# -*- coding: utf-8 -*-
"""评分引擎单元测试

跑法（在仓库根目录）：
    python -m unittest discover -s tests -p test_scoring.py -v
或在仓库根目录：
    python -m unittest discover -s tests -p test_scoring.py -v
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from verda import Combo, Plant, Scene, score_combo
from verda.loader import load_plants
from verda.scoring import (AESTHETIC_RATIO, FIT_RATIO, WEIGHTS,
                           WEIGHTS_RAW)


class TestLoader(unittest.TestCase):
    """能读到 B 交付的真实数据"""

    @classmethod
    def setUpClass(cls):
        cls.plants = load_plants()
        cls.by_id = {p.plant_id: p for p in cls.plants}

    def test_count(self):
        self.assertGreaterEqual(len(self.plants), 40,
                                "B 的 plants_master 应该有 40+ 种，实际 %d"
                                % len(self.plants))

    def test_ids_format(self):
        for p in self.plants:
            self.assertRegex(p.plant_id, r"^P\d{2}$")

    def test_all_have_color(self):
        """每株都要有叶色，否则色彩维度算不了"""
        for p in self.plants:
            self.assertRegex(p.dominant_hex, r"^#[0-9A-Fa-f]{6}$",
                             "%s 的叶色不对：%r" % (p.plant_id, p.dominant_hex))

    def test_cutout_flag(self):
        ready = [p for p in self.plants if p.has_cutout]
        self.assertGreater(len(ready), 0, "至少要有一株有去底素材")

    def test_derived_fields_valid(self):
        for p in self.plants:
            self.assertIn(p.leaf_size, ("大叶", "中叶", "细叶"))
            self.assertIn(p.texture, ("光泽", "哑光", "绒面", "纸质", "革质"))


class TestWeights(unittest.TestCase):
    def test_raw_sum_is_0_90(self):
        self.assertAlmostEqual(sum(WEIGHTS_RAW.values()), 0.90, places=4)

    def test_normalized_sum_is_1(self):
        self.assertAlmostEqual(sum(WEIGHTS.values()), 1.0, places=6)

    def test_ratio_preserved(self):
        for k in WEIGHTS_RAW:
            self.assertAlmostEqual(WEIGHTS[k] / WEIGHTS_RAW[k], 1 / 0.90, places=6)
            break

    def test_composite_ratio(self):
        self.assertAlmostEqual(AESTHETIC_RATIO + FIT_RATIO, 1.0, places=6)


class TestScoreing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plants = load_plants()
        cls.by_id = {p.plant_id: p for p in cls.plants}

    def _p(self, pid):
        return self.by_id[pid]

    def test_all_scores_in_range(self):
        scene = Scene(room="living", style="nordic", light=2,
                      weekly_minutes=30, has_pet=True, budget=400)
        # 拿前 12 种植物两两组合，覆盖各种形态
        groups = [self.plants[i:i + 3] for i in range(0, 12, 3)]
        for group in groups:
            with self.subTest(plants=[p.name_cn for p in group]):
                result = score_combo(Combo(group), scene)
                for d in result.dimensions:
                    self.assertGreaterEqual(d.score, 0.0)
                    self.assertLessEqual(d.score, 100.0)
                for v in (result.aesthetic, result.fit, result.total):
                    self.assertGreaterEqual(v, 0.0)
                    self.assertLessEqual(v, 100.0)

    def test_composite_formula(self):
        scene = Scene(room="living", style="nordic", light=2)
        result = score_combo(Combo(self.plants[:2]), scene)
        expect = AESTHETIC_RATIO * result.aesthetic + FIT_RATIO * result.fit
        self.assertAlmostEqual(result.total, expect, places=6)

    def test_pet_toxic_flag(self):
        """有宠物 + 有毒植物必须报警"""
        scene = Scene(room="living", style="tropical", light=2, has_pet=True)
        toxic = [p for p in self.plants if p.is_toxic][:2]
        self.assertTrue(toxic, "数据里应该有有毒植物")
        result = score_combo(Combo(toxic), scene)
        self.assertTrue(any("有毒" in f for f in result.hard_flags),
                        "应该报警，实际 %s" % result.hard_flags)

    def test_pet_safe_no_flag(self):
        scene = Scene(room="living", style="tropical", light=2, has_pet=True)
        safe = [p for p in self.plants if not p.is_toxic and p.pet_safe][:2]
        if len(safe) < 2:
            self.skipTest("数据里无毒植物不足")
        result = score_combo(Combo(safe), scene)
        self.assertFalse(any("有毒" in f for f in result.hard_flags))

    def test_light_gap_flag(self):
        """光照差 2 档以上要报警"""
        scene = Scene(room="study", style="minimal", light=1)
        thirsty = [p for p in self.plants if p.light_need >= 4][:2]
        if not thirsty:
            self.skipTest("数据里没有高光需植物")
        result = score_combo(Combo(thirsty), scene)
        self.assertTrue(any("光照" in f for f in result.hard_flags),
                        "应该报警，实际 %s" % result.hard_flags)

    def test_big_plant_small_room(self):
        """办公桌放不下 100cm+ 的植物（B 给办公桌的区间是 8~50cm）"""
        scene = Scene(room="desk", style="minimal", light=3)
        big = [p for p in self.plants if p.height_cm >= 100][:1]
        if not big:
            self.skipTest("数据里没有 100cm+ 的植物")
        result = score_combo(Combo(big), scene)
        self.assertTrue(any("放不下" in f for f in result.hard_flags),
                        "应该报警，实际 %s" % result.hard_flags)

    def test_good_beats_bad(self):
        """层次分明的组合要比全直立的分数高"""
        scene = Scene(room="living", style="nordic", light=2, budget=800)
        tall = [p for p in self.plants if p.form in ("树形", "直立")
                and p.height_cm >= 100][:1]
        drop = [p for p in self.plants if p.form == "垂吊"][:1]
        low = [p for p in self.plants if p.height_cm < 40][:1]
        uprights = [p for p in self.plants
                    if p.form in ("直立", "树形")][:3]

        if not (tall and drop and low):
            self.skipTest("数据不足以构造对比组合")

        good = score_combo(Combo(tall + drop + low), scene)
        bad = score_combo(Combo(uprights), scene)
        self.assertGreater(good.total, bad.total,
                           "层次组合 %.1f 应该高于全直立 %.1f"
                           % (good.total, bad.total))

    def test_reasons(self):
        scene = Scene(room="living", style="nordic", light=2)
        result = score_combo(Combo(self.plants[:3]), scene)
        self.assertGreaterEqual(len(result.reasons), 3)
        self.assertLessEqual(len(result.reasons), 4)

    def test_as_dict_serializable(self):
        scene = Scene(room="living", style="nordic", light=2)
        result = score_combo(Combo(self.plants[:3]), scene)
        s = json.dumps(result.as_dict(), ensure_ascii=False)
        self.assertIn("aesthetic", s)
        self.assertIn("dimensions", s)


class TestValidation(unittest.TestCase):
    def test_bad_form(self):
        with self.assertRaises(ValueError):
            Plant("P99", "假植物", form="不存在的株型")

    def test_bad_light_level(self):
        with self.assertRaises(ValueError):
            Plant("P99", "假植物", form="直立", light_level="L9")

    def test_bad_room(self):
        with self.assertRaises(ValueError):
            Scene(room="地下室", style="nordic")

    def test_bad_style(self):
        with self.assertRaises(ValueError):
            Scene(room="living", style="中式")

    def test_bad_light(self):
        with self.assertRaises(ValueError):
            Scene(room="living", style="nordic", light=9)

    def test_empty_combo(self):
        with self.assertRaises(ValueError):
            Combo([])


if __name__ == "__main__":
    unittest.main(verbosity=2)
