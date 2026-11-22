# -*- coding: utf-8 -*-
"""Wikimedia Commons 采集 + 打分择优（替代 Pexels 搜索页不可用时的路径）。

优先走物种分类 Category:{学名}，没有就退回搜索。
    python batch_commons.py --plants P06,P07 --limit 8
"""
from __future__ import annotations
import argparse, io, json, re, time
from pathlib import Path

import requests
from PIL import Image

from common import (INBOX, ASSETS, TODAY, ALLOWED_LICENSES, LICENSE_URL, read_csv, plant_index)
import cutout
from batch_assets import score

S = requests.Session()
S.headers.update({"User-Agent": "VerdaBot/0.5 (course project; data collection)"})
API = "https://commons.wikimedia.org/w/api.php"
OK = {"cc0": "cc0", "public domain": "pd", "pd": "pd", "cc by 4.0": "cc-by", "cc by-sa 4.0": "cc-by-sa",
      "cc by 3.0": "cc-by", "cc by-sa 3.0": "cc-by-sa", "cc by 2.0": "cc-by", "cc by-sa 2.0": "cc-by-sa"}


def list_files(latin: str, limit: int) -> list:
    for params in (
        {"generator": "categorymembers", "gcmtitle": f"Category:{latin}", "gcmtype": "file", "gcmlimit": 40},
        {"generator": "search", "gsrsearch": f"{latin} potted plant", "gsrnamespace": 6, "gsrlimit": 40},
    ):
        try:
            r = S.get(API, params={"action": "query", "format": "json", "prop": "imageinfo",
                                   "iiprop": "url|size|extmetadata", "iiurlwidth": 1600, **params}, timeout=30)
            pages = (r.json().get("query") or {}).get("pages", {})
        except Exception as e:
            print("   ! api", type(e).__name__)
            continue
        out = []
        for p in pages.values():
            ii = (p.get("imageinfo") or [{}])[0]
            em = ii.get("extmetadata") or {}
            lic = OK.get((em.get("LicenseShortName", {}).get("value") or "").strip().lower())
            if not lic or not ii.get("thumburl"):
                continue
            if ii.get("width", 0) < 1200:
                continue
            out.append({"title": p.get("title", ""), "url": ii["thumburl"],
                        "page": ii.get("descriptionurl", ""), "license": lic,
                        "artist": re.sub(r"<[^>]+>", "", em.get("Artist", {}).get("value", "")).strip()[:60]})
            if len(out) >= limit * 2:
                return out
        if out:
            return out
    return []


def download(item, pid: str) -> Path | None:
    try:
        r = S.get(item["url"], timeout=45)
        im = Image.open(io.BytesIO(r.content))
        im.load()
    except Exception:
        return None
    if max(im.size) < 1200:
        return None
    folder = INBOX / pid
    folder.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^0-9a-zA-Z]+", "", item["title"].split(":")[-1])[:24]
    path = folder / f"{pid}_commons_{name or 'file'}.jpg"
    if not path.exists():
        im.convert("RGB").save(path, quality=94)
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plants", default="")
    ap.add_argument("--limit", type=int, default=8)
    a = ap.parse_args()
    idx = plant_index()
    rows = read_csv("assets_manifest.csv")
    todo = [r["plant_id"] for r in rows if r["status"] != "ready"]
    if a.plants:
        todo = [x.strip() for x in a.plants.split(",") if x.strip()]
    print("待采", len(todo), flush=True)
    winners = []
    for pid in todo:
        p = idx[pid]
        print(f"[{pid}] {p['name_cn']} {p['name_latin']}", flush=True)
        best, tried = None, 0
        for item in list_files(p["name_latin"], a.limit):
            if tried >= a.limit:
                break
            path = download(item, pid)
            if not path:
                continue
            tried += 1
            res = score(path)
            if not res:
                continue
            s, m = res
            print(f"   . {path.name[:40]} {s:.2f} comp={m['comp']:.2f} ratio={m['ratio']:.2f}", flush=True)
            if best is None or s > best[0]:
                best = (s, item, path)
        if not best:
            print("   -> 无合格候选", flush=True)
            continue
        s, item, path = best
        out = cutout.process(path, "onnx", harden=True)
        if not out:
            continue
        with open(INBOX / "_candidates.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"plant_id": pid, "source": "commons", "file": out["file"],
                                "page_url": item["page"], "author": item["artist"],
                                "license": ALLOWED_LICENSES[item["license"]],
                                "collected_at": TODAY}, ensure_ascii=False) + "\n")
        winners.append(out)
        print(f"   -> 入选 {path.name[:36]} {s:.2f}", flush=True)
    if winners:
        cutout.update_manifest(winners)
        print("ready", len(winners), flush=True)


if __name__ == "__main__":
    main()
