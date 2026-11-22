# -*- coding: utf-8 -*-
"""改稿演示：拿一套方案，试七种指令

跑法（在仓库根目录）：
    python demos/demo_revise.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from verda import Combo, Scene
from verda.loader import load_plants
from verda.recommend import build_pool, recommend
from verda.revise import INTENTS, revise


def show(res):
    if not res.get("supported"):
        print("  不支持：%s" % res.get("error", ""))
        return

    d = res["diff"]
    print("  指令：%s  ->  识别为「%s」" % (res["instruction"], res["intent"]))
    print("  改前：%s（%.1f 分）"
          % (res["before"]["names"], res["before"]["total"]))
    print("  改后：%s（%.1f 分，%+.1f）"
          % (res["after"]["names"], res["after"]["total"], res["score_delta"]))
    print("  保留率 %.0f%%（%d 株留下，%d 换出，%d 换入）  %s"
          % (d["keep_ratio"] * 100, len(d["kept"]), len(d["removed"]),
             len(d["added"]), "满足约束" if d["satisfied"] else "未完全满足"))
    if d["removed"]:
        print("  换出：%s" % "、".join(d["removed_names"]))
    if d["added"]:
        print("  换入：%s" % "、".join(d["added_names"]))
    print("  说明：%s" % d["note"])


def main():
    plants = load_plants()
    print("从 B 读到 %d 种植物\n" % len(plants))

    scene = Scene(room="living", style="nordic", light=2,
                  weekly_minutes=30, has_pet=True, budget=400)
    pool = build_pool(plants, scene)

    plan = recommend(scene, plants)
    if not plan["plans"]:
        print("推荐失败：%s" % plan.get("error"))
        return

    base = plan["plans"][0]
    by_id = {p.plant_id: p for p in plants}
    combo = Combo([by_id[x] for x in base["plant_ids"]])

    print("=" * 80)
    print("基础方案【%s】" % base["personality"])
    print("  %s（%.1f 分，总价 %.0f 元）"
          % (base["names"], base["score"]["total"], base["total_price"]))
    print("=" * 80)

    for intent in INTENTS:
        print("\n" + "-" * 80)
        res = revise(combo, scene, intent.name, pool=pool, plants=plants)
        show(res)

    # 几句自然语言，测试关键词匹配
    print("\n" + "=" * 80)
    print("自然语言测试")
    print("=" * 80)
    for sentence in ("能不能换几种好养的", "我家有猫，安全点",
                     "预算能省一点吗", "有点太高了",
                     "想更出片一点", "加点垂下来的", "想素一点"):
        print("\n" + "-" * 80)
        res = revise(combo, scene, sentence, pool=pool, plants=plants)
        show(res)

    # 听不懂的情况
    print("\n" + "-" * 80)
    res = revise(combo, scene, "今天天气不错", pool=pool, plants=plants)
    show(res)


if __name__ == "__main__":
    main()
