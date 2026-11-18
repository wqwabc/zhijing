# -*- coding: utf-8 -*-
"""风格分类基线单元测试

依赖 torch + sklearn + B 的案例图，首次约 15 秒。

跑法（在仓库根目录）：
    python -m unittest C.test_style -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from verda.style_clf import STYLE_NAMES, StyleClassifier


class TestStyleClassifier(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from sklearn.linear_model import LogisticRegression  # noqa: F401
        except ImportError as e:
            raise unittest.SkipTest("sklearn 不可用：%s" % e)
        try:
            from verda.case_index import CaseIndex
            from verda.embedding import ImageEmbedder
            emb = ImageEmbedder("resnet50")
        except ImportError as e:
            raise unittest.SkipTest("torch 不可用：%s" % e)
        if not emb.pretrained:
            raise unittest.SkipTest("没有本地预训练权重")

        cls.idx = CaseIndex(emb).build(verbose=False)
        cls.clf = StyleClassifier().fit(cls.idx, drop_duplicates=True)
        cls.ev = cls.clf.evaluate(cv=5)

    def test_samples_count(self):
        """去重后应该有 100+ 条训练样本"""
        self.assertGreaterEqual(len(self.clf.y), 90,
                                "训练样本只有 %d 条" % len(self.clf.y))

    def test_classes(self):
        """六种风格都该有样本"""
        self.assertEqual(len(set(self.clf.y)), 6,
                         "类别数是 %d，不是 6" % len(set(self.clf.y)))
        for c in set(self.clf.y):
            self.assertIn(c, STYLE_NAMES, "未知风格 key：%s" % c)

    def test_evaluate_fields(self):
        for k in ("samples", "classes", "folds", "top1_accuracy",
                  "majority_baseline", "random_baseline",
                  "lift_over_majority", "confusion_matrix", "per_class_f1"):
            self.assertIn(k, self.ev, "评估结果缺字段 %s" % k)

    def test_beats_random(self):
        """top-1 必须显著高于随机基线，否则分类器是废的"""
        self.assertGreater(self.ev["top1_accuracy"],
                           self.ev["random_baseline"] * 1.5,
                           "top-1 %.3f 没比随机基线 %.3f 的 1.5 倍高"
                           % (self.ev["top1_accuracy"],
                              self.ev["random_baseline"]))

    def test_beats_majority(self):
        """top-1 要高于「全猜最常见那类」的基线"""
        self.assertGreater(self.ev["top1_accuracy"],
                           self.ev["majority_baseline"],
                           "top-1 %.3f 不如多数类基线 %.3f"
                           % (self.ev["top1_accuracy"],
                              self.ev["majority_baseline"]))

    def test_accuracy_reasonable(self):
        """6 类分类，40% 左右是合理下限（样本只有 110 条）"""
        self.assertGreaterEqual(self.ev["top1_accuracy"], 0.25,
                                "top-1 只有 %.1f%%，太低"
                                % (self.ev["top1_accuracy"] * 100))

    def test_confusion_matrix_shape(self):
        cm = self.ev["confusion_matrix"]
        n = self.ev["classes"]
        self.assertEqual(len(cm), n)
        for row in cm:
            self.assertEqual(len(row), n)
        # 对角线之和 = 正确预测数
        correct = sum(cm[i][i] for i in range(n))
        self.assertAlmostEqual(correct / self.ev["samples"],
                               self.ev["top1_accuracy"], places=2)

    def test_predict_output(self):
        c = self.idx.cases[0]
        style, prob, detail = self.clf.predict(c["abs_path"])
        self.assertIn(style, self.clf.classes_)
        self.assertGreaterEqual(prob, 0.0)
        self.assertLessEqual(prob, 1.0)
        # 概率和应该接近 1
        self.assertAlmostEqual(sum(detail.values()), 1.0, places=2)
        # detail 应该按概率降序
        vals = list(detail.values())
        self.assertEqual(vals, sorted(vals, reverse=True))

    def test_predict_style_or_none(self):
        c = self.idx.cases[0]
        _, prob, _ = self.clf.predict(c["abs_path"])
        # 阈值设成 1.01，一定返回 None
        self.assertIsNone(self.clf.predict_style_or_none(c["abs_path"],
                                                         threshold=1.01))
        # 阈值设成 0，一定返回具体风格
        self.assertIsNotNone(self.clf.predict_style_or_none(c["abs_path"],
                                                           threshold=0.0))

    def test_confusion_table(self):
        lines = self.clf.confusion_table()
        self.assertGreater(len(lines), 3)
        self.assertTrue(any("行=真实" in ln for ln in lines))

    def test_drop_duplicates_effect(self):
        """不去重时样本数应该更多（因为 B 的包里有重复图）"""
        clf2 = StyleClassifier().fit(self.idx, drop_duplicates=False)
        self.assertGreater(len(clf2.y), len(self.clf.y),
                           "不去重的样本数 %d 没比去重的 %d 多"
                           % (len(clf2.y), len(self.clf.y)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
