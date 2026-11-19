# -*- coding: utf-8 -*-
"""推荐搜索：给出三套性格不同的方案（FR-03）

对应《需求分析 v2.1》FR-03 和 AC-04：
    输入：场景、风格、光照、每周养护、宠物、预算
    输出：三套性格不同的方案（稳妥 / 对比 / 个性）
    验收：三套两两 Jaccard < 0.5

思路：
    1. 候选池  —— 按场景标签、宠物安全、光照、单株预算过滤，只要带去底素材的
    2. 组合枚举 —— 按株高分高/中/低三层，枚举「1 高 + 1~2 中 + 1~2 低」的搭配
    3. 打分排序 —— 六维分只算一次，三种性格换权重重算综合分（rescore）
    4. 差异化   —— 每套方案要和已选方案 Jaccard < 0.5，保证三套真的不一样

用法：
    from verda.recommend import recommend
    from verda import Scene

    plan = recommend(Scene(room="living", style="nordic", light=2, budget=400))
    for p in plan["plans"]:
        print(p["personality"], p["score"]["total"], p["names"])
"""

from itertools import combinations
from typing import Dict, List, Optional

from .models import ROOM_HEIGHT_RANGE, STYLE_NAMES, Combo, Plant, Scene
from .scoring import WEIGHTS_RAW, rescore, score_combo

# ---------------- 三种性格 ----------------

PERSONALITIES = {
    "稳妥": {
        "desc": "常见品种、风格统一、养护省心，不会出错的一套",
        "boost": {"风格一致": 1.8, "色彩和谐": 1.2},
        "reduce": {"形态对比": 0.7},
        "prefer_priority": "P0",
    },
    "对比": {
        "desc": "高低错落、大叶细叶混搭，视觉上最有张力",
        "boost": {"形态对比": 1.8, "层次比例": 1.6},
        "reduce": {"风格一致": 0.5},
        "prefer_priority": None,
    },
    "个性": {
        "desc": "冷门品种、色彩更出挑，适合想做点不一样的人",
        "boost": {"色彩和谐": 1.7, "质感叶面": 1.4},
        "reduce": {"风格一致": 0.4},
        "prefer_priority": "P1",
    },
}

# 验收阈值：两两 Jaccard 必须小于这个值
JACCARD_LIMIT = 0.5


def weights_for(personality: str) -> Dict[str, float]:
    """按性格算出六维权重（未归一化，交给 score_combo / rescore 归一化）"""
    cfg = PERSONALITIES[personality]
    w = dict(WEIGHTS_RAW)
    for k, factor in cfg["boost"].items():
        w[k] = w[k] * factor
    for k, factor in cfg["reduce"].items():
        w[k] = w[k] * factor
    return w


def jaccard(a: List[Plant], b: List[Plant]) -> float:
    """两个组合的 Jaccard 相似度：交集 / 并集"""
    sa = {p.plant_id for p in a}
    sb = {p.plant_id for p in b}
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / len(sa | sb)


# ---------------- 候选池 ----------------

def build_pool(plants: List[Plant], scene: Scene,
               allow_one_light_gap: bool = True) -> List[Plant]:
    """过滤出能进照片的植物

    规则（顺序有意义，前面的更硬）：
        1. 必须有去底素材，否则放不进照片（FR-07 要求标记「仅参考」并灰显）
        2. 有宠物时排除有毒的（硬约束，AC-05 要求有毒植物 = 0）
        3. 光照：允许比场景低 1 档，差 2 档以上放进来会徒长
        4. 单株价格不超过预算的 60%，否则一株就超支
        5. 株高不超过场景上限
    """
    lo, hi = ROOM_HEIGHT_RANGE.get(scene.room, (20, 200))
    max_price = scene.budget * 0.6 if scene.budget else 1e9
    max_gap = 1 if allow_one_light_gap else 0

    pool = []
    for p in plants:
        if not p.has_cutout:
            continue
        if scene.has_pet and p.is_toxic:
            continue
        if p.light_need - scene.light > max_gap:
            continue
        if p.price > max_price:
            continue
        if p.height_cm > hi:
            continue
        pool.append(p)
    return pool


def split_by_layer(pool: List[Plant]):
    """按株高分三层，每层按「和场景的贴合度」排序后截断

    截断是为了控制组合数量：不截断的话 4×12×8 就是 384 种，
    加上 4/5 株的组合会到几千，打分再快也顶不住。
    """
    high = [p for p in pool if p.height_cm >= 100]
    mid = [p for p in pool if 40 <= p.height_cm < 100]
    low = [p for p in pool if p.height_cm < 40]
    return high, mid, low


