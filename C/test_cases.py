# -*- coding: utf-8 -*-
"""案例检索单元测试（FR-09 / AC-06）

依赖 torch + torchvision + B 的案例图，跑得比前三个慢（首次建库约 10 秒，
之后读缓存秒开）。

跑法（在仓库根目录）：
    python -m unittest C.test_cases -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from verda.case_index import CaseIndex


class TestCaseIndex(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 整个测试类只建一次索引
        try:
            from verda.embedding import ImageEmbedder
            emb = ImageEmbedder("resnet50")
        except ImportError as e:
            raise unittest.SkipTest("torch 不可用：%s" % e)
        if not emb.pretrained:
            raise unittest.SkipTest("没有本地预训练权重，特征无意义")

        cls.idx = CaseIndex(emb)
        cls.idx.build(verbose=False)
        cls.emb = emb

    # ---------------- 建库 ----------------

    def test_index_size(self):
        """AC-06 要求库内 >= 100 张"""
        n = len(self.idx.cases)
        self.assertGreaterEqual(n, 100, "案例库只有 %d 张，少于 100" % n)

    def test_matrix_shape(self):
        self.assertEqual(self.idx.matrix.shape[0], len(self.idx.cases))
        self.assertEqual(self.idx.matrix.shape[1], self.emb.out_dim)

    def test_matrix_normalized(self):
        """特征矩阵每行都该是单位向量，否则余弦相似度算错"""
        import numpy as np
        norms = np.linalg.norm(self.idx.matrix, axis=1)
        self.assertLess(float(np.max(np.abs(norms - 1.0))), 1e-4,
                        "有向量的 L2 范数偏离 1")

    def test_pretrained(self):
        self.assertTrue(self.emb.pretrained, "没加载到预训练权重")

    def test_all_cases_exist(self):
        """清单里每条都得有对应的图文件"""
        for c in self.idx.cases:
            self.assertTrue(os.path.exists(c["abs_path"]),
                            "%s 的文件不存在：%s"
                            % (c["case_id"], c["abs_path"]))

    def test_labels_complete(self):
        """每条案例都该有 room 和 style，否则筛选用不了"""
        for c in self.idx.cases:
            self.assertTrue(c.get("room"), "%s 缺 room" % c["case_id"])
            self.assertTrue(c.get("style"), "%s 缺 style" % c["case_id"])

    # ---------------- 检索 ----------------

    def test_search_by_image_returns_k(self):
        base = self.idx.cases[0]
        hits = self.idx.search_by_image(base["abs_path"], top_k=3,
                                        exclude_case_id=base["case_id"])
        self.assertEqual(len(hits), 3)
        # 不该返回查询自己
        self.assertNotIn(base["case_id"], [h["case_id"] for h in hits])

    def test_search_fields(self):
        """返回结构要带溯源信息（FR-09 要求可点回原页面看作者许可）"""
        base = self.idx.cases[0]
        hit = self.idx.search_by_image(base["abs_path"], top_k=1,
                                       exclude_case_id=base["case_id"])[0]
        for k in ("case_id", "file_path", "score", "room", "style",
                  "source", "source_url", "author", "license", "license_url"):
            self.assertIn(k, hit, "结果缺字段 %s" % k)

    def test_search_scores_descending(self):
        base = self.idx.cases[0]
        hits = self.idx.search_by_image(base["abs_path"], top_k=5,
                                        exclude_case_id=base["case_id"])
        scores = [h["score"] for h in hits]
        self.assertEqual(scores, sorted(scores, reverse=True),
                         "结果没按相似度降序")

    def test_search_with_style_filter(self):
        base = next(c for c in self.idx.cases if c.get("style") == "nordic")
        hits = self.idx.search_by_image(base["abs_path"], top_k=3,
                                        style="nordic",
                                        exclude_case_id=base["case_id"])
        for h in hits:
            self.assertEqual(h["style"], "nordic",
                             "筛 nordic 却返回了 %s" % h["style"])

    def test_search_with_room_filter(self):
        base = next(c for c in self.idx.cases if c.get("room") == "living")
        hits = self.idx.search_by_image(base["abs_path"], top_k=3,
                                        room="living",
                                        exclude_case_id=base["case_id"])
        for h in hits:
            self.assertEqual(h["room"], "living")

    def test_search_by_case_id(self):
        cid = self.idx.cases[0]["case_id"]
        hits = self.idx.search_by_case_id(cid, top_k=3)
        self.assertEqual(len(hits), 3)
        self.assertNotIn(cid, [h["case_id"] for h in hits])

    def test_search_speed(self):
        """检索要快，前端是交互式的"""
        import time
        base = self.idx.cases[0]
        t0 = time.time()
        self.idx.search_by_image(base["abs_path"], top_k=3)
        dt = time.time() - t0
        self.assertLess(dt, 1.0, "单次检索 %.2f 秒，太慢" % dt)

    # ---------------- 配色检索 ----------------

    def test_palette_search(self):
        base = self.idx.cases[0]
        pal = base.get("palette")
        self.assertTrue(pal, "%s 没有调色板数据" % base["case_id"])
        hits = self.idx.search_by_palette(pal, top_k=3)
        self.assertEqual(len(hits), 3)
        # 用自己调色板查，自己应该排第一
        self.assertEqual(hits[0]["case_id"], base["case_id"],
                         "用自己调色板查，第一名却是 %s" % hits[0]["case_id"])

    def test_palette_scores_in_range(self):
        """配色相似度必须在 0~1 之间，不能出现负数"""
        base = self.idx.cases[0]
        hits = self.idx.search_by_palette(base.get("palette"), top_k=5)
        for h in hits:
            self.assertGreaterEqual(h["score"], 0.0,
                                    "相似度是负的：%s" % h["score"])
            self.assertLessEqual(h["score"], 1.0)

    def test_palette_empty(self):
        hits = self.idx.search_by_palette([], top_k=3)
        self.assertEqual(hits, [])

    # ---------------- 查重 ----------------

    def test_find_duplicates(self):
        """B 的包里确实有重复图，这个方法应该能找出来"""
        dups = self.idx.find_duplicates()
        self.assertIsInstance(dups, list)
        for g in dups:
            self.assertGreater(len(g), 1, "重复组里只有一条")
        # 顺便算出去重后的数量
        removed = sum(len(g) - 1 for g in dups)
        unique = len(self.idx.cases) - removed
        self.assertGreaterEqual(unique, 100,
                                "去重后只剩 %d 张，低于 AC-06 的 100 张"
                                % unique)

    # ---------------- 质量评估 ----------------

    def test_evaluate(self):
        ev = self.idx.evaluate(n_queries=30, top_k=3)
        self.assertEqual(ev["queries"], 30)
        for k in ("style_hit_rate", "room_hit_rate", "either_hit_rate"):
            self.assertGreaterEqual(ev[k], 0.0)
            self.assertLessEqual(ev[k], 1.0)

    def test_evaluate_meets_ac06(self):
        """AC-06：top-3 命中率要 >= 80%"""
        ev = self.idx.evaluate(n_queries=30, top_k=3)
        self.assertGreaterEqual(
            ev["either_hit_rate"], 0.8,
            "风格或场景命中率只有 %.1f%%，低于 AC-06 的 80%%"
            % (ev["either_hit_rate"] * 100))


if __name__ == "__main__":
    unittest.main(verbosity=2)
