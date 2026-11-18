# -*- coding: utf-8 -*-
"""植境 Verda 评分引擎（C 角色交付物）

字段口径对齐 B 的 plants_master.csv，数据由 loader 直接读 B 的交付包。

快速使用：
    from verda import Combo, Scene, score_combo
    from verda.loader import load_plants

    plants = load_plants()                    # 读 B/data/plants_master.csv
    by_id = {p.plant_id: p for p in plants}

    combo = Combo([by_id["P01"], by_id["P10"], by_id["P15"]])
    scene = Scene(room="living", style="nordic", light=2)
    result = score_combo(combo, scene)
    print(result.total, result.hard_flags, result.reasons)
"""

from .loader import load_plants, load_scenes, load_styles   # noqa: F401
from .models import (                                       # noqa: F401
    FORMS, LEAF_SIZES, LIGHT_BY_VALUE, LIGHT_LEVELS, LIGHT_VALUE,
    ROOM_HEIGHT_RANGE, ROOM_NAMES, ROOM_WIDTH, ROOMS,
    STYLE_NAMES, STYLES, TEXTURES,
    Combo, ComboScore, DimensionScore, Plant, Scene,
)
from .recommend import (                                    # noqa: F401
    JACCARD_LIMIT, PERSONALITIES, build_pool, enumerate_combos,
    jaccard, recommend, weights_for,
)
from .revise import (                                       # noqa: F401
    INTENTS, MIN_KEEP_RATIO, Diff, Intent, parse_intent, revise,
)
from .scoring import (                                      # noqa: F401
    AESTHETIC_RATIO, FIT_RATIO, WEIGHTS, WEIGHTS_RAW,
    explain_weights, normalize_weights, rescore, score_combo,
)

__all__ = [
    "Plant", "Scene", "Combo", "DimensionScore", "ComboScore",
    "score_combo", "rescore", "normalize_weights", "explain_weights",
    "recommend", "jaccard", "build_pool", "enumerate_combos", "weights_for",
    "PERSONALITIES", "JACCARD_LIMIT",
    "revise", "parse_intent", "Intent", "Diff", "INTENTS", "MIN_KEEP_RATIO",
    "WEIGHTS", "WEIGHTS_RAW", "AESTHETIC_RATIO", "FIT_RATIO",
    "load_plants", "load_styles", "load_scenes",
    "FORMS", "TEXTURES", "LEAF_SIZES", "STYLES", "ROOMS",
    "STYLE_NAMES", "ROOM_NAMES", "LIGHT_LEVELS", "LIGHT_VALUE",
    "LIGHT_BY_VALUE", "ROOM_HEIGHT_RANGE", "ROOM_WIDTH",
]

__version__ = "0.5.0"

# 注意：图像相关的 case_index / embedding 故意不在这里导出。
# 它们依赖 torch + torchvision，而评分和推荐是纯标准库实现的，
# 顶层 import 会让「只想算个分」的场景也背上 2GB 的 torch 依赖。
# 需要时直接：
#     from verda.embedding import ImageEmbedder
#     from verda.case_index import CaseIndex
