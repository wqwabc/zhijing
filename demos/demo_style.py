# -*- coding: utf-8 -*-
"""风格分类基线演示

跑法（在仓库根目录）：
    python demos/demo_style.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from verda.case_index import CaseIndex
from verda.embedding import ImageEmbedder
from verda.style_clf import STYLE_NAMES, StyleClassifier


def main():
    print("=" * 78)
    print("风格分类基线（ResNet50 特征 + 逻辑回归）")
    print("=" * 78)

    print("\n1. 准备特征")
    emb = ImageEmbedder("resnet50")
    idx = CaseIndex(emb).build(verbose=False)
    print("   案例 %d 条，特征 %d 维" % (len(idx.cases), idx.matrix.shape[1]))

    dups = idx.find_duplicates()
    print("   其中 %d 组内容重复（%d 条冗余）"
          % (len(dups), sum(len(g) - 1 for g in dups)))

    print("\n2. 训练（去重后）")
    t0 = time.time()
    clf = StyleClassifier().fit(idx, drop_duplicates=True)
    print("   样本 %d 条，%d 类，耗时 %.2f 秒"
          % (len(clf.y), len(set(clf.y)), time.time() - t0))
    from collections import Counter
    print("   类别分布：%s"
          % {STYLE_NAMES.get(k, k): v
             for k, v in Counter(clf.y).most_common()})

    print("\n3. 5 折交叉验证")
    ev = clf.evaluate(cv=5)
    print("   top-1 准确率：%.1f%%" % (ev["top1_accuracy"] * 100))
    print("   多数类基线：  %.1f%%" % (ev["majority_baseline"] * 100))
    print("   随机基线：    %.1f%%" % (ev["random_baseline"] * 100))
    print("   比多数类高：  %+.1f 个百分点" % (ev["lift_over_majority"] * 100))
    print("   （%s）" % ev["note"])

    print("\n4. 各类 F1")
    for k, v in sorted(ev["per_class_f1"].items(), key=lambda x: -x[1]):
        print("   %-12s %.3f" % (STYLE_NAMES.get(k, k), v))

    print("\n5. 混淆矩阵")
    for line in clf.confusion_table():
        print("   " + line)

    print("\n6. 单张预测示例")
    for c in idx.cases[:3]:
        style, prob, detail = clf.predict(c["abs_path"])
        truth = c.get("style")
        mark = "对" if style == truth else "错"
        print("   %s 真实 %-12s 预测 %-12s 置信 %.2f  [%s]"
              % (c["case_id"], STYLE_NAMES.get(truth, truth),
                 STYLE_NAMES.get(style, style), prob, mark))

    print("\n7. 低置信度兜底")
    c = idx.cases[0]
    style, prob, _ = clf.predict(c["abs_path"])
    got = clf.predict_style_or_none(c["abs_path"], threshold=0.95)
    print("   置信度 %.2f，阈值 0.95 -> %s"
          % (prob, "返回 %s" % got if got else "返回 None（让用户手动选）"))

    print("\n" + "=" * 78)
    print("结论")
    print("=" * 78)
    print("  · 6 类分类，随机基线 %.1f%%，多数类基线 %.1f%%"
          % (ev["random_baseline"] * 100, ev["majority_baseline"] * 100))
    print("  · 实际 top-1 %.1f%%，比多数类高 %.1f 个百分点"
          % (ev["top1_accuracy"] * 100, ev["lift_over_majority"] * 100))
    print("  · 样本只有 %d 条（去重后），置信区间较宽，"
          "这个数字只能当下限参考" % ev["samples"])
    print("  · 换成 CLIP 特征后重跑 evaluate() 即可对比，评估代码不用改")


if __name__ == "__main__":
    main()
