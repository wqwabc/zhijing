# -*- coding: utf-8 -*-
"""iNat 采集 + 打分择优（Pexels 搜索页不可用时的主路径）。

iNaturalist 的 captive=true 观测多为家庭盆栽，配 CC 许可、可回源。
    python batch_inat.py --plants P06,P07 --limit 6
"""
from __future__ import annotations
import argparse, io, json, time
from pathlib import Path

import requests
from PIL import Image

from common import (INBOX, ASSETS, TODAY, ALLOWED_LICENSES, LICENSE_URL,
                    read_csv, write_csv, plant_index)
import cutout
from batch_assets import score

S = requests.Session()
S.headers.update({"User-Agent": "VerdaBot/0.5 (course project)"})


def candidates(taxon_id: str, limit: int):
    r = S.get("https://api.inaturalist.org/v1/observations", params={
        "taxon_id": taxon_id, "photos": "true", "per_page": 40,
        "captive": "true", "order_by": "votes",
        "photo_license": "cc0,cc-by,cc-by-sa",
    }, timeout=30)
    if r.status_code != 200:
        print("   ! api", r.status_code)
        return []
    out = []
    for obs in r.json().get("results", []):
        for ph in obs.get("photos", [])[:2]:
            lic = (ph.get("license_code") or "").lower()
            if lic not in ALLOWED_LICENSES:
                continue
            out.append({
                "photo_id": ph["id"], "url": ph["url"], "license": lic,
                "obs": obs["id"], "attribution": ph.get("attribution", ""),
                "page": f"https://www.inaturalist.org/observations/{obs['id']}",
                "observed_on": obs.get("observed_on", ""),
            })
            if len(out) >= limit * 3:
                return out
    return out


def fetch(c) -> Path | None:
    for size in ("original", "large"):
        url = c["url"].replace("/square.", f"/{size}.")
        try:
            r = S.get(url, timeout=60)
            im = Image.open(io.BytesIO(r.content))
            im.load()
        except Exception:
            continue
        if max(im.size) < 1200:
            continue
        pid = c["plant_id"]
        folder = INBOX / pid
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{pid}_inat_{c['photo_id']}.jpg"
        if not path.exists():
            im.convert("RGB").save(path, quality=94)
        return path
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plants", default="")
    ap.add_argument("--limit", type=int, default=6)
    a = ap.parse_args()
    idx = plant_index()
    taxa = {r["plant_id"]: r for r in read_csv("taxa_verified.csv")}
    rows = read_csv("assets_manifest.csv")
    todo = [r["plant_id"] for r in rows if r["status"] != "ready"]
    if a.plants:
        todo = [x.strip() for x in a.plants.split(",") if x.strip()]
    print("待采", len(todo))
    winners = []
    for pid in todo:
        p = idx[pid]
        taxon_id = (taxa.get(pid) or {}).get("inat_taxon_id")
        print(f"[{pid}] {p['name_cn']} taxon={taxon_id}")
        if not taxon_id:
            continue
        best, tried = None, 0
        for c in candidates(taxon_id, a.limit):
            if tried >= a.limit:
                break
            c["plant_id"] = pid
            path = fetch(c)
            if not path:
                continue
            tried += 1
            res = score(path)
            if not res:
                print(f"   x {c['photo_id']}")
                continue
            s, m = res
            print(f"   . {c['photo_id']} {s:.2f} comp={m['comp']:.2f} ratio={m['ratio']:.2f}")
            if best is None or s > best[0]:
                c["path"] = path
                best = (s, c, m)
        if not best:
            print("   -> 无合格候选")
            continue
        s, c, m = best
        out = cutout.process(c["path"], "onnx", harden=True)
        if not out:
            continue
        author = (c["attribution"] or "").split(",")[0].replace("(c)", "").strip()
        with open(INBOX / "_candidates.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"plant_id": pid, "source": "inat", "file": out["file"],
                                "photo_id": c["photo_id"], "page_url": c["page"],
                                "author": author, "license": ALLOWED_LICENSES[c["license"]],
                                "collected_at": TODAY}, ensure_ascii=False) + "\n")
        out["_score"] = s
        winners.append(out)
        print(f"   -> 入选 {c['photo_id']} {s:.2f} {author[:20]}")
    if winners:
        cutout.update_manifest(winners)
        print("ready", len(winners))


if __name__ == "__main__":
    main()
