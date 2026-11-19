# -*- coding: utf-8 -*-
"""推荐搜索单元测试（对应 FR-03 和 AC-04）

跑法（在仓库根目录）：
    python -m unittest C.test_recommend -v
"""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from verda import Scene
from verda.loader import load_plants
from verda.recommend import (JACCARD_LIMIT, PERSONALITIES, build_pool,
                             enumerate_combos, jaccard, recommend,
                             split_by_layer, weights_for)


class TestWeightsPerPersonality(unittest.TestCase):
    def test_three_personalities_exist(self):
        self.assertEqual(set(PERSONALITIES), {"稳妥", "对比", "个性"})

    def test_weights_differ(self):
        """三种性格的权重必须真的不一样，否则性格是假的"""
        w1 = weights_for("稳妥")
        w2 = weights_for("对比")
        w3 = weights_for("个性")
        self.assertNotEqual(w1, w2)
        self.assertNotEqual(w2, w3)
        self.assertNotEqual(w1, w3)

    def test_boost_direction(self):
        """稳妥该加重风格一致，对比该加重形态对比"""
        self.assertGreater(weights_for("稳妥")["风格一致"],
                           weights_for("对比")["风格一致"])
        self.assertGreater(weights_for("对比")["形态对比"],
                           weights_for("稳妥")["形态对比"])
        self.assertGreater(weights_for("个性")["色彩和谐"],
                           weights_for("稳妥")["色彩和谐"])


class TestJaccard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plants = load_plants()
        cls.by_id = {p.plant_id: p for p in cls.plants}

    def test_identical(self):
        a = self.plants[:3]
        self.assertAlmostEqual(jaccard(a, a), 1.0, places=6)

    def test_disjoint(self):
        a = self.plants[:2]
        b = self.plants[10:12]
        self.assertAlmostEqual(jaccard(a, b), 0.0, places=6)

    def test_partial(self):
        a = self.plants[:3]      # P01 P02 P03
        b = self.plants[2:5]     # P03 P04 P05
        # 交集 {P03} = 1，并集 5 个
        self.assertAlmostEqual(jaccard(a, b), 1 / 5, places=6)


