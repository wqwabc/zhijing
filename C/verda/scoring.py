# -*- coding: utf-8 -*-
"""七维评分引擎

对应《需求分析 v2.1》第 7 节。字段口径对齐 B 的 plants_master.csv。

权重说明：文档给的六个维度权重是
    0.22 / 0.18 / 0.18 / 0.12 / 0.15 / 0.05 = 0.90
加起来只有 0.90。如果直接加权，审美分满分只有 90，综合分天生打九折。
这里按比例放大到 1.0（每项除以 0.90），相对比例完全不变。
没有把差的 0.10 补给某个维度——那等于凭空改设计意图。

    综合分 = 0.68 × 审美分 + 0.32 × 适配分

硬约束（宠物有毒、光照差 ≥2 档、场景放不下）不参与平均，单独进 hard_flags 标红。
"""

import statistics
from typing import List, Tuple

from .color import is_greenish, is_neutral, lightness
from .models import (
    LIGHT_VALUE, ROOM_HEIGHT_RANGE, ROOM_NAMES, ROOM_WIDTH, STYLE_NAMES,
    Combo, ComboScore, DimensionScore, Plant, Scene,
)

# ---------------- 权重 ----------------

WEIGHTS_RAW = {
    "色彩和谐": 0.22,
    "形态对比": 0.18,
    "层次比例": 0.18,
    "质感叶面": 0.12,
    "疏密留白": 0.15,
    "风格一致": 0.05,
}

_RAW_SUM = sum(WEIGHTS_RAW.values())          # = 0.90
WEIGHTS = {k: v / _RAW_SUM for k, v in WEIGHTS_RAW.items()}

AESTHETIC_RATIO = 0.68
FIT_RATIO = 0.32

# 形态互补的搭配对（同时出现加分）
COMPLEMENTARY_PAIRS = [
    ("直立", "垂吊"),
    ("树形", "垂吊"),
    ("剑叶", "莲座"),
    ("直立", "丛生"),
    ("树形", "附生"),
]


def _clamp(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, x))


# ---------------- 六个审美维度 ----------------

def _score_color(combo: Combo) -> Tuple[float, str]:
    """色彩和谐：绿色占比、明度跨度、中性叶点缀"""
    plants = combo.plants
    n = len(plants)
    colors = [p.dominant_hex for p in plants]

    greens = sum(1 for c in colors if is_greenish(c))
    neutrals = sum(1 for c in colors if is_neutral(c))
    green_ratio = greens / n

    # 绿色基调 55%~75% 最优。两端斜率不同：
    # 绿色太少是「花」（扣得狠），绿色太多只是「单调」（扣得轻）
    if 0.55 <= green_ratio <= 0.75:
        s_green = 100.0
    elif green_ratio < 0.55:
        s_green = _clamp(40.0 + green_ratio / 0.55 * 60.0)
    else:
        s_green = _clamp(100.0 - (green_ratio - 0.75) * 120.0)

    # 明度跨度：真实叶片的明度差多在 0.1~0.3
    ls = [lightness(c) for c in colors]
    span = max(ls) - min(ls)
    if 0.12 <= span <= 0.35:
        s_span = 100.0
    elif span < 0.12:
        s_span = _clamp(100.0 - (0.12 - span) * 350)
    else:
        s_span = _clamp(100.0 - (span - 0.35) * 250)

    # 中性叶：1~2 株点缀最舒服
    if 1 <= neutrals <= 2:
        s_neutral = 100.0
    elif neutrals == 0:
        s_neutral = 70.0
    else:
        s_neutral = 60.0

    score = 0.45 * s_green + 0.35 * s_span + 0.20 * s_neutral
    detail = ("绿色基调 %.0f%%，明度跨度 %.2f，中性叶 %d 株"
              % (green_ratio * 100, span, neutrals))
    return _clamp(score), detail


