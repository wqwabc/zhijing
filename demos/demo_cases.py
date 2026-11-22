# -*- coding: utf-8 -*-
"""案例库检索演示（FR-09）

跑法（在仓库根目录）：
    python demos/demo_cases.py

第一次跑要算 120 张图的特征，CPU 上大约 30~60 秒；
之后有缓存，秒开。
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from verda.case_index import CaseIndex
from verda.embedding import ImageEmbedder


def show_hits(hits, title):
    print("\n%s" % title)
    if not hits:
        print("  （没有结果）")
        return
    for i, h in enumerate(hits, 1):
        print("  %d. %-8s 相似度 %.3f  %s / %s  植物 %s 株  %s"
              % (i, h["case_id"], h["score"], h["room"], h["style"],
                 h["plant_count"], h["height_profile"]))
        print("     %s" % h["file_path"])
        print("     来源：%s / %s / %s"
              % (h["source"], h["author"], h["license"]))


def main():
    print("=" * 78)
    print("案例库检索（ResNet50 语义特征 + 余弦相似度）")
    print("=" * 78)

    print("\n加载模型...")
    t0 = time.time()
    emb = ImageEmbedder("resnet50")
    print("  %s  （加载耗时 %.1f 秒）" % (emb, time.time() - t0))
    if not emb.pretrained:
        print("  ⚠️ 没有加载到预训练权重，特征无意义")

    print("\n建索引...")
    idx = CaseIndex(emb)
    idx.build(verbose=True)

    print("\n案例库标签分布：")
    from collections import Counter
    print("  场景：%s" % dict(Counter(c.get("room") for c in idx.cases)))
    print("  风格：%s" % dict(Counter(c.get("style") for c in idx.cases)))

    # 1. 以图搜图：拿库里某个北欧客厅案例当查询
    demo_case = next(c for c in idx.cases
                     if c.get("style") == "nordic" and c.get("room") == "living")
    t0 = time.time()
    hits = idx.search_by_image(demo_case["abs_path"], top_k=3,
                               exclude_case_id=demo_case["case_id"])
    dt = (time.time() - t0) * 1000
    show_hits(hits, "1. 以图搜图：拿 %s（%s/%s）当查询，找相似（%.0f ms）"
              % (demo_case["case_id"], demo_case["room"], demo_case["style"], dt))

    # 2. 带筛选的检索
    hits = idx.search_by_image(demo_case["abs_path"], top_k=3,
                               style="nordic",
                               exclude_case_id=demo_case["case_id"])
    show_hits(hits, "2. 同样的查询，但限定 style=nordic")

    # 3. 按配色搜（不需要模型）
    palette = demo_case["palette"]
    t0 = time.time()
    hits = idx.search_by_palette(palette, top_k=3)
    dt = (time.time() - t0) * 1000
    show_hits(hits, "3. 按配色搜：用 %s 的调色板 %s（%.1f ms）"
              % (demo_case["case_id"], "/".join(palette), dt))

    # 4. 反查相似案例
    hits = idx.search_by_case_id(demo_case["case_id"], top_k=3)
    show_hits(hits, "4. 反查：和 %s 最像的三个" % demo_case["case_id"])

    # 5. 查重（B 的包里存在同一张图被采两次的情况）
    print("\n" + "=" * 78)
    print("案例库查重")
    print("=" * 78)
    dups = idx.find_duplicates()
    print("  发现 %d 组内容重复的案例：" % len(dups))
    for g in dups:
        print("    · " + "  |  ".join(g))
    if dups:
        total_dup = sum(len(g) - 1 for g in dups)
        print("  去重后实际独立案例：%d 张（清单里写了 %d 张）"
              % (len(idx.cases) - total_dup, len(idx.cases)))

    # 6. 检索质量自评（AC-06 要求 top-3 命中 >= 80%）
    print("\n" + "=" * 78)
    print("检索质量自评（30 组查询）")
    print("=" * 78)
    ev = idx.evaluate(n_queries=30, top_k=3)
    print("  查询数：%d，top-%d" % (ev["queries"], ev["top_k"]))
    print("  同风格命中率：%.1f%%" % (ev["style_hit_rate"] * 100))
    print("  同场景命中率：%.1f%%" % (ev["room_hit_rate"] * 100))
    print("  风格或场景命中率：%.1f%%  %s"
          % (ev["either_hit_rate"] * 100,
             "达到 AC-06 的 80%" if ev["either_hit_rate"] >= 0.8
             else "未达到 AC-06 的 80%"))

    print("\n  前 5 组明细：")
    for d in ev["details"][:5]:
        print("    %s（%s/%s）-> %s   风格%s 场景%s"
              % (d["query"], d["query_style"], d["query_room"],
                 ",".join(d["top"]),
                 "✓" if d["style_hit"] else "✗",
                 "✓" if d["room_hit"] else "✗"))


if __name__ == "__main__":
    main()
