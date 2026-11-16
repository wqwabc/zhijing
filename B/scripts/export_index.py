# -*- coding: utf-8 -*-
"""导出给 D（后端/合成）的素材可用性清单：JSON + CSV。

字段名一旦冻结，改动需提前一天通知 D 并同步 mock。
    python export_index.py
"""
from __future__ import annotations
import json
from common import DATA, TODAY, read_csv

def main() -> None:
    plants = {p["plant_id"]: p for p in read_csv("plants_master.csv")}
    assets = read_csv("assets_manifest.csv")
    items = []
    for a in assets:
        p = plants.get(a["plant_id"], {})
        items.append({
            "plant_id": a["plant_id"],
            "name_cn": p.get("name_cn", ""),
            "name_latin": p.get("name_latin", ""),
            "has_cutout": a["status"] == "ready",
            "file": a["file_path"] or None,
            "width": int(a["width"]) if a["width"] else None,
            "height": int(a["height"]) if a["height"] else None,
            "height_range_cm": [int(p.get("height_min_cm", 0)), int(p.get("height_max_cm", 0))],
            "spread_cm": int(p.get("spread_cm", 0) or 0),
            "dominant_hex": a["dominant_hex"] or None,
            "light_level": p.get("light_level", ""),
            "pet_safe": p.get("pet_safe", "") == "Y",
            "toxic": p.get("toxic", ""),
            "style_tags": [s for s in (p.get("style_tags") or "").split(";") if s],
            "priority": p.get("priority", ""),
        })
    payload = {
        "schema": "verda.assets.index/1.0",
        "generated_at": TODAY,
        "note": "has_cutout=false 的植物在前端标记为「仅参考」并灰显；file 为相对包根路径。",
        "count": {"total": len(items), "cutout_ready": sum(1 for i in items if i["has_cutout"])},
        "items": items,
    }
    (DATA / "assets_index.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                            encoding="utf-8")
    with open(DATA / "assets_index.csv", "w", encoding="utf-8-sig", newline="") as f:
        import csv as _csv
        w = _csv.writer(f)
        w.writerow(["plant_id", "name_cn", "has_cutout", "file", "height_cm_min", "height_cm_max",
                    "dominant_hex", "pet_safe", "light_level", "style_tags"])
        for i in items:
            w.writerow([i["plant_id"], i["name_cn"], "1" if i["has_cutout"] else "0", i["file"] or "",
                        i["height_range_cm"][0], i["height_range_cm"][1], i["dominant_hex"] or "",
                        "1" if i["pet_safe"] else "0", i["light_level"], ";".join(i["style_tags"])])
    print(f"assets_index.json：{payload['count']}")

if __name__ == "__main__":
    main()