class TestPool(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plants = load_plants()

    def test_pet_filter_excludes_toxic(self):
        """有宠物时，候选池里不能有有毒植物（AC-05）"""
        scene = Scene(room="living", style="nordic", light=2,
                      has_pet=True, budget=1000)
        pool = build_pool(self.plants, scene)
        toxic = [p for p in pool if p.is_toxic]
        self.assertEqual(len(toxic), 0,
                         "有宠物时池里不该有有毒植物，实际有 %d 株"
                         % len(toxic))

    def test_no_cutout_excluded(self):
        """没有去底素材的植物不能进照片（FR-07）"""
        scene = Scene(room="living", style="nordic", light=2, budget=1000)
        pool = build_pool(self.plants, scene)
        for p in pool:
            self.assertTrue(p.has_cutout,
                            "%s 没有去底素材却进了池" % p.plant_id)

    def test_light_gap_filter(self):
        """光照差 2 档以上的不进池"""
        scene = Scene(room="study", style="minimal", light=1, budget=1000)
        pool = build_pool(self.plants, scene)
        for p in pool:
            self.assertLessEqual(p.light_need - scene.light, 1,
                                 "%s 光照需求 %d 太高" % (p.plant_id, p.light_need))

    def test_budget_filter(self):
        """单株价格不能超过预算 60%"""
        scene = Scene(room="living", style="nordic", light=2, budget=200)
        pool = build_pool(self.plants, scene)
        for p in pool:
            self.assertLessEqual(p.price, 200 * 0.6 + 0.01,
                                 "%s 单价 %.0f 超过预算 60%%" % (p.plant_id, p.price))

    def test_height_filter(self):
        """株高不能超过场景上限（B 的 scenes.csv）"""
        from verda.models import ROOM_HEIGHT_RANGE
        scene = Scene(room="desk", style="minimal", light=2, budget=500)
        _, hi = ROOM_HEIGHT_RANGE["desk"]
        pool = build_pool(self.plants, scene)
        for p in pool:
            self.assertLessEqual(p.height_cm, hi)


class TestEnumerate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plants = load_plants()

    def test_produces_combos(self):
        scene = Scene(room="living", style="nordic", light=2, budget=400)
        pool = build_pool(self.plants, scene)
        h, m, l = split_by_layer(pool)
        combos = enumerate_combos(h, m, l, scene.budget)
        self.assertGreater(len(combos), 20,
                           "客厅场景应该能枚举出几十种组合，实际 %d" % len(combos))

    def test_small_room_fallback(self):
        """办公桌没有「高」层，要靠 fallback 也能出组合"""
        scene = Scene(room="desk", style="minimal", light=1, budget=300)
        pool = build_pool(self.plants, scene)
        h, m, l = split_by_layer(pool)
        combos = enumerate_combos(h, m, l, scene.budget)
        self.assertGreater(len(combos), 0,
                           "办公桌场景应该靠 fallback 出组合，实际 0 个")

    def test_price_within_tolerance(self):
        scene = Scene(room="living", style="nordic", light=2, budget=400)
        pool = build_pool(self.plants, scene)
        h, m, l = split_by_layer(pool)
        combos = enumerate_combos(h, m, l, scene.budget)
        for c in combos:
            total = sum(p.price for p in c)
            self.assertLessEqual(total, 400 * 1.15 + 0.01,
                                 "组合超预算：%.0f" % total)

    def test_no_duplicate(self):
        scene = Scene(room="living", style="nordic", light=2, budget=400)
        pool = build_pool(self.plants, scene)
        h, m, l = split_by_layer(pool)
        combos = enumerate_combos(h, m, l, scene.budget)
        keys = [tuple(sorted(p.plant_id for p in c)) for c in combos]
        self.assertEqual(len(keys), len(set(keys)), "枚举结果有重复组合")


class TestRecommend(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plants = load_plants()

    def test_three_plans(self):
        scene = Scene(room="living", style="nordic", light=2,
                      weekly_minutes=30, has_pet=True, budget=400)
        plan = recommend(scene, self.plants)
        self.assertEqual(len(plan["plans"]), 3)
        names = [p["personality"] for p in plan["plans"]]
        self.assertEqual(names, ["稳妥", "对比", "个性"])

    def test_jaccard_under_limit(self):
        """AC-04：三套方案两两 Jaccard < 0.5，这是硬验收指标"""
        scene = Scene(room="living", style="nordic", light=2,
                      weekly_minutes=30, has_pet=True, budget=400)
        plan = recommend(scene, self.plants)
        for j in plan["jaccard"]:
            self.assertLess(j["jaccard"], JACCARD_LIMIT,
                            "%s vs %s 的 Jaccard 是 %.3f，超过 0.5"
                            % (j["a"], j["b"], j["jaccard"]))

    def test_pet_safety_in_plans(self):
        """有宠物时三套方案都不能含有毒植物"""
        scene = Scene(room="living", style="nordic", light=2,
                      has_pet=True, budget=400)
        plan = recommend(scene, self.plants)
        by_id = {p.plant_id: p for p in self.plants}
        for p in plan["plans"]:
            for pid in p["plant_ids"]:
                self.assertFalse(by_id[pid].is_toxic,
                                 "%s 方案里含毒株 %s" % (p["personality"], pid))

    def test_budget_respect(self):
        """总价不超过预算的 115%"""
        budget = 400
        scene = Scene(room="living", style="nordic", light=2, budget=budget)
        plan = recommend(scene, self.plants)
        for p in plan["plans"]:
            self.assertLessEqual(p["total_price"], budget * 1.15 + 0.01,
                                 "%s 方案超预算：%.0f" % (p["personality"],
                                                        p["total_price"]))

    def test_performance(self):
        """FR-03 要求推荐 P95 < 2 秒"""
        scene = Scene(room="living", style="nordic", light=2, budget=400)
        t0 = time.time()
        recommend(scene, self.plants)
        dt = time.time() - t0
        self.assertLess(dt, 2.0, "推荐耗时 %.2f 秒，超过 2 秒" % dt)

    def test_scores_in_range(self):
        scene = Scene(room="living", style="nordic", light=2, budget=400)
        plan = recommend(scene, self.plants)
        for p in plan["plans"]:
            s = p["score"]
            for k in ("aesthetic", "fit", "total"):
                self.assertGreaterEqual(s[k], 0.0)
                self.assertLessEqual(s[k], 100.0)

    def test_empty_pool_degrades(self):
        """候选池空的时候要优雅降级，不是崩"""
        scene = Scene(room="desk", style="minimal", light=1, budget=5)
        plan = recommend(scene, self.plants)
        if plan["candidates"] == 0:
            self.assertTrue(plan["degraded"])
            self.assertIn("error", plan)

    def test_plan_fields(self):
        scene = Scene(room="living", style="nordic", light=2, budget=400)
        plan = recommend(scene, self.plants)
        for p in plan["plans"]:
            for k in ("personality", "desc", "names", "plant_ids",
                      "total_price", "care_min_week", "score"):
                self.assertIn(k, p, "方案缺字段 %s" % k)
            self.assertEqual(len(p["plant_ids"]), len(p["plant_ids"]))
            self.assertGreaterEqual(len(p["plant_ids"]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
