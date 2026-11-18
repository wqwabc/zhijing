# -*- coding: utf-8 -*-
"""数据结构（对齐 B 的 schema）

字段以 B 的 `schema/plant.schema.json` 和 `data/plants_master.csv` 为准，
不自己另起一套。B 没给但评分要用的三个字段（叶型、质感、叶色）由 loader
从 `leaf` 描述、`morphology` 文本和 `assets_index.json` 的 `dominant_hex` 派生。

与 B 的差异（都是补，不是改）：
    leaf_size   从 leaf 字段（"大叶深裂"/"大叶提琴形"）解析
    texture     从 leaf + morphology 关键词解析，缺省「哑光」
    dominant_hex 从 assets_index.json 取
"""

from dataclasses import dataclass, field
from typing import List, Optional

# ---------------- 枚举（完全照 B 的 schema）----------------

# 株型：B 是这 8 种
FORMS = ("直立", "丛生", "垂吊", "攀援", "莲座", "树形", "剑叶", "附生")

# 叶型（派生字段，按叶片大小粗分）
LEAF_SIZES = ("大叶", "中叶", "细叶")

# 质感（派生字段）
TEXTURES = ("光泽", "哑光", "绒面", "纸质", "革质")

# 风格：B 用英文 key，中文名在 styles.csv
STYLES = ("nordic", "wabi", "midcentury", "minimal", "tropical", "industrial")
STYLE_NAMES = {
    "nordic": "北欧自然",
    "wabi": "日式侘寂",
    "midcentury": "中古复古",
    "minimal": "现代极简",
    "tropical": "热带雨林",
    "industrial": "工业冷调",
}

# 场景：B 用英文 key
ROOMS = ("bedroom", "study", "living", "balcony", "desk")
ROOM_NAMES = {
    "bedroom": "卧室",
    "study": "书房",
    "living": "客厅",
    "balcony": "阳台",
    "desk": "办公桌",
}

# 光照等级：B 用 L1~L4
LIGHT_LEVELS = ("L1", "L2", "L3", "L4")
LIGHT_VALUE = {"L1": 1, "L2": 2, "L3": 3, "L4": 4}
# 反查：数字 -> 等级，比如用户说「我这里光照 2」，对应 L2
LIGHT_BY_VALUE = {v: k for k, v in LIGHT_VALUE.items()}

# 各场景能接受的株高上限（cm），来自 B 的 scenes.csv
# 注意这是 B 的口径，和需求文档里的粗略值不同，以 B 为准
ROOM_HEIGHT_RANGE = {
    "bedroom": (40, 120),
    "study": (20, 90),
    "living": (80, 200),
    "balcony": (30, 150),
    "desk": (8, 50),
}

# 各场景的横向可用宽度（cm），B 没给，按常见家具尺寸估
ROOM_WIDTH = {
    "bedroom": 180,
    "study": 150,
    "living": 240,
    "balcony": 160,
    "desk": 120,
}


def _mid_value(text) -> float:
    """把 "7-10" 这种区间字符串取中值；单个数字原样返回"""
    if text is None:
        return 0.0
    s = str(text).strip()
    if not s:
        return 0.0
    # 只保留数字和小数点、连字符
    cleaned = "".join(ch if ch.isdigit() or ch in ".-" else " " for ch in s)
    parts = [p for p in cleaned.split() if p]
    if not parts:
        return 0.0
    if len(parts) == 1:
        try:
            return float(parts[0])
        except ValueError:
            return 0.0
    try:
        lo, hi = float(parts[0]), float(parts[1])
        return (lo + hi) / 2.0
    except ValueError:
        return 0.0