def _score_form(combo: Combo) -> Tuple[float, str]:
    """形态对比：株型多样性、互补搭配、叶型对比"""
    plants = combo.plants
    forms = [p.form for p in plants]
    uniq_forms = len(set(forms))

    if uniq_forms >= 4:
        s_div = 100.0
    elif uniq_forms == 3:
        s_div = 85.0
    elif uniq_forms == 2:
        s_div = 60.0
    else:
        s_div = 30.0

    hits = sum(1 for a, b in COMPLEMENTARY_PAIRS if a in forms and b in forms)
    s_comp = _clamp(40.0 + hits * 30.0)

    sizes = {p.leaf_size for p in plants}
    if "大叶" in sizes and "细叶" in sizes:
        s_leaf = 100.0
    elif len(sizes) >= 2:
        s_leaf = 75.0
    else:
        s_leaf = 50.0

    score = 0.40 * s_div + 0.40 * s_comp + 0.20 * s_leaf
    detail = ("%d 种株型（%s），互补 %d 对，%d 种叶型"
              % (uniq_forms, "/".join(sorted(set(forms))), hits, len(sizes)))
    return _clamp(score), detail


def _score_layer(combo: Combo) -> Tuple[float, str]:
    """层次比例：高中低三层覆盖、最高与中位高度比、垂吊补层"""
    heights = sorted(p.height_cm for p in combo.plants)

    high = sum(1 for h in heights if h >= 100)
    mid = sum(1 for h in heights if 40 <= h < 100)
    low = sum(1 for h in heights if h < 40)
    layers = sum(1 for c in (high, mid, low) if c > 0)
    s_cover = layers / 3.0 * 100.0

    median = statistics.median(heights)
    ratio = heights[-1] / median if median else 1.0
    if 1.8 <= ratio <= 2.5:
        s_ratio = 100.0
    elif ratio < 1.8:
        s_ratio = _clamp(100.0 - (1.8 - ratio) * 80)
    else:
        s_ratio = _clamp(100.0 - (ratio - 2.5) * 50)

    s_drop = 100.0 if any(p.form == "垂吊" for p in combo.plants) else 70.0

    score = 0.50 * s_cover + 0.30 * s_ratio + 0.20 * s_drop
    detail = ("覆盖 %d 层（高%d/中%d/低%d），最高与中位比 %.2f"
              % (layers, high, mid, low, ratio))
    return _clamp(score), detail


def _score_texture(combo: Combo) -> Tuple[float, str]:
    """质感叶面：2~3 种混合最舒服

    注意：B 的 plants_master.csv 没有「质感」这一列，目前的质感是从
    leaf 描述和 morphology 文本里按关键词推的，48 种里有 38 种落到默认值「哑光」。
    所以「全组都是哑光」更可能是数据没标注，而不是真的单调——这种给 72 而不是 50。
    等 B 补了 texture 列，这个特判就可以去掉。
    """
    textures = [p.texture for p in combo.plants]
    uniq = len(set(textures))

    if uniq == 3:
        score = 100.0
    elif uniq == 2:
        score = 90.0
    elif uniq == 4:
        score = 80.0
    elif uniq == 1:
        # 全是「哑光」很可能是默认值，不当成真的单调
        score = 72.0 if textures[0] == "哑光" else 55.0
    else:
        score = 65.0

    detail = "质感 %d 种（%s）" % (uniq, "/".join(sorted(set(textures))))
    return score, detail


