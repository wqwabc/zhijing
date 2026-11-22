# -*- coding: utf-8 -*-
"""推荐演示：给一个场景出三套方案

跑法（在仓库根目录）：
    python demos/demo_recommend.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from verda import Scene
from verda.loader import load_plants
from verda.recommend import PERSONALITIES, recommend, weights_for


def show(plan):
    scene = plan["scene"]
    print("=" * 80)
    print("场景：%s / %s / 光照 %d 档 / %s / 预算 %.0f 元"
          % (scene["room_cn"], scene["style_cn"], scene["light"],
             "有宠物" if scene["has_pet"] else "无宠物", scene["budget"]))
    print("候选池 %d 种，枚举出 %d 种组合"
          % (plan["pool_size"], plan["candidates"]))
    if plan.get("degraded"):
        print("！降级：%s" % plan.get("error", "找不到互不重叠的方案"))
    print("=" * 80)

    for p in plan["plans"]:
        s = p["score"]
        print("\n【%s】%s" % (p["personality"], p["desc"]))
        print("  组合：%s" % p["names"])
        print("  序号：%s" % "、".join(p["plant_ids"]))
        print("  综合 %.1f  = 0.68 x 审美 %.1f + 0.32 x 适配 %.1f"
              % (s["total"], s["aesthetic"], s["fit"]))
        print("  总价 %.0f 元，每周养护 %d 分钟"
              % (p["total_price"], p["care_min_week"]))
        top3 = sorted(s["dimensions"], key=lambda d: -d["score"])[:3]
        print("  最强三项：%s"
              % "，".join("%s %.0f" % (d["name"], d["score"]) for d in top3))
        if s["hard_flags"]:
            print("  硬约束：")
            for f in s["hard_flags"]:
                print("    ! " + f)

    print("\n--- 差异自检（AC-04 要求两两 Jaccard < 0.5）---")
    for j in plan["jaccard"]:
        print("  %s vs %s：%.3f  %s"
              % (j["a"], j["b"], j["jaccard"], "通过" if j["pass"] else "未通过"))


def main():
    plants = load_plants()
    print("从 B 读到 %d 种植物\n" % len(plants))

    print("--- 三种性格的权重（未归一化）---")
    print("%-8s %s" % ("性格", " / ".join(
        "%s %.3f" % (k, v) for k, v in weights_for("稳妥").items())))
    for name in PERSONALITIES:
        w = weights_for(name)
        print("%-8s %s" % (name, " / ".join("%.3f" % v for v in w.values())))
    print()

    # 场景一：客厅 + 北欧 + 光照中等 + 有猫 + 400
    scene1 = Scene(room="living", style="nordic", light=2,
                   weekly_minutes=30, has_pet=True, budget=400)
    t0 = time.time()
    plan1 = recommend(scene1, plants)
    dt1 = time.time() - t0
    show(plan1)
    print("\n耗时 %.2f 秒（FR-03 要求 P95 < 2s）\n" % dt1)

    # 场景二：办公桌 + 极简 + 光照差 + 无宠物 + 200（考验小空间）
    scene2 = Scene(room="desk", style="minimal", light=1,
                   weekly_minutes=10, has_pet=False, budget=200)
    t0 = time.time()
    plan2 = recommend(scene2, plants)
    dt2 = time.time() - t0
    show(plan2)
    print("\n耗时 %.2f 秒\n" % dt2)


if __name__ == "__main__":
    main()
