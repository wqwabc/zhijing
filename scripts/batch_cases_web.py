# -*- coding: utf-8 -*-
"""案例库采集（无 Key，经 r.jina.ai 读 Pexels 搜索页）。

按 6 风格 × 5 场景的配额取图，作者从图片下载名 `dl=pexels-{author}-{id}.jpg` 解析。
    python batch_cases_web.py --per-cell 4
"""
from __future__ import annotations
import argparse, io, json, re, time
from pathlib import Path

import requests
from PIL import Image

from common import (CASES, ASSETS, TODAY, ALLOWED_LICENSES, LICENSE_URL,
                    read_csv, write_csv, append_license)

S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) VerdaBot/0.6"})
JINA = "https://r.jina.ai/"
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


def search(query: str):
    url = JINA + "https://www.pexels.com/search/" + requests.utils.quote(query) + "/"
    r = S.get(url, timeout=90)
    if r.status_code != 200:
        return []
    text = r.text
    hits = re.findall(r"https://www\.pexels\.com/photo/([a-z0-9\-]+?)-(\d+)/", text)
    authors = dict(re.findall(r"/photos/(\d+)/[^\"\s]*?dl=pexels-([a-z0-9\-]+)-\d+\.jpg", text))
    out, seen = [], set()
    for slug, pid in hits:
        if pid in seen:
            continue
        seen.add(pid)
        out.append({"id": pid, "slug": slug.replace("-", " "),
                    "page": f"https://www.pexels.com/photo/{slug}-{pid}/",
                    "author": authors.get(pid, "")})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-cell", type=int, default=4)
    a = ap.parse_args()
    manifest = read_csv("cases_manifest.csv")
    have = {(r["room"], r["style"]) for r in manifest}
    n = len(manifest)
    lic = []
    for (style, room), q in QUERY.items():
        if (room, style) in have:
            continue
        print(f"[{style}/{room}] {q}", flush=True)
        got = 0
        for c in search(q):
            if got >= a.per_cell:
                break
            url = (f"https://images.pexels.com/photos/{c['id']}/pexels-photo-{c['id']}.jpeg"
                   f"?auto=compress&cs=tinysrgb&w=1800")
            try:
                r = S.get(url, timeout=60)
                im = Image.open(io.BytesIO(r.content)); im.load()
            except Exception:
                continue
            if max(im.size) < 800:
                continue
            got += 1
            n += 1
            name = f"{style}_{room}_{got:02d}.jpg"
            CASES.mkdir(parents=True, exist_ok=True)
            im.convert("RGB").save(CASES / name, quality=92)
            row = {"case_id": f"C-{n:03d}", "file_path": f"assets/cases/{name}",
                   "source": "pexels", "source_url": c["page"],
                   "author": c["author"] or "Pexels contributor",
                   "license": ALLOWED_LICENSES["pexels"], "license_url": LICENSE_URL["pexels"],
                   "room": room, "style": style, "palette_hex": "", "plant_count": "",
                   "height_profile": "", "has_plant": "true", "background": "room",
                   "usable_for": "reference", "collected_at": TODAY, "note": f"query: {q}"}
            manifest.append(row)
            lic.append({"item_id": row["case_id"], "file_name": row["file_path"],
                        "source_platform": "Pexels", "source_url": c["page"], "author": row["author"],
                        "license": ALLOWED_LICENSES["pexels"], "license_url": LICENSE_URL["pexels"],
                        "collected_at": TODAY, "proof_path": "data/cases_manifest.csv", "note": q})
            time.sleep(0.2)
        print(f"   -> {got}", flush=True)
        write_csv("cases_manifest.csv", manifest)
        if lic:
            append_license(lic)
            lic.clear()
    print("done", len(manifest), "cases", flush=True)


if __name__ == "__main__":
    main()
