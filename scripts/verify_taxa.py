# -*- coding: utf-8 -*-
"""学名与来源校验：用 iNaturalist 分类 API 核对 36 种植物的学名，回填 Wikipedia 链接。

一次性脚本，结果写 data/taxa_verified.csv，并更新 plants_master.csv 的 source_url / source_status。
    python verify_taxa.py
"""
from __future__ import annotations
import time

import requests

from common import DATA, read_csv, write_csv

S = requests.Session()
S.headers.update({"User-Agent": "VerdaDataBot/0.3 (course project)"})


def main() -> None:
    rows = read_csv("plants_master.csv")
    out, ok = [], 0
    for r in rows:
        latin = r["name_latin"]
        try:
            resp = S.get("https://api.inaturalist.org/v1/taxa",
                         params={"q": latin, "per_page": 8}, timeout=25)
            results = resp.json().get("results", [])
        except Exception as e:
            print(f"ERR {latin} {type(e).__name__}")
            out.append([r["plant_id"], latin, "", "", "", "", "", "", "error"])
            continue
        hit = next((x for x in results if x.get("name", "").lower() == latin.lower()), None)
        if hit is None:
            hit = results[0] if results else {}
        photo = hit.get("default_photo") or {}
        out.append([
            r["plant_id"], latin, hit.get("id", ""), hit.get("name", ""), hit.get("rank", ""),
            hit.get("observations_count", ""), hit.get("wikipedia_url", ""),
            (photo.get("attribution") or "").replace("\n", " "),
            "ok" if hit else "miss",
        ])
        if hit.get("wikipedia_url"):
            r["source_url"] = hit["wikipedia_url"]
            r["source_status"] = "verified"
            ok += 1
        print(f'{r["plant_id"]} {latin:38s} id={hit.get("id")} '
              f'obs={hit.get("observations_count")} wiki={"Y" if hit.get("wikipedia_url") else "N"}')
        time.sleep(0.25)

    with open(DATA / "taxa_verified.csv", "w", encoding="utf-8-sig", newline="") as f:
        import csv as _csv
        w = _csv.writer(f)
        w.writerow(["plant_id", "name_latin", "inat_taxon_id", "matched_name", "rank",
                    "observations_count", "wikipedia_url", "default_photo_attribution", "status"])
        w.writerows(out)
    write_csv("plants_master.csv", rows)
    print(f"校验完成：{ok}/{len(out)} 拿到来源链接")


if __name__ == "__main__":
    main()
