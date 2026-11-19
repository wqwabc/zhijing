# -*- coding: utf-8 -*-
"""素材采集器：iNaturalist / Unsplash / Pexels / Wikimedia Commons。

用法：
    python collect.py inat --plants P01,P02 --limit 1
    python collect.py unsplash --plants all --limit 2      # 需 UNSPLASH_ACCESS_KEY
    python collect.py pexels --plants all --limit 2        # 需 PEXELS_API_KEY
    python collect.py commons --plants all --limit 2

产物：
    assets/inbox/<plant_id>/...            原始候选图
    assets/inbox/_candidates.jsonl         候选元数据（可追溯）
    data/license_table.csv                 授权表（一行一张，追加）
    logs/collect_YYYYMMDD.jsonl            采集日志
"""
from __future__ import annotations
import argparse, hashlib, io, json, os, re, sys, time
import requests
from PIL import Image

from common import (DATA, INBOX, LOGS, TODAY, ALLOWED_LICENSES, LICENSE_URL,
                    append_license, log, plant_index, read_csv)

S = requests.Session()
S.headers.update({"User-Agent": "VerdaDataBot/0.3 (course project; data collection)"})
TIMEOUT = (10, 90)


# ---------------------------------------------------------------- helpers
def target_plants(arg: str) -> dict[str, dict]:
    idx = plant_index()
    if arg.lower() == "all":
        return idx
    ids = [x.strip() for x in arg.split(",") if x.strip()]
    missing = [x for x in ids if x not in idx]
    if missing:
        sys.exit(f"未知植物编号：{missing}")
    return {k: idx[k] for k in ids}


