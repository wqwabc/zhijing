# -*- coding: utf-8 -*-
"""Pexels 无 Key 采集：经 r.jina.ai 读取搜索页，取图并登记。

用途：没有 Pexels API Key、但能访问网络时的兜底采集。
限制：作者信息在图片详情页，先落图与 photo_id，选定后用 `enrich_pexels.py` 补全。

    python collect_pexels_web.py --plants P01,P02 --limit 4
"""
from __future__ import annotations
import argparse, io, json, re, time
import requests
from PIL import Image

from common import ASSETS, INBOX, TODAY, LICENSE_URL, ALLOWED_LICENSES, log, plant_index

S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) VerdaBot/0.4"})
JINA = "https://r.jina.ai/"


def search_ids(query: str) -> list[tuple[str, str, str]]:
    """返回 [(photo_id, slug, page_url)]，只取真实图卡（导航缩略图不含 slug-数字 形式）。"""
    url = JINA + "https://www.pexels.com/search/" + requests.utils.quote(query) + "/"
    r = S.get(url, timeout=90)
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plants", default="all")
    ap.add_argument("--limit", type=int, default=4)
    a = ap.parse_args()
    idx = plant_index()
    ids = list(idx) if a.plants == "all" else [x.strip() for x in a.plants.split(",")]
    for pid in ids:
        p = idx[pid]
        q = f"{p['name_cn']} {p['name_latin']} houseplant" if False else f"{p['name_latin']} houseplant"
        print(f"[Pexels-web] {pid} q={q}")
        got = 0
        for photo_id, slug, page_url in search_ids(q):
            if got >= a.limit:
                break
            url = (f"https://images.pexels.com/photos/{photo_id}/pexels-photo-{photo_id}.jpeg"
                   f"?auto=compress&cs=tinysrgb&w=1800")
            try:
                r = S.get(url, timeout=60)
                im = Image.open(io.BytesIO(r.content)); im.load()
            except Exception as e:
                print("   !", photo_id, type(e).__name__)
                continue
            if max(im.size) < 1200:
                continue
            folder = INBOX / pid
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{pid}_pexels_{photo_id}.jpg"
            if not path.exists():
                im.convert("RGB").save(path, quality=94)
            rec = {"plant_id": pid, "source": "pexels", "file": str(path.relative_to(ASSETS.parent)),
                   "photo_id": photo_id, "alt": slug, "width": im.width, "height": im.height,
                   "page_url": page_url,
                   "download_url": url, "collected_at": TODAY,
                   "license": ALLOWED_LICENSES["pexels"], "license_url": LICENSE_URL["pexels"],
                   "needs_author": True}
            with open(INBOX / "_candidates.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(f"   + {path.name} {im.width}x{im.height} {slug[:46]}")
            log("candidate", plant_id=pid, source="pexels", file=rec["file"])
            got += 1
            time.sleep(0.3)
        print(f"   -> {got} 张")


if __name__ == "__main__":
    main()
