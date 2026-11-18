# -*- coding: utf-8 -*-
"""演示：用 B 的真实植物数据跑四套方案

跑法（在仓库根目录，即 B/ C/ 的上一层）：
    python C/demo.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from verda import Combo, Scene, explain_weights, score_combo
from verda.loader import load_plants


def show(title, combo, scene):
    result = score_combo(combo, scene)

    print("=" * 78)
    print("%s：%s" % (title, combo.names()))
    print("=" * 78)
    print("综合 %.1f  =  0.68 x 审美 %.1f  +  0.32 x 适配 %.1f"
          % (result.total, result.aesthetic, result.fit))
    print()
    print("%-8s %7s %8s %9s   %s"
          % ("维度", "得分", "权重", "贡献", "说明"))
    print("-" * 78)
    for d in result.dimensions:
        print("%-8s %7.1f %8.4f %9.2f   %s"
              % (d.name, d.score, d.weight, d.contribution, d.detail))

    if result.hard_flags:
        print("\n硬约束（标红，不参与平均）：")
        for f in result.hard_flags:
            print("  ! " + f)

    print("\n理由：")
    for i, r in enumerate(result.reasons, 1):
        print("  %d. %s" % (i, r))
    print()


def main():
    plants = load_plants()
    by_id = {p.plant_id: p for p in plants}
    print("\n从 B 的数据包读到 %d 种植物" % len(plants))
    print("其中 %d 种有去底素材（可放进照片）"
          % sum(1 for p in plants if p.has_cutout))
    print()

    print("权重（文档原值合计 %.2f，已按比例归一化到 1.00）："
          % sum(w for _, w, _ in explain_weights()))
    print("%-8s %10s %14s" % ("维度", "原权重", "归一化后"))
    print("-" * 36)
    for name, raw, norm in explain_weights():
        print("%-8s %10.3f %14.4f" % (name, raw, norm))
    print()

    # 按形态挑几组真实的植物
    def pick(pred, n=3):
        out = [p for p in plants if pred(p)][:n]
        return out

    # 场景：客厅 + 北欧 + 光照 2 档 + 有猫 + 400 预算
    scene = Scene(room="living", style="nordic", light=2,
                  weekly_minutes=30, has_pet=True, budget=400)

    # 方案一：高 + 垂 + 中，稳妥
    tall = pick(lambda p: p.form in ("直立", "树形") and 100 <= p.height_cm <= 160, 1)
    drop = pick(lambda p: p.form == "垂吊", 1)
    mid = pick(lambda p: 40 <= p.height_cm <= 90 and p.form != "垂吊", 1)
    if tall and drop:
        show("方案一（稳妥）", Combo(tall + drop + mid), scene)

    # 方案二：株型拉开，大叶细叶混
    big = pick(lambda p: p.leaf_size == "大叶", 1)
    small = pick(lambda p: p.leaf_size == "细叶", 1)
    other = pick(lambda p: p.form in ("丛生", "附生", "莲座"), 2)
    if big and small and other:
        show("方案二（对比）", Combo(big + small + other), scene)

    # 方案三：偏向热带，色彩有跳色
    trop = [p for p in plants if "tropical" in p.style_tags][:4]
    if len(trop) >= 3:
        show("方案三（个性）", Combo(trop), scene)

    # 反例：办公桌（B 的高度区间 8~50cm）放一堆 100cm 以上的
    bad_scene = Scene(room="desk", style="minimal", light=1,
                      weekly_minutes=10, has_pet=False, budget=150)
    bad = pick(lambda p: p.height_cm >= 100, 3)
    if bad:
        show("反例（场景不匹配）", Combo(bad), bad_scene)


if __name__ == "__main__":
    main()