@dataclass
class Plant:
    """植物主数据（B 的 plants_master.csv 的一行 + 派生字段）"""

    # ---- B 的原始字段 ----
    plant_id: str                       # P01
    name_cn: str
    name_latin: str = ""
    family_cn: str = ""
    form: str = "直立"                  # 8 种株型
    leaf: str = ""                      # 叶型描述，如「大叶深裂」
    height_min_cm: int = 40
    height_max_cm: int = 120
    spread_cm: int = 60
    light_level: str = "L2"             # L1~L4
    water_days: str = "7"               # 可能是 "7-10"
    difficulty: str = "易"
    toxic: str = "safe"                 # safe / toxic / unknown
    pet_safe: bool = True
    style_tags: List[str] = field(default_factory=list)
    scene_tags: List[str] = field(default_factory=list)
    price_cny: str = "0"                # 可能是 "80-200"
    care_min_week: int = 10
    priority: str = "P0"

    # ---- 派生字段（loader 填）----
    leaf_size: str = "中叶"             # 大叶/中叶/细叶
    texture: str = "哑光"               # 光泽/哑光/绒面/纸质/革质
    dominant_hex: str = "#3F6B4A"       # 叶色主色，来自 assets_index
    has_cutout: bool = False

    def __post_init__(self):
        if self.form not in FORMS:
            raise ValueError("%s 的株型 %r 不在 %s 里"
                             % (self.plant_id, self.form, FORMS))
        if self.light_level not in LIGHT_LEVELS:
            raise ValueError("%s 的光照等级 %r 不在 %s 里"
                             % (self.plant_id, self.light_level, LIGHT_LEVELS))
        if self.leaf_size not in LEAF_SIZES:
            raise ValueError("%s 的叶型 %r 不在 %s 里"
                             % (self.plant_id, self.leaf_size, LEAF_SIZES))
        if self.texture not in TEXTURES:
            raise ValueError("%s 的质感 %r 不在 %s 里"
                             % (self.plant_id, self.texture, TEXTURES))

    # ---- 派生属性 ----

    @property
    def height_cm(self) -> float:
        """评分用的株高：取区间中值"""
        return (self.height_min_cm + self.height_max_cm) / 2.0

    @property
    def light_need(self) -> int:
        """光照需求 1~4（L1 耐阴，L4 强光）"""
        return LIGHT_VALUE[self.light_level]

    @property
    def water_days_value(self) -> float:
        """浇水间隔中值（天）"""
        v = _mid_value(self.water_days)
        return v if v > 0 else 7.0

    @property
    def price(self) -> float:
        """参考价中值（元）"""
        return _mid_value(self.price_cny)

    @property
    def is_toxic(self) -> bool:
        """有毒与否：toxic 明确写着 toxic 才算，unknown 保守当无毒但会给提示"""
        return self.toxic == "toxic"

    def name(self) -> str:
        return self.name_cn


@dataclass
class Scene:
    """用户场景。用 B 的 scenes.csv 口径"""

    room: str                        # bedroom/study/living/balcony/desk
    style: str                       # 6 个英文 key
    light: int = 2                   # 1~4，对应用户看到的「光照几档」
    weekly_minutes: int = 30
    has_pet: bool = False
    budget: float = 500.0

    def __post_init__(self):
        if self.room not in ROOMS:
            raise ValueError("场景 %r 不在 %s 里" % (self.room, ROOMS))
        if self.style not in STYLES:
            raise ValueError("风格 %r 不在 %s 里" % (self.style, STYLES))
        if not 1 <= self.light <= 4:
            raise ValueError("光照应在 1~4，收到 %r" % self.light)

    @property
    def room_cn(self) -> str:
        return ROOM_NAMES[self.room]

    @property
    def style_cn(self) -> str:
        return STYLE_NAMES[self.style]

    @property
    def light_level(self) -> str:
        return LIGHT_BY_VALUE[self.light]


@dataclass
class Combo:
    """一套搭配方案"""

    plants: List[Plant]

    def __post_init__(self):
        if not self.plants:
            raise ValueError("组合里至少要有 1 株植物")

    @property
    def total_price(self) -> float:
        return sum(p.price for p in self.plants)

    @property
    def max_height(self) -> float:
        return max(p.height_cm for p in self.plants)

    @property
    def total_care_min(self) -> int:
        return sum(p.care_min_week for p in self.plants)

    def names(self) -> str:
        return "、".join(p.name_cn for p in self.plants)


@dataclass
class DimensionScore:
    """一个维度的评分"""

    name: str
    score: float
    weight: float
    detail: str
    flags: List[str] = field(default_factory=list)

    @property
    def contribution(self) -> float:
        return self.score * self.weight


@dataclass
class ComboScore:
    """整套评分结果"""

    dimensions: List[DimensionScore]
    aesthetic: float
    fit: float
    total: float
    hard_flags: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "aesthetic": round(self.aesthetic, 1),
            "fit": round(self.fit, 1),
            "total": round(self.total, 1),
            "hard_flags": self.hard_flags,
            "reasons": self.reasons,
            "dimensions": [
                {
                    "name": d.name,
                    "score": round(d.score, 1),
                    "weight": round(d.weight, 4),
                    "contribution": round(d.contribution, 2),
                    "detail": d.detail,
                }
                for d in self.dimensions
            ],
        }
