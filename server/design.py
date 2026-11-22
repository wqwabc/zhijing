# -*- coding: utf-8 -*-
"""大模型选株 → 规则校验 → 确定性评分。

模型只出“选哪几株、多高、放哪”，所有约束在本地再校验一遍：
宠物安全、光照档位、株高区间、素材可用、数量上限。
模型失败/超时/JSON 不合法时，退回 verda.recommend 的规则方案（AC-10）。
"""

from __future__ import annotations

import time
from dataclasses import asdict

from verda import Combo, Scene, recommend, score_combo

from . import llm
from .room import analyze

MAX_DESIGN_ITEMS = 5


def build_catalog(plants) -> list:
    out = []
    for p in plants:
        out.append({
            "plant_id": p.plant_id,
            "name_cn": p.name_cn,
            "height_min_cm": p.height_min_cm,
            "height_max_cm": p.height_max_cm,
            "light_level": p.light_level,
            "pet_safe": bool(p.pet_safe),
            "style_tags": list(p.style_tags),
            "price_cny": p.price_cny,
        })
    return out


def _light_num(p) -> int:
    try:
        return int(str(p.light_level).replace("L", ""))
    except ValueError:
        return 2


def _height_mid(p) -> int:
    return int(round((p.height_min_cm + p.height_max_cm) / 2.0))


def _validate(proposal: dict, by_id: dict, assets: dict, scene: Scene,
              count: int) -> list:
    items, seen = [], set()
    for raw in proposal.get("plants", []):
        if not isinstance(raw, dict):
            continue
        pid = raw.get("plant_id")
        if not isinstance(pid, str) or pid in seen:
            continue
        p = by_id.get(pid)
        if p is None:
            continue
        if not assets["by_id"].get(pid, {}).get("available"):
            continue
        if scene.has_pet and not p.pet_safe:
            continue
        if _light_num(p) > scene.light + 1:
            continue

        try:
            height = float(raw.get("height_cm", _height_mid(p)))
        except (TypeError, ValueError):
            height = _height_mid(p)
        height = min(max(height, p.height_min_cm), p.height_max_cm)

        try:
            x_frac = float(raw.get("x_frac", 0.5))
        except (TypeError, ValueError):
            x_frac = 0.5
        x_frac = min(max(x_frac, 0.08), 0.92)

        layer = raw.get("layer", 0)
        if type(layer) is not int or layer < 0:
            layer = 0

        items.append({
            "plant_id": pid,
            "height_cm": round(height, 1),
            "x_frac": round(x_frac, 3),
            "layer": layer,
            "why": str(raw.get("why", ""))[:120],
        })
        seen.add(pid)
        if len(items) >= max(1, min(count, MAX_DESIGN_ITEMS)):
            break
    return items


def _fallback(scene: Scene, plants, assets: dict, count: int) -> list:
    try:
        result = recommend(scene, plants)
        plans = result.get("plans") or []
    except Exception:
        plans = []

    ids = list(plans[0].get("plant_ids") or []) if plans else []
    by_id = {p.plant_id: p for p in plants}
    if not ids:
        pool = [p for p in plants
                if assets["by_id"].get(p.plant_id, {}).get("available")
                and (not scene.has_pet or p.pet_safe)]
        ids = [p.plant_id for p in pool[:count]]

    items = []
    ids = ids[:max(1, count)]
    n = max(1, len(ids))
    for i, pid in enumerate(ids):
        p = by_id.get(pid)
        if p is None:
            continue
        items.append({
            "plant_id": pid,
            "height_cm": _height_mid(p),
            "x_frac": round((i + 1.0) / (n + 1.0), 3),
            "layer": 0,
            "why": "规则推荐：按场景、光照与宠物约束筛选",
        })
    return items


def design(photo_path: str, scene: Scene, plants, assets: dict,
           count: int = 3) -> dict:
    t0 = time.time()
    features = analyze(photo_path)
    catalog = build_catalog(plants)
    by_id = {p.plant_id: p for p in plants}

    proposal = None
    if llm.available():
        proposal = llm.plan_plants(features, asdict(scene), catalog, count)

    items = _validate(proposal, by_id, assets, scene, count) if proposal else []
    source = "llm" if items else "rules"
    summary = (proposal or {}).get("summary", "") if source == "llm" else ""

    if not items:
        items = _fallback(scene, plants, assets, count)

    combo = Combo([by_id[it["plant_id"]] for it in items])
    score = score_combo(combo, scene).as_dict()

    return {
        "items": items,
        "source": source,
        "model": (proposal or {}).get("_model", llm._config()["model"]),
        "llm_available": llm.available(),
        "summary": summary,
        "features": features,
        "score": score,
        "elapsed_ms": round((time.time() - t0) * 1000, 1),
    }