def save_image(content: bytes, plant_id: str, source: str, url: str, meta: dict,
               min_edge: int, dry: bool) -> dict | None:
    try:
        im = Image.open(io.BytesIO(content))
        im.load()
    except Exception as e:
        print(f"   ! 不是有效图片：{type(e).__name__}")
        return None
    w, h = im.size
    if max(w, h) < min_edge:
        print(f"   ! 尺寸不足 {w}x{h} < {min_edge}")
        return None
    if min(w, h) < 600:
        print(f"   ! 短边过小 {w}x{h}")
        return None
    if dry:
        print(f"   · [dry-run] {w}x{h} {url[:80]}")
        return None
    folder = INBOX / plant_id
    folder.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(content).hexdigest()[:8]
    name = f"{plant_id}_{source}_{digest}.jpg"
    path = folder / name
    if not path.exists():
        path.write_bytes(content)
    rec = {**meta, "plant_id": plant_id, "source": source, "file": str(path.relative_to(DATA.parent)),
           "width": w, "height": h, "sha1": digest, "download_url": url, "collected_at": TODAY}
    with open(INBOX / "_candidates.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"   + {name} {w}x{h} {len(content)//1024}KB")
    return rec


def fetch(url: str, headers: dict | None = None, retries: int = 2) -> bytes | None:
    for i in range(retries + 1):
        try:
            r = S.get(url, headers=headers, timeout=TIMEOUT)
            if r.status_code == 200 and r.content:
                return r.content
            print(f"   ! HTTP {r.status_code} {url[:90]}")
        except Exception as e:
            print(f"   ! {type(e).__name__} {url[:90]}")
        time.sleep(1.5 * (i + 1))
    return None


def license_row(plant_id: str, rec: dict, platform: str, page_url: str, author: str,
                lic_key: str, note: str = "") -> dict:
    return {
        "item_id": plant_id,
        "file_name": rec["file"],
        "source_platform": platform,
        "source_url": page_url,
        "author": author,
        "license": ALLOWED_LICENSES[lic_key],
        "license_url": LICENSE_URL[lic_key],
        "collected_at": TODAY,
        "proof_path": "assets/inbox/_candidates.jsonl",
        "note": note,
    }


# ---------------------------------------------------------------- iNaturalist
def collect_inat(plants: dict, limit: int, min_edge: int, dry: bool) -> None:
    taxa = {r["plant_id"]: r for r in read_csv("taxa_verified.csv")}
    for pid, p in plants.items():
        taxon_id = (taxa.get(pid) or {}).get("inat_taxon_id", "")
        print(f"[iNat] {pid} {p['name_cn']} taxon={taxon_id}")
        if not taxon_id:
            print("   ! 缺少 taxon_id，先运行 verify_taxa.py")
            continue
        r = S.get("https://api.inaturalist.org/v1/observations", params={
            "taxon_id": taxon_id, "photos": "true", "per_page": 30,
            "quality_grade": "research", "order_by": "votes",
            "photo_license": "cc0,cc-by,cc-by-sa,cc-by-nc,cc-by-nc-sa",
        }, timeout=TIMEOUT)
        if r.status_code != 200:
            print(f"   ! API {r.status_code}")
            continue
        got = 0
        for obs in r.json().get("results", []):
            if got >= limit:
                break
            for ph in obs.get("photos", [])[:2]:
                lic = (ph.get("license_code") or "").lower()
                if lic not in ALLOWED_LICENSES:
                    continue
                url = ph["url"].replace("/square.", "/original.")
                content = fetch(url)
                if content is None:
                    url = ph["url"].replace("/square.", "/large.")
                    content = fetch(url)
                if content is None:
                    continue
                author = (ph.get("attribution") or "").split(",")[0].replace("(c)", "").strip()
                meta = {
                    "platform": "iNaturalist",
                    "page_url": f"https://www.inaturalist.org/observations/{obs['id']}",
                    "author": author,
                    "license": ALLOWED_LICENSES[lic],
                    "license_url": LICENSE_URL[lic],
                    "observation_id": obs["id"],
                    "photo_id": ph["id"],
                    "quality_grade": obs.get("quality_grade", ""),
                    "seen_on": obs.get("observed_on", ""),
                    "place": (obs.get("place_guess") or "")[:60],
                }
                rec = save_image(content, pid, "inat", url, meta, min_edge, dry)
                if rec:
                    append_license([license_row(pid, rec, "iNaturalist", meta["page_url"],
                                                author, lic, f"obs {obs['id']}")])
                    log("download", plant_id=pid, source="inat", file=rec["file"])
                    got += 1
                    break
                time.sleep(0.3)
        print(f"   -> 新增 {got} 张")


# ---------------------------------------------------------------- Unsplash
def collect_unsplash(plants: dict, limit: int, min_edge: int, dry: bool) -> None:
    key = os.environ.get("UNSPLASH_ACCESS_KEY", "").strip()
    if not key:
        sys.exit("缺少 UNSPLASH_ACCESS_KEY（https://unsplash.com/developers 免费申请）")
    hdr = {"Authorization": f"Client-ID {key}"}
    for pid, p in plants.items():
        q = p["search_query"] or p["name_latin"]
        print(f"[Unsplash] {pid} {p['name_cn']} q={q}")
        r = S.get("https://api.unsplash.com/search/photos", headers=hdr,
                  params={"query": q, "per_page": 30, "orientation": "portrait"}, timeout=TIMEOUT)
        if r.status_code != 200:
            print(f"   ! API {r.status_code} {r.text[:100]}")
            continue
        got = 0
        for item in r.json().get("results", []):
            if got >= limit:
                break
            url = (item["urls"].get("full") or item["urls"]["regular"]).split("?")[0] + "?w=1800&q=85"
            content = fetch(url)
            if content is None:
                continue
            author = item["user"]["name"]
            meta = {"platform": "Unsplash", "page_url": item["links"]["html"], "author": author,
                    "license": ALLOWED_LICENSES["unsplash"], "license_url": LICENSE_URL["unsplash"],
                    "photo_id": item["id"], "query": q}
            rec = save_image(content, pid, "unsplash", url, meta, min_edge, dry)
            if rec:
                append_license([license_row(pid, rec, "Unsplash", meta["page_url"], author, "unsplash")])
                log("download", plant_id=pid, source="unsplash", file=rec["file"])
                got += 1
        print(f"   -> 新增 {got} 张")


# ---------------------------------------------------------------- Pexels
def collect_pexels(plants: dict, limit: int, min_edge: int, dry: bool) -> None:
    key = os.environ.get("PEXELS_API_KEY", "").strip()
    if not key:
        sys.exit("缺少 PEXELS_API_KEY（https://www.pexels.com/api/ 免费申请）")
    hdr = {"Authorization": key}
    for pid, p in plants.items():
        q = p["search_query"] or p["name_latin"]
        print(f"[Pexels] {pid} {p['name_cn']} q={q}")
        r = S.get("https://api.pexels.com/v1/search", headers=hdr,
                  params={"query": q, "per_page": 30, "orientation": "portrait"}, timeout=TIMEOUT)
        if r.status_code != 200:
            print(f"   ! API {r.status_code} {r.text[:100]}")
            continue
        got = 0
        for item in r.json().get("photos", []):
            if got >= limit:
                break
            url = item["src"].get("original") or item["src"].get("large2x")
            content = fetch(url)
            if content is None:
                continue
            author = item.get("photographer", "")
            meta = {"platform": "Pexels", "page_url": item["url"], "author": author,
                    "license": ALLOWED_LICENSES["pexels"], "license_url": LICENSE_URL["pexels"],
                    "photo_id": item["id"], "query": q}
            rec = save_image(content, pid, "pexels", url, meta, min_edge, dry)
            if rec:
                append_license([license_row(pid, rec, "Pexels", meta["page_url"], author, "pexels")])
                log("download", plant_id=pid, source="pexels", file=rec["file"])
                got += 1
        print(f"   -> 新增 {got} 张")


# ---------------------------------------------------------------- Commons
COMMONS_OK = {"cc0": "cc0", "public domain": "pd", "pd": "pd",
              "cc by 4.0": "cc-by", "cc by-sa 4.0": "cc-by-sa",
              "cc by 3.0": "cc-by", "cc by-sa 3.0": "cc-by-sa"}


def collect_commons(plants: dict, limit: int, min_edge: int, dry: bool) -> None:
    for pid, p in plants.items():
        q = f'{p["name_latin"]} plant'
        print(f"[Commons] {pid} {p['name_cn']} q={q}")
        r = S.get("https://commons.wikimedia.org/w/api.php", params={
            "action": "query", "format": "json", "generator": "search", "gsrsearch": q,
            "gsrnamespace": 6, "gsrlimit": 20, "prop": "imageinfo",
            "iiprop": "url|size|extmetadata", "iiurlwidth": 1600,
        }, timeout=TIMEOUT)
        if r.status_code != 200:
            print(f"   ! API {r.status_code}")
            continue
        got = 0
        pages = (r.json().get("query") or {}).get("pages", {})
        for page in pages.values():
            if got >= limit:
                break
            ii = (page.get("imageinfo") or [{}])[0]
            em = ii.get("extmetadata") or {}
            short = (em.get("LicenseShortName", {}).get("value") or "").strip().lower()
            lic = COMMONS_OK.get(short)
            if not lic:
                continue
            url = ii.get("thumburl") or ii.get("url")
            if not url:
                continue
            content = fetch(url)
            if content is None:
                continue
            author = re.sub(r"<[^>]+>", "", em.get("Artist", {}).get("value", "")).strip()[:60]
            meta = {"platform": "Wikimedia Commons", "page_url": ii.get("descriptionurl", ""),
                    "author": author, "license": ALLOWED_LICENSES[lic], "license_url": LICENSE_URL[lic],
                    "file_title": page.get("title", ""), "query": q}
            rec = save_image(content, pid, "commons", url, meta, min_edge, dry)
            if rec:
                append_license([license_row(pid, rec, "Wikimedia Commons", meta["page_url"],
                                            author, lic, page.get("title", ""))])
                log("download", plant_id=pid, source="commons", file=rec["file"])
                got += 1
        print(f"   -> 新增 {got} 张")


def main() -> None:
    ap = argparse.ArgumentParser(description="植境 Verda 素材采集器")
    ap.add_argument("source", choices=["inat", "unsplash", "pexels", "commons"])
    ap.add_argument("--plants", default="all", help="P01,P02 或 all")
    ap.add_argument("--limit", type=int, default=1, help="每种最多入库张数")
    ap.add_argument("--min-edge", type=int, default=1200, help="长边下限 px")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    plants = target_plants(a.plants)
    print(f"目标 {len(plants)} 种，每种上限 {a.limit} 张，长边≥{a.min_edge}px"
          f"{'（dry-run）' if a.dry_run else ''}")
    {"inat": collect_inat, "unsplash": collect_unsplash,
     "pexels": collect_pexels, "commons": collect_commons}[a.source](
        plants, a.limit, a.min_edge, a.dry_run)


if __name__ == "__main__":
    main()