def _score_density(combo: Combo, scene: Scene) -> Tuple[float, str]:
    """疏密留白：盆数、冠幅占空间比、视觉重量均衡"""
    plants = combo.plants
    n = len(plants)

    if 3 <= n <= 6:
        s_n = 100.0
    elif n == 2:
        s_n = 60.0
    elif n == 1:
        s_n = 30.0
    else:
        s_n = 70.0

    room_w = ROOM_WIDTH.get(scene.room, 180)
    spread_ratio = sum(p.spread_cm for p in plants) / room_w
    if 0.30 <= spread_ratio <= 0.50:
        s_spread = 100.0
    elif spread_ratio < 0.30:
        s_spread = _clamp(100.0 - (0.30 - spread_ratio) * 300)
    else:
        s_spread = _clamp(100.0 - (spread_ratio - 0.50) * 150)

    heights = [p.height_cm for p in plants]
    mean_h = statistics.mean(heights)
    cv = statistics.pstdev(heights) / mean_h if mean_h else 0
    if 0.30 <= cv <= 0.70:
        s_bal = 100.0
    elif cv < 0.30:
        s_bal = _clamp(100.0 - (0.30 - cv) * 200)
    else:
        s_bal = _clamp(100.0 - (cv - 0.70) * 120)

    score = 0.40 * s_n + 0.40 * s_spread + 0.20 * s_bal
    detail = ("%d 株，冠幅占 %s %.0f%%，株高离散度 %.2f"
              % (n, ROOM_NAMES.get(scene.room, scene.room),
                 spread_ratio * 100, cv))
    return _clamp(score), detail


def _score_style(combo: Combo, scene: Scene) -> Tuple[float, str]:
    """风格一致：植物 style_tags 命中目标风格的比例"""
    matches = sum(1 for p in combo.plants if scene.style in p.style_tags)
    ratio = matches / len(combo.plants)
    score = _clamp(40.0 + ratio * 60.0)
    detail = "%d/%d 株带「%s」标签（%.0f%%）" % (
        matches, len(combo.plants), STYLE_NAMES.get(scene.style, scene.style),
        ratio * 100)
    return score, detail


# ---------------- 适配分 ----------------

def _score_fit(combo: Combo, scene: Scene) -> Tuple[float, List[str], str]:
    """场景适配：光照、工时、宠物、预算、尺度"""
    plants = combo.plants
    flags: List[str] = []
    parts = []

    # 1. 光照：按最挑的那株算
    need = max(p.light_need for p in plants)
    gap = need - scene.light
    if gap <= 0:
        s_light = 100.0
    elif gap == 1:
        s_light = 75.0
    else:
        s_light = _clamp(100.0 - gap * 35.0)
        names = "、".join(p.name_cn for p in plants if p.light_need == need)
        flags.append("光照差 %d 档：需要 %s 的「%s」放这里会徒长"
                     % (gap, need_to_level(need), names))
    parts.append("光照%s" % ("匹配" if gap <= 0 else "差 %d 档" % gap))

    # 2. 工时：直接用 B 的 care_min_week
    minutes = combo.total_care_min
    if minutes <= scene.weekly_minutes:
        s_time = 100.0
    else:
        s_time = _clamp(100.0 - (minutes - scene.weekly_minutes)
                        / max(scene.weekly_minutes, 1) * 80.0)
    parts.append("每周 %d 分钟" % minutes)

    # 3. 宠物：有毒植物是硬约束
    toxics = [p for p in plants if p.is_toxic]
    if scene.has_pet and toxics:
        s_pet = _clamp(100.0 - len(toxics) * 40.0)
        flags.append("家里有宠物，但含 %d 株有毒植物：%s"
                     % (len(toxics), "、".join(p.name_cn for p in toxics)))
    else:
        s_pet = 100.0
    parts.append("宠物安全" if not (scene.has_pet and toxics) else "有毒风险")

    # 4. 预算
    total_price = combo.total_price
    ratio = total_price / scene.budget if scene.budget else 0
    if ratio <= 0.80:
        s_budget = 100.0
    elif ratio <= 1.00:
        s_budget = 85.0
    else:
        s_budget = _clamp(100.0 - (ratio - 1.0) * 150.0)
    parts.append("预算 %.0f/%.0f 元" % (total_price, scene.budget))

    # 5. 尺度：用 B 的 scenes.csv 高度区间
    lo, hi = ROOM_HEIGHT_RANGE.get(scene.room, (20, 200))
    tallest = combo.max_height
    if tallest <= hi:
        s_scale = 100.0
    else:
        s_scale = _clamp(100.0 - (tallest - hi) / hi * 100.0)
        tall = max(plants, key=lambda p: p.height_cm)
        flags.append("%s 放不下 %.0fcm 的「%s」（B 给的区间 %.0f~%.0fcm）"
                     % (ROOM_NAMES.get(scene.room, scene.room), tallest,
                        tall.name_cn, lo, hi))
    parts.append("最高 %.0fcm（区间 %.0f~%.0f）" % (tallest, lo, hi))

    score = (0.28 * s_light + 0.18 * s_time + 0.24 * s_pet
             + 0.16 * s_budget + 0.14 * s_scale)
    return _clamp(score), flags, "，".join(parts)


