# -*- coding: utf-8 -*-
"""一句话改稿（FR-08）

支持的七种指令，全部靠关键词匹配，不依赖 LLM：
    更好养      省心、懒人、少打理 —— 换成难度「易」且养护时间短的
    对猫狗安全  猫、狗、宠物 —— 换成 pet_safe 且无毒的
    预算降一档  预算、便宜、省钱 —— 换贵的，总价压到预算 80% 以内
    再矮一点    矮、低、小一点 —— 把最高的换矮
    更有张力    张力、冲击、夸张 —— 换一株最能提升形态对比的
    加一点垂坠  垂坠、藤、瀑布 —— 补一株垂吊，或把非垂吊的换成垂吊
    更安静      安静、素、简约 —— 换权重，压风格一致和色彩，抬层次

验收（FR-08）：
    · 过滤类改稿保留原方案 >= 50%
    · 返回 diff
    · 改后满足新约束

「保留 >= 50%」是硬要求，所以**最多只能换掉一半**。如果原方案里有超过一半的植物
不符合新约束，就只换最差的那几株，并在 note 里说明「部分约束未完全满足」——
宁可如实告知，也不偷偷全换掉。
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .models import Combo, Plant, Scene
from .scoring import WEIGHTS_RAW, rescore, score_combo

# 改稿后必须保留的最低比例（FR-08 的验收阈值）
MIN_KEEP_RATIO = 0.5

# 预算降一档后，总价要压到预算的这个倍数以内
BUDGET_TARGET = 0.85

# 「更好养」的养护时间上限（分钟/周/株）
EASY_CARE_MAX = 15


@dataclass
class Intent:
    """解析出来的改稿意图"""

    name: str
    kind: str                       # filter / boost / add / weight
    keywords: List[str]


INTENTS: List[Intent] = [
    Intent("更好养", "filter",
           ["好养", "省心", "省事", "懒人", "少打理", "不用管", "放着就行", "皮实"]),
    Intent("对猫狗安全", "filter",
           ["猫", "狗", "宠物", "安全", "无毒"]),
    Intent("预算降一档", "filter",
           ["预算", "便宜", "省钱", "贵", "降一档", "少花"]),
    Intent("再矮一点", "filter",
           ["矮", "低一点", "小一点", "别太高", "太高"]),
    Intent("更有张力", "boost",
           ["张力", "冲击", "夸张", "戏剧", "抢眼", "视觉", "出片",
            "好看", "惊艳", "有型"]),
    Intent("加一点垂坠", "add",
           ["垂坠", "垂吊", "垂下", "垂下来", "藤", "瀑布", "挂下来"]),
    Intent("更安静", "weight",
           ["安静", "素", "简约", "低调", "克制", "极简", "简单", "清爽", "干净"]),
]


@dataclass
class Diff:
    """改稿前后的差异"""

    kept: List[Plant] = field(default_factory=list)
    removed: List[Plant] = field(default_factory=list)
    added: List[Plant] = field(default_factory=list)
    keep_ratio: float = 1.0
    satisfied: bool = True
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "kept": [p.plant_id for p in self.kept],
            "kept_names": [p.name_cn for p in self.kept],
            "removed": [p.plant_id for p in self.removed],
            "removed_names": [p.name_cn for p in self.removed],
            "added": [p.plant_id for p in self.added],
            "added_names": [p.name_cn for p in self.added],
            "keep_ratio": round(self.keep_ratio, 3),
            "satisfied": self.satisfied,
            "note": self.note,
        }


# ---------------- 意图解析 ----------------

def parse_intent(instruction: str) -> Optional[Intent]:
    """从一句话里认出要改什么

    按出现顺序匹配，先命中的优先。「对猫狗安全」放在「更好养」后面，
    是为了让「好养的、对猫安全的」这种复合句先命中外层的「好养」。
    """
    text = (instruction or "").strip()
    if not text:
        return None
    for intent in INTENTS:
        if any(k in text for k in intent.keywords):
            return intent
    return None


# ---------------- 约束判定 ----------------

def _satisfies(p: Plant, intent: Intent, scene: Scene,
               ref_max_height: float = None) -> bool:
    """这株植物是否满足改稿约束"""
    if intent.name == "更好养":
        return p.difficulty == "易" and p.care_min_week <= EASY_CARE_MAX

    if intent.name == "对猫狗安全":
        return p.pet_safe and not p.is_toxic

    if intent.name == "预算降一档":
        # 单株价格不超过「目标总价」的三分之一，避免一株吃掉全部预算
        cap = scene.budget * BUDGET_TARGET / 3.0
        return p.price <= cap

    if intent.name == "再矮一点":
        if ref_max_height is None:
            ref_max_height = 100
        return p.height_cm <= ref_max_height

    # boost / add / weight 不走 satisfies，单独处理
    return True


def _penalty(p: Plant, intent: Intent, scene: Scene,
             ref_max_height: float = None) -> float:
    """不合格程度，用来决定先换谁（值越大越该换）"""
    if _satisfies(p, intent, scene, ref_max_height):
        return 0.0
    if intent.name == "更好养":
        score = 0.0
        if p.difficulty != "易":
            score += 2.0
        if p.care_min_week > EASY_CARE_MAX:
            score += (p.care_min_week - EASY_CARE_MAX) / 10.0
        return score
    if intent.name == "对猫狗安全":
        return 2.0 if p.is_toxic else 1.0
    if intent.name == "预算降一档":
        cap = scene.budget * BUDGET_TARGET / 3.0
        return max(0.0, (p.price - cap) / max(cap, 1))
    if intent.name == "再矮一点":
        return max(0.0, (p.height_cm - (ref_max_height or 100)) / 50.0)
    return 0.0


# ---------------- 替换候选 ----------------

def _candidates(pool: List[Plant], used: set, scene: Scene,
                intent: Intent, template: Plant,
                ref_max_height: float = None) -> List[Plant]:
    """找能替换 template 的植物

    优先同层（株高接近），其次满足约束、没被用过、有去底素材。
    """
    out = []
    for p in pool:
        if p.plant_id in used:
            continue
        if not p.has_cutout:
            continue
        if scene.has_pet and p.is_toxic:
            continue
        if not _satisfies(p, intent, scene, ref_max_height):
            continue
        # 株高差不超过 60%，避免换完层次乱掉
        if abs(p.height_cm - template.height_cm) > template.height_cm * 0.6:
            continue
        out.append(p)

    # 按「和原株的株高接近程度」排序，越接近越优先
    out.sort(key=lambda x: abs(x.height_cm - template.height_cm))
    return out


# ---------------- 主流程 ----------------

def revise(combo: Combo, scene: Scene, instruction: str,
           pool: List[Plant] = None, plants: List[Plant] = None) -> dict:
    """按一句话改稿

    返回结构：
        {
          "instruction": "更好养",
          "intent": "更好养",
          "supported": true,
          "before": { names, total, plant_ids },
          "after":  { names, total, plant_ids, score },
          "score_delta": -3.2,
          "diff": { kept, removed, added, keep_ratio, satisfied, note }
        }
    """
    plant_list = plants
    if plant_list is None:
        from .loader import load_plants
        plant_list = load_plants()
    if pool is None:
        from .recommend import build_pool
        pool = build_pool(plant_list, scene)

    intent = parse_intent(instruction)
    if intent is None:
        return {
            "instruction": instruction,
            "supported": False,
            "error": "没听懂要改什么。支持的指令：%s"
                     % "、".join(i.name for i in INTENTS),
        }

    before_score = score_combo(combo, scene)
    original = list(combo.plants)
    max_change = max(1, len(original) // 2)      # 最多换一半（3 株换 1 株）

    if intent.kind == "filter":
        result = _revise_by_filter(combo, scene, intent, pool,
                                   original, max_change, before_score)
    elif intent.kind == "boost":
        result = _revise_by_boost(combo, scene, intent, pool,
                                  original, max_change, before_score)
    elif intent.kind == "add":
        result = _revise_by_add(combo, scene, intent, pool,
                                original, max_change, before_score)
    else:   # weight
        result = _revise_by_weight(combo, scene, intent, before_score)

    result["instruction"] = instruction
    result["intent"] = intent.name
    result["supported"] = True
    return result


def _pack(before_combo, before_score, after_combo, after_score,
          diff: Diff) -> dict:
    return {
        "before": {
            "names": before_combo.names(),
            "plant_ids": [p.plant_id for p in before_combo.plants],
            "total": round(before_score.total, 1),
        },
        "after": {
            "names": after_combo.names(),
            "plant_ids": [p.plant_id for p in after_combo.plants],
            "total": round(after_score.total, 1),
            "score": after_score.as_dict(),
        },
        "score_delta": round(after_score.total - before_score.total, 1),
        "diff": diff.as_dict(),
    }


def _revise_by_filter(combo, scene, intent, pool, original,
                      max_change, before_score) -> dict:
    """过滤型：把不合格的换掉，但最多换一半"""
    # 算每株的不合格程度
    ref_max = None
    if intent.name == "再矮一点":
        ref_max = max(p.height_cm for p in original) * 0.8

    scored = [(p, _penalty(p, intent, scene, ref_max)) for p in original]
    bad = [(p, pen) for p, pen in scored if pen > 0]
    bad.sort(key=lambda x: -x[1])            # 最差的排前面

    to_replace = bad[:max_change]
    removed = [p for p, _ in to_replace]
    removed_ids = {p.plant_id for p in removed}
    kept = [p for p in original if p.plant_id not in removed_ids]

    added: List[Plant] = []
    used = {p.plant_id for p in kept}
    for old in removed:
        cands = _candidates(pool, used, scene, intent, old, ref_max)
        if not cands:
            continue
        new = cands[0]
        added.append(new)
        used.add(new.plant_id)

    # 如果没找到替代，就留着原来的（总比少一株好）
    for old in removed:
        if len(added) < len(removed):
            added.append(old)

    after_plants = kept + added
    after_combo = Combo(after_plants)
    after_score = score_combo(after_combo, scene)

    kept_n = len(kept)
    keep_ratio = kept_n / len(original) if original else 1.0
    still_bad = [p for p in after_plants
                 if not _satisfies(p, intent, scene, ref_max)]

    diff = Diff(
        kept=kept,
        removed=[p for p in removed if p not in added],
        added=[p for p in added if p not in removed],
        keep_ratio=keep_ratio,
        satisfied=not still_bad,
        note=(
            "改后仍有 %d 株不满足「%s」：%s。因为要求保留原方案 >= 50%%，"
            "所以只换了 %d 株。"
            % (len(still_bad), intent.name,
               "、".join(p.name_cn for p in still_bad), len(removed))
            if still_bad
            else "已全部满足「%s」。" % intent.name
        ),
    )
    return _pack(combo, before_score, after_combo, after_score, diff)


def _revise_by_boost(combo, scene, intent, pool, original,
                     max_change, before_score) -> dict:
    """增强型：换一株最能提升目标维度的"""
    # target 维度：更有张力 -> 形态对比
    target_dim = "形态对比" if intent.name == "更有张力" else "层次比例"

    best = None
    best_gain = -1e9
    for i, old in enumerate(original):
        for new in _candidates(pool, {p.plant_id for p in original},
                               scene, intent, old):
            trial = original[:i] + [new] + original[i + 1:]
            s = score_combo(Combo(trial), scene)
            dim = next(d for d in s.dimensions if d.name == target_dim)
            base_dim = next(d for d in before_score.dimensions
                            if d.name == target_dim)
            gain = (dim.score - base_dim.score) + (s.total - before_score.total) * 0.3
            if gain > best_gain:
                best_gain = gain
                best = (old, new, trial, s)

    if best is None or best_gain <= 0:
        diff = Diff(kept=original, keep_ratio=1.0, satisfied=True,
                    note="现在的组合在「%s」上已经是最优，换任何一株都不会更好。"
                         % target_dim)
        return _pack(combo, before_score, combo, before_score, diff)

    old, new, trial, s = best
    kept = [p for p in original if p.plant_id != old.plant_id]
    diff = Diff(
        kept=kept,
        removed=[old],
        added=[new],
        keep_ratio=len(kept) / len(original),
        satisfied=True,
        note="把「%s」换成「%s」，%s %+.0f 分。"
             % (old.name_cn, new.name_cn, target_dim,
                next(d for d in s.dimensions if d.name == target_dim).score
                - next(d for d in before_score.dimensions if d.name == target_dim).score),
    )
    return _pack(combo, before_score, Combo(trial), s, diff)


def _revise_by_add(combo, scene, intent, pool, original,
                   max_change, before_score) -> dict:
    """加垂坠：优先补一株垂吊，其次把非垂吊的换成垂吊"""
    has_drop = any(p.form == "垂吊" for p in original)

    if has_drop:
        diff = Diff(kept=original, keep_ratio=1.0, satisfied=True,
                    note="这套方案里已经有垂吊植物了，再加会显得拥挤。"
                         "如果想更垂，可以把原来那株往前挪。")
        return _pack(combo, before_score, combo, before_score, diff)

    # 找垂吊替代
    for old in original:
        for new in _candidates(pool, {p.plant_id for p in original},
                               scene, intent, old):
            if new.form != "垂吊":
                continue
            trial = [p for p in original if p.plant_id != old.plant_id] + [new]
            s = score_combo(Combo(trial), scene)
            kept = [p for p in original if p.plant_id != old.plant_id]
            diff = Diff(
                kept=kept,
                removed=[old],
                added=[new],
                keep_ratio=len(kept) / len(original),
                satisfied=True,
                note="把「%s」换成垂吊的「%s」，补上最下面一层。"
                     % (old.name_cn, new.name_cn),
            )
            return _pack(combo, before_score, Combo(trial), s, diff)

    diff = Diff(kept=original, keep_ratio=1.0, satisfied=False,
                note="候选池里没有可用的垂吊植物（可能是光照或预算限制），"
                     "这次没能加上。")
    return _pack(combo, before_score, combo, before_score, diff)


def _revise_by_weight(combo, scene, intent, before_score) -> dict:
    """更安静：不换植物，只调权重重算"""
    w = dict(WEIGHTS_RAW)
    w["层次比例"] *= 1.4
    w["疏密留白"] *= 1.3
    w["色彩和谐"] *= 0.7
    w["形态对比"] *= 0.6

    after_score = rescore(before_score, w)
    diff = Diff(kept=list(combo.plants), keep_ratio=1.0, satisfied=True,
                note="「更安静」不换植物，只是把评分口径调向层次和留白、压低色彩和对比。"
                     "如果要真的少一点东西，可以说「去掉一株」。")
    return _pack(combo, before_score, combo, after_score, diff)
