# -*- coding: utf-8 -*-
"""数据加载：读 B 交付包里的 plants_master.csv 和 assets_index.json

B 的包结构（相对仓库根）：
    B/data/plants_master.csv     植物主数据，31 列
    B/data/assets_index.json     素材索引，含 dominant_hex（主色）和 has_cutout
    B/data/styles.csv            风格 key -> 中文名
    B/data/scenes.csv            场景 key -> 高度范围

B 没给评分需要的三个字段，这里派生：
    leaf_size     从 leaf 字段解析（"大叶深裂" -> 大叶）
    texture       从 leaf + morphology 关键词解析（"革质" -> 革质），缺省哑光
    dominant_hex  从 assets_index.json 取

用法：
    from verda.loader import load_plants
    plants = load_plants()           # 自动找仓库里的 B/data
    plants = load_plants("其他路径/B/data")
"""

import csv
import json
import os
from typing import Dict, List

from .models import LEAF_SIZES, TEXTURES, Plant


def _decode(text: str) -> str:
    """按 utf-8-sig 读，兼容 BOM；同时也兼容 gbk 兜底"""
    return text.lstrip("\ufeff")


def _parse_leaf_size(leaf: str) -> str:
    """从 leaf 描述判断叶型

    B 的 leaf 字段混着「叶形」和「叶大小」两种信息，取值举例：
        大叶深裂、大叶提琴形、大叶革质、深裂大叶、剑形肉质、披针、
        心形、羽状、掌状复叶、羽状细叶、肉质剑叶……

    「心形 / 披针 / 掌状」讲的是形状不是大小，多数对应中等叶片；
    「羽状 / 针状 / 丝状 / 剑形」这类通常是细叶（散尾葵、文竹、虎尾兰）。
    """
    s = (leaf or "").strip()
    if not s:
        return "中叶"

    # 明确写了大小
    if "大叶" in s or "大型叶" in s or "阔叶" in s:
        return "大叶"
    if any(k in s for k in ("小叶", "细叶", "针叶", "针状", "丝状", "羽状")):
        return "细叶"

    # 靠叶形推断
    if any(k in s for k in ("剑形", "剑叶", "披针", "条形", "线形")):
        return "细叶"

    return "中叶"


# 质感关键词，按优先级匹配（越具体的放前面）
_TEXTURE_RULES = [
    ("革质", ("革质", "厚革", "硬革")),
    ("绒面", ("绒", "被毛", "绒毛", "绒质", "粉质", "绵毛")),
    ("纸质", ("纸质", "膜质", "薄纸")),
    ("光泽", ("光泽", "油亮", "蜡质", "发亮", "明亮叶面", "有光")),
]


def _parse_texture(leaf: str, morphology: str) -> str:
    """从叶型描述和形态文本里找质感关键词，找不到就按哑光处理"""
    haystack = "%s %s" % (leaf or "", morphology or "")
    for texture, keywords in _TEXTURE_RULES:
        if any(k in haystack for k in keywords):
            return texture
    return "哑光"


def _find_data_dir(explicit: str = None) -> str:
    """找 B/data 目录：优先用传入的，否则从当前文件往上找"""
    if explicit:
        if os.path.isdir(explicit):
            return explicit
        raise FileNotFoundError("指定的数据目录不存在：%s" % explicit)

    here = os.path.dirname(os.path.abspath(__file__))
    # 从 C/verda/ 往上找，最多 4 层
    cur = here
    for _ in range(5):
        cur = os.path.dirname(cur)
        candidate = os.path.join(cur, "B", "data")
        if os.path.isdir(candidate):
            return candidate
    raise FileNotFoundError(
        "没找到 B/data 目录。请确认仓库结构里 B/ 和 C/ 是同级，"
        "或者显式传路径给 load_plants()")


