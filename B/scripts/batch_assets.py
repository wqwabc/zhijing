# -*- coding: utf-8 -*-
"""批量采集 + 去底 + 自动择优（W2：把 36 种素材补齐）。

对每种植物：
  1) 用 Pexels 搜索页（经 r.jina.ai）取候选，下载到 assets/inbox/Pxx/
  2) 逐张去底，算质量分（主体完整度、边缘干净度、占比、长宽比）
  3) 取分最高且过硬约束的一张，落 assets/cutout/Pxx/Pxx_front_pexels.png
  4) 写授权行（作者按需回填）、更新 assets_manifest.csv

    python batch_assets.py --plants P06,P07 --limit 4
    python batch_assets.py --all --limit 5
"""
from __future__ import annotations
import argparse, io, json, re, sys, time
from pathlib import Path

import numpy as np
import requests
from PIL import Image

from common import (INBOX, CUTOUT, ASSETS, TODAY, ALLOWED_LICENSES, LICENSE_URL,
                    read_csv, write_csv, plant_index, log)
import bg_onnx
import cutout
import qc

S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) VerdaBot/0.5"})
JINA = "https://r.jina.ai/"


def search_ids(query: str) -> list[tuple[str, str, str]]:
    url = JINA + "https://www.pexels.com/search/" + requests.utils.quote(query) + "/"
    try:
        r = S.get(url, timeout=90)
    except Exception as e:
        print("   ! jina", type(e).__name__)
        return []
    if r.status_code != 200:
        print("   ! jina", r.status_code)
        return []
    hits = re.findall(r"https://www\.pexels\.com/photo/([a-z0-9\-]+?)-(\d+)/", r.text)
    out, seen = [], set()
    for slug, pid in hits:
        if pid in seen:
            continue
        seen.add(pid)
        out.append((pid, slug.replace("-", " "), f"https://www.pexels.com/photo/{slug}-{pid}/"))
    return out


def download(photo_id: str, plant_id: str, page_url: str, slug: str) -> Path | None:
    url = (f"https://images.pexels.com/photos/{photo_id}/pexels-photo-{photo_id}.jpeg"
           f"?auto=compress&cs=tinysrgb&w=1800")
    for _ in range(2):
        try:
            r = S.get(url, timeout=60)
            im = Image.open(io.BytesIO(r.content))
            im.load()
            if max(im.size) < 1200:
                return None
            folder = INBOX / plant_id
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{plant_id}_pexels_{photo_id}.jpg"
            if not path.exists():
                im.convert("RGB").save(path, quality=94)
            rec = {"plant_id": plant_id, "source": "pexels", "file": path.relative_to(ASSETS.parent).as_posix(),
                   "photo_id": photo_id, "alt": slug, "width": im.width, "height": im.height,
                   "page_url": page_url, "download_url": url, "collected_at": TODAY,
                   "license": ALLOWED_LICENSES["pexels"], "license_url": LICENSE_URL["pexels"],
                   "needs_author": True}
            with open(INBOX / "_candidates.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            return path
        except Exception:
            time.sleep(2)
    return None


def score(path: Path) -> tuple[float, dict] | None:
    """去底后打分；硬约束不过直接淘汰。"""
    im = Image.open(path).convert("RGBA")
    cut = cutout.harden_alpha(bg_onnx.remove(im))
    cut = cutout.trim(cut)
    cut = cutout.fit(cut)
    a = np.asarray(cut.getchannel("A"))
    opacity = a > 16
    ratio = float(opacity.mean())
    if max(cut.size) < 1200 or ratio < 0.05 or ratio > 0.65:
        return None
    border = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    border_alpha = float((border > 16).mean())
    if border_alpha > 0.12:
        return None
    small = np.asarray(cut.resize((256, 256), Image.BILINEAR))
    comp = qc.largest_component_ratio(small[:, :, 3])
    if comp < 0.80:
        return None
    w, h = cut.size
    aspect = h / w
    # 整株越"竖"越像盆栽正面照；占比适中最好（太小=远景，太大=局部）
    fill = 1.0 - abs(ratio - 0.28) / 0.28
    s = 0.45 * comp + 0.2 * (1 - border_alpha / 0.12) + 0.2 * max(0, min(1, (aspect - 0.9) / 0.8)) + 0.15 * max(0, fill)
    return s, {"ratio": ratio, "border": border_alpha, "comp": comp, "aspect": aspect,
               "size": cut.size, "engine": "onnx"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plants", default="")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--limit", type=int, default=4)
    a = ap.parse_args()
    idx = plant_index()
    rows = read_csv("assets_manifest.csv")
    todo = [r["plant_id"] for r in rows if r["status"] != "ready"]
    if a.plants:
        todo = [x.strip() for x in a.plants.split(",") if x.strip()]
    print("待采", len(todo), "种")
    winners = []
    for pid in todo:
        p = idx[pid]
        print(f"[{pid}] {p['name_cn']} {p['name_latin']}")
        got, best = 0, None
        for query in (f"{p['name_latin']} houseplant", f"{p['name_latin']} plant pot"):
            if got >= a.limit or best:
                break
            for photo_id, slug, page in search_ids(query):
                if got >= a.limit:
                    break
                path = download(photo_id, pid, page, slug)
                if not path:
                    continue
                got += 1
                res = score(path)
                if not res:
                    print(f"   x {photo_id} {slug[:34]}")
                    continue
                s, m = res
                print(f"   . {photo_id} score={s:.2f} comp={m['comp']:.2f} ratio={m['ratio']:.2f}")
                if best is None or s > best[0]:
                    best = (s, photo_id, path, m)
        if not best:
            print("   -> 无合格候选，保持 pending")
            continue
        s, photo_id, path, m = best
        out = cutout.process(path, "onnx", harden=True)
        if not out:
            continue
        out["_score"] = s
        winners.append(out)
        print(f"   -> 入选 {photo_id} score={s:.2f}")
    if winners:
        cutout.update_manifest(winners)
        print("ready", len(winners))


if __name__ == "__main__":
    main()