def enumerate_combos(high: List[Plant], mid: List[Plant], low: List[Plant],
                     budget: float, max_each: int = 4,
                     price_tolerance: float = 1.15) -> List[List[Plant]]:
    """枚举 3~5 株的组合

    结构原本是「1 株高的 + 1~2 株中的 + 1~2 株低的」，保证层次。
    但小空间会有问题：办公桌的高度区间只有 8~50cm，根本不存在「高」这一层，
    照原结构枚举会直接得 0 个组合。所以这里做了逐层 fallback：
        没高层 -> 把中层最高的几株提上来当高层
        没中层 -> 把低层提上来当中层
        还是没有 -> 只枚举「高 + 中」两株的组合
    """
    # --- 逐层 fallback ---
    if not high and mid:
        ordered = sorted(mid, key=lambda p: -p.height_cm)
        high = ordered[:min(2, len(ordered))]
        mid = [p for p in mid if p not in high]

    if not mid and low:
        ordered = sorted(low, key=lambda p: -p.height_cm)
        mid = ordered[:min(2, len(ordered))]
        low = [p for p in low if p not in mid]

    if not high or not mid:
        return []

    h = high[:max_each]
    m = mid[:max_each + 2]
    lo = low[:max_each]

    limit = budget * price_tolerance if budget else 1e9
    combos: List[List[Plant]] = []

    def total(ps):
        return sum(p.price for p in ps)

    # 2 株：1 高 + 1 中（低层为空时的兜底）
    if not lo:
        for a in h:
            for b in m:
                combo = [a, b]
                if total(combo) <= limit:
                    combos.append(combo)
    else:
        # 3 株：1 高 + 1 中 + 1 低
        for a in h:
            for b in m:
                for c in lo:
                    combo = [a, b, c]
                    if total(combo) <= limit:
                        combos.append(combo)

        # 4 株：1 高 + 2 中 + 1 低
        for a in h:
            for bb in combinations(m, 2):
                for c in lo:
                    combo = [a] + list(bb) + [c]
                    if total(combo) <= limit:
                        combos.append(combo)

        # 5 株：1 高 + 2 中 + 2 低
        if len(lo) >= 2:
            for a in h:
                for bb in combinations(m, 2):
                    for cc in combinations(lo, 2):
                        combo = [a] + list(bb) + list(cc)
                        if total(combo) <= limit:
                            combos.append(combo)

    # 去重（同一组植物不同顺序算一个）
    seen = set()
    uniq = []
    for c in combos:
        key = tuple(sorted(p.plant_id for p in c))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(c)
    return uniq


# ---------------- 主入口 ----------------

def recommend(scene: Scene, plants: List[Plant] = None,
              top_n: int = 3) -> dict:
    """给用户出 n 套方案

    返回结构（直接给前端用）：
        {
          "scene": {...},
          "pool_size": 32,
          "candidates": 480,
          "plans": [
            {
              "personality": "稳妥",
              "desc": "...",
              "names": "龟背竹、绿萝、虎尾兰",
              "plant_ids": ["P01", "P05", "P04"],
              "score": { ...as_dict() }
            }
          ],
          "degraded": false
        }
    """
    if plants is None:
        from .loader import load_plants
        plants = load_plants()

    pool = build_pool(plants, scene)
    high, mid, low = split_by_layer(pool)
    combos = enumerate_combos(high, mid, low, scene.budget)

    result = {
        "scene": {
            "room": scene.room,
            "room_cn": scene.room_cn,
            "style": scene.style,
            "style_cn": scene.style_cn,
            "light": scene.light,
            "has_pet": scene.has_pet,
            "budget": scene.budget,
        },
        "pool_size": len(pool),
        "candidates": len(combos),
        "plans": [],
        "degraded": False,
    }

    if not combos:
        result["degraded"] = True
        result["error"] = ("候选池太小（%d 种），组合不出方案。"
                          "可能是预算太低、光照太差，或者场景里有宠物的限制太严。"
                          % len(pool))
        return result

    # 1. 六个维度只算一次
    bases = []
    for c in combos:
        base = score_combo(Combo(c), scene)
        bases.append((c, base))

    # 2. 按性格逐个选，且和已选的保持差异
    picked: List[dict] = []
    order = ["稳妥", "对比", "个性"][:top_n]

    for personality in order:
        w = weights_for(personality)

        # 换权重重排
        scored = []
        for c, base in bases:
            s = rescore(base, w)
            scored.append((c, s))
        scored.sort(key=lambda x: -x[1].total)

        # 找一个和已选方案 Jaccard < 0.5 的
        chosen: Optional[tuple] = None
        for c, s in scored:
            if all(jaccard(c, p["_combo"]) < JACCARD_LIMIT for p in picked):
                chosen = (c, s)
                break

        if chosen is None:
            # 找不到互不重叠的，退一步允许重叠，但标记降级
            chosen = scored[0]
            result["degraded"] = True

        c, s = chosen
        combo = Combo(c)
        picked.append({
            "_combo": c,                 # 内部用，返回前删掉
            "personality": personality,
            "desc": PERSONALITIES[personality]["desc"],
            "names": combo.names(),
            "plant_ids": [p.plant_id for p in c],
            "total_price": round(combo.total_price, 1),
            "care_min_week": combo.total_care_min,
            "score": s.as_dict(),
        })

    for p in picked:
        p.pop("_combo", None)
    result["plans"] = picked

    # 3. 自检：两两 Jaccard（AC-04 要求都小于 0.5）
    result["jaccard"] = _pairwise(picked, plants)

    return result


def _pairwise(plans: List[dict], all_plants: List[Plant]) -> List[dict]:
    """算三套方案两两之间的 Jaccard，用来验证 AC-04"""
    by_id = {p.plant_id: p for p in all_plants}
    out = []
    for i in range(len(plans)):
        for j in range(i + 1, len(plans)):
            a = [by_id[x] for x in plans[i]["plant_ids"] if x in by_id]
            b = [by_id[x] for x in plans[j]["plant_ids"] if x in by_id]
            out.append({
                "a": plans[i]["personality"],
                "b": plans[j]["personality"],
                "jaccard": round(jaccard(a, b), 3),
                "pass": jaccard(a, b) < JACCARD_LIMIT,
            })
    return out