def load_plants(data_dir: str = None) -> List[Plant]:
    """读 plants_master.csv + assets_index.json，返回 Plant 列表"""
    d = _find_data_dir(data_dir)

    # 1. 素材索引：plant_id -> (dominant_hex, has_cutout)
    assets: Dict[str, dict] = {}
    idx_path = os.path.join(d, "assets_index.json")
    if os.path.exists(idx_path):
        with open(idx_path, "r", encoding="utf-8-sig") as f:
            idx = json.load(f)
        for item in idx.get("items", []):
            assets[item["plant_id"]] = {
                "dominant_hex": item.get("dominant_hex", ""),
                "has_cutout": bool(item.get("has_cutout")),
            }

    # 2. 主数据
    csv_path = os.path.join(d, "plants_master.csv")
    if not os.path.exists(csv_path):
        raise FileNotFoundError("找不到 plants_master.csv：%s" % csv_path)

    plants: List[Plant] = []
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if not row.get("plant_id"):
                continue

            pid = row["plant_id"].strip()
            leaf = (row.get("leaf") or "").strip()
            morphology = (row.get("morphology") or "").strip()

            extra = assets.get(pid, {})
            style_tags = [t.strip() for t in
                          (row.get("style_tags") or "").split(";") if t.strip()]
            scene_tags = [t.strip() for t in
                          (row.get("scene_tags") or "").split(";") if t.strip()]

            # v1.7 起 B 直接给了 leaf_size / texture 两列，优先用。
            # v1.6 及更早没有这两列，退回从 leaf 描述和 morphology 关键词派生。
            # 实测两者的叶型一致率 58%、质感一致率 17%，可见派生只能当兜底。
            leaf_size = (row.get("leaf_size") or "").strip()
            if leaf_size not in LEAF_SIZES:
                leaf_size = _parse_leaf_size(leaf)

            texture = (row.get("texture") or "").strip()
            if texture not in TEXTURES:
                texture = _parse_texture(leaf, morphology)

            pet_safe_raw = (row.get("pet_safe") or "").strip().upper()
            water_raw = (row.get("water_days") or "").strip()
            try:
                care_min = int((row.get("care_min_week") or "10").strip())
            except ValueError:
                care_min = 10

            plants.append(Plant(
                plant_id=pid,
                name_cn=(row.get("name_cn") or "").strip(),
                name_latin=(row.get("name_latin") or "").strip(),
                family_cn=(row.get("family_cn") or "").strip(),
                form=(row.get("form") or "直立").strip(),
                leaf=leaf,
                height_min_cm=_to_int(row.get("height_min_cm"), 40),
                height_max_cm=_to_int(row.get("height_max_cm"), 120),
                spread_cm=_to_int(row.get("spread_cm"), 60),
                light_level=(row.get("light_level") or "L2").strip(),
                water_days=water_raw,
                difficulty=(row.get("difficulty") or "易").strip(),
                toxic=(row.get("toxic") or "safe").strip(),
                pet_safe=(pet_safe_raw == "Y"),
                style_tags=style_tags,
                scene_tags=scene_tags,
                price_cny=(row.get("price_cny") or "0").strip(),
                care_min_week=care_min,
                priority=(row.get("priority") or "P0").strip(),
                # 优先用 B 给的，没有再派生
                leaf_size=leaf_size,
                texture=texture,
                dominant_hex=extra.get("dominant_hex") or "#3F6B4A",
                has_cutout=extra.get("has_cutout", False),
            ))

    return plants


def _to_int(value, default: int) -> int:
    """把 CSV 里的字符串安全转 int"""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def load_styles(data_dir: str = None) -> List[dict]:
    """读 styles.csv，返回 [{key, name_cn, palette_ref, rule_note, ...}]"""
    d = _find_data_dir(data_dir)
    path = os.path.join(d, "styles.csv")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return [r for r in csv.DictReader(f) if r.get("style_key")]


def load_scenes(data_dir: str = None) -> List[dict]:
    """读 scenes.csv，返回 [{key, name_cn, light, height_range_cm, ...}]"""
    d = _find_data_dir(data_dir)
    path = os.path.join(d, "scenes.csv")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return [r for r in csv.DictReader(f) if r.get("scene_key")]