def need_to_level(need: int) -> str:
    """1~4 转 B 的 L1~L4"""
    for k, v in LIGHT_VALUE.items():
        if v == need:
            return k
    return "L%d" % need


# ---------------- 理由生成 ----------------

def _build_reasons(combo: Combo, scene: Scene,
                   dims: List[DimensionScore], fit_detail: str) -> List[str]:
    """生成 3~4 条能指着具体植物和数值说的理由"""
    reasons: List[str] = []
    by_name = {d.name: d for d in dims}
    plants = combo.plants

    tallest = max(plants, key=lambda p: p.height_cm)
    reasons.append("「%s」高 %.0fcm，撑起竖向主景，是这套方案的视觉重心。"
                   % (tallest.name_cn, tallest.height_cm))

    has_drop = [p for p in plants if p.form == "垂吊"]
    d_layer = by_name.get("层次比例")
    if has_drop:
        reasons.append("「%s」的垂吊形态补上最下一层，和立柱形成高低呼应（层次分 %.0f）。"
                       % (has_drop[0].name_cn, d_layer.score if d_layer else 0))
    else:
        reasons.append("三层覆盖度：%s。"
                       % (d_layer.detail if d_layer else "—"))

    d_color = by_name.get("色彩和谐")
    if d_color:
        reasons.append("色彩上%s（色彩分 %.0f）。" % (d_color.detail, d_color.score))

    reasons.append("适配方面：%s。" % fit_detail)

    return reasons[:4]


# ---------------- 对外入口 ----------------

def score_combo(combo: Combo, scene: Scene) -> ComboScore:
    """给一套方案打分"""
    color_s, color_d = _score_color(combo)
    form_s, form_d = _score_form(combo)
    layer_s, layer_d = _score_layer(combo)
    texture_s, texture_d = _score_texture(combo)
    density_s, density_d = _score_density(combo, scene)
    style_s, style_d = _score_style(combo, scene)

    dims = [
        DimensionScore("色彩和谐", color_s, WEIGHTS["色彩和谐"], color_d),
        DimensionScore("形态对比", form_s, WEIGHTS["形态对比"], form_d),
        DimensionScore("层次比例", layer_s, WEIGHTS["层次比例"], layer_d),
        DimensionScore("质感叶面", texture_s, WEIGHTS["质感叶面"], texture_d),
        DimensionScore("疏密留白", density_s, WEIGHTS["疏密留白"], density_d),
        DimensionScore("风格一致", style_s, WEIGHTS["风格一致"], style_d),
    ]

    aesthetic = sum(d.score * d.weight for d in dims)
    fit, hard_flags, fit_detail = _score_fit(combo, scene)
    total = AESTHETIC_RATIO * aesthetic + FIT_RATIO * fit
    reasons = _build_reasons(combo, scene, dims, fit_detail)

    return ComboScore(
        dimensions=dims,
        aesthetic=aesthetic,
        fit=fit,
        total=total,
        hard_flags=hard_flags,
        reasons=reasons,
    )


def explain_weights() -> List[Tuple[str, float, float]]:
    """[(维度, 原始权重, 归一化权重)]，答辩展示用"""
    return [(k, WEIGHTS_RAW[k], WEIGHTS[k]) for k in WEIGHTS_RAW]
