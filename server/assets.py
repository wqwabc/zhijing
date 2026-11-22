# -*- coding: utf-8 -*-
"""FR-05 素材可用性清单

数据源是 B 的 data/assets_index.json，这里做三件事：

1. 路径规范化：索引里 P45、P48 用了反斜杠（``assets\\cutout\\...``），
   上 Linux 会 404，统一改正斜杠（已提给 B，后端先自行兜底）。
2. kind 区分：索引暂无 photo/illustration 字段，按文件路径推导——
   ``assets/illustrations/`` 开头为 illustration，其余为 photo。
   产品原则「绝不用插画冒充照片」，该字段会透传给前端（FR-07）。
3. available 校验：has_cutout 且文件真实存在才可放入照片。
"""

import hashlib
import json
import os
import threading

_CACHE_LOCK = threading.Lock()
_CACHE = {}          # (index_path, mtime, size) -> (etag, by_id, items)


def _normalize_file(file_field: str) -> str:
    return (file_field or "").replace("\\", "/")


def _derive_kind(file_field: str) -> str:
    return "illustration" if "/illustrations/" in file_field else "photo"


def load_assets(repo_root: str) -> dict:
    """读素材索引，返回
    {"etag": ..., "by_id": {plant_id: {...}}, "items": [...]}（带缓存）"""
    index_path = os.path.join(repo_root, "data", "assets_index.json")
    with open(index_path, "rb") as f:
        raw = f.read()
    mtime = os.path.getmtime(index_path)
    key = (index_path, mtime, len(raw))
    with _CACHE_LOCK:
        if key in _CACHE:
            return _CACHE[key]

    idx = json.loads(raw.decode("utf-8-sig"))
    by_id, items = {}, []
    for it in idx.get("items", []):
        file_norm = _normalize_file(it.get("file", ""))
        kind = _derive_kind(file_norm)
        abs_path = os.path.join(repo_root, file_norm.replace("/", os.sep))
        available = bool(it.get("has_cutout")) and os.path.isfile(abs_path)

        entry = {
            "plant_id": it.get("plant_id", ""),
            "name_cn": it.get("name_cn", ""),
            "available": available,
            "kind": kind,
            "file": file_norm,
            "abs_path": abs_path,
            "width": it.get("width", 0),
            "height": it.get("height", 0),
            "height_range_cm": it.get("height_range_cm", [0, 0]),
            "spread_cm": it.get("spread_cm", 0),
            "dominant_hex": it.get("dominant_hex", ""),
        }
        by_id[entry["plant_id"]] = entry

        items.append({
            "plant_id": entry["plant_id"],
            "name_cn": entry["name_cn"],
            "available": available,
            "kind": kind,
            "width": entry["width"],
            "height": entry["height"],
            "height_range_cm": entry["height_range_cm"],
            "dominant_hex": entry["dominant_hex"],
            "thumb_url": "/api/assets/%s/thumb" % entry["plant_id"],
            "image_url": "/api/assets/%s/image" % entry["plant_id"],
        })

    counts = {"total": len(items)}
    counts["available"] = sum(1 for i in items if i["available"])
    counts["photo"] = sum(1 for i in items
                          if i["available"] and i["kind"] == "photo")
    counts["illustration"] = sum(1 for i in items
                                 if i["available"] and i["kind"] == "illustration")

    result = {
        "schema": idx.get("schema", "verda.assets.index/1.0"),
        "etag": hashlib.sha256(raw).hexdigest()[:16],
        "by_id": by_id,
        "items": items,
        "counts": counts,
    }
    with _CACHE_LOCK:
        _CACHE.clear()                       # 只保留最新一份
        _CACHE[key] = result
    return result
