# -*- coding: utf-8 -*-
"""案例库批量采集（Pexels 官方 API，需要免费 Key）。

为什么用官方 API 而不是网页：网页搜索被 Cloudflare 拦、镜像通道不稳定；
官方 API 只要一个免费 Key，50 次/小时，足够 30 个配额格各取 4 张。

    set PEXELS_API_KEY=xxxx
    python batch_cases.py --per-cell 4

产物：
    assets/cases/{style}_{room}_{n}.jpg
    data/cases_manifest.csv（room/style/palette/height_profile/来源/许可）
    data/license_table.csv 追加行
"""
from __future__ import annotations
import argparse, io, json, os, sys, time
from pathlib import Path

import requests
from PIL import Image

from common import (CASES, ASSETS, TODAY, ALLOWED_LICENSES, LICENSE_URL,
                    read_csv, write_csv, append_license)

QUERY = {
    ("nordic", "living"): "scandinavian living room plants",
    ("nordic", "bedroom"): "scandinavian bedroom plants",
    ("nordic", "study"): "nordic home office plants",
    ("nordic", "balcony"): "scandinavian balcony plants",
    ("nordic", "desk"): "minimal desk plant",
    ("wabi", "living"): "wabi sabi living room plant",
    ("wabi", "bedroom"): "wabi sabi bedroom plant",
    ("wabi", "study"): "japandi study plants",
    ("wabi", "balcony"): "japanese balcony plants",
    ("wabi", "desk"): "zen desk plant",
    ("midcentury", "living"): "mid century modern living room plants",
    ("midcentury", "bedroom"): "retro bedroom plants",
    ("midcentury", "study"): "mid century home office plant",
    ("midcentury", "balcony"): "retro balcony plants",
    ("midcentury", "desk"): "vintage desk plant",
    ("minimal", "living"): "minimalist living room plant",
    ("minimal", "bedroom"): "minimalist bedroom plant",
    ("minimal", "study"): "minimalist home office plant",
    ("minimal", "balcony"): "minimalist balcony plants",
    ("minimal", "desk"): "minimalist desk plant",
    ("tropical", "living"): "tropical living room plants",
    ("tropical", "bedroom"): "tropical bedroom plants",
    ("tropical", "study"): "tropical home office plants",
    ("tropical", "balcony"): "tropical balcony plants",
    ("tropical", "desk"): "tropical desk plant",
    ("industrial", "living"): "industrial loft living room plants",
    ("industrial", "bedroom"): "industrial bedroom plants",
    ("industrial", "study"): "loft office plants",
    ("industrial", "balcony"): "industrial balcony plants",
    ("industrial", "desk"): "industrial desk plant",
}

STYLE_CN = {"nordic": "北欧", "wabi": "侘寂", "midcentury": "中古", "minimal": "极简",
            "tropical": "热带", "industrial": "工业"}
ROOM_CN = {"bedroom": "卧室", "study": "书房", "living": "客厅", "balcony": "阳台", "desk": "办公桌"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-cell", type=int, default=4)
    ap.add_argument("--max-cells", type=int, default=30)
    a = ap.parse_args()
    key = os.environ.get("PEXELS_API_KEY", "").strip()
    if not key:
        sys.exit("缺少 PEXELS_API_KEY：https://www.pexels.com/api/ 免费申请后 set PEXELS_API_KEY=xxx")
    S = requests.Session()
    S.headers.update({"Authorization": key})
    manifest = read_csv("cases_manifest.csv")
    have = {(r["room"], r["style"]) for r in manifest}
    n = len(manifest)
    lic = []
    for i, ((style, room), q) in enumerate(QUERY.items()):
        if i >= a.max_cells:
            break
        if (room, style) in have:
            continue
        print(f"[{style}/{room}] {q}")
        r = S.get("https://api.pexels.com/v1/search",
                  params={"query": q, "per_page": a.per_cell * 3, "orientation": "landscape"},
                  timeout=40)
        if r.status_code != 200:
            print("   !", r.status_code, r.text[:80])
            continue
        got = 0
        for item in r.json().get("photos", []):
            if got >= a.per_cell:
                break
            url = item["src"].get("large2x") or item["src"]["large"]
            try:
                c = S.get(url, timeout=60).content
                im = Image.open(io.BytesIO(c)); im.load()
            except Exception:
                continue
            if max(im.size) < 800:
                continue
            n += 1
            name = f"{style}_{room}_{got+1:02d}.jpg"
            CASES.mkdir(parents=True, exist_ok=True)
            path = CASES / name
            im.convert("RGB").save(path, quality=92)
            row = {"case_id": f"C-{n:03d}", "file_path": f"assets/cases/{name}",
                   "source": "pexels", "source_url": item["url"], "author": item.get("photographer", ""),
                   "license": ALLOWED_LICENSES["pexels"], "license_url": LICENSE_URL["pexels"],
                   "room": room, "style": style, "palette_hex": "", "plant_count": "",
                   "height_profile": "", "has_plant": "true", "background": "room",
                   "usable_for": "reference", "collected_at": TODAY,
                   "note": f"query: {q}"}
            manifest.append(row)
            lic.append({"item_id": row["case_id"], "file_name": row["file_path"],
                        "source_platform": "Pexels", "source_url": item["url"],
                        "author": item.get("photographer", ""),
                        "license": ALLOWED_LICENSES["pexels"], "license_url": LICENSE_URL["pexels"],
                        "collected_at": TODAY, "proof_path": "data/cases_manifest.csv", "note": q})
            got += 1
        print(f"   -> {got} 张")
        write_csv("cases_manifest.csv", manifest)
        append_license(lic)
        lic.clear()
        time.sleep(1)
    print("done", len(manifest), "cases")


if __name__ == "__main__":
    main()
