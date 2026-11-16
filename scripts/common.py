# -*- coding: utf-8 -*-
"""共享工具：路径、CSV 读写、授权常量、日志。"""
from __future__ import annotations
import csv, json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ASSETS = ROOT / "assets"
INBOX = ASSETS / "inbox"
CUTOUT = ASSETS / "cutout"
CASES = ASSETS / "cases"
LOGS = ROOT / "logs"
for d in (DATA, ASSETS, INBOX, CUTOUT, CASES, LOGS):
    d.mkdir(parents=True, exist_ok=True)

TODAY = time.strftime("%Y-%m-%d")

# 允许进入素材库的许可（白名单）
ALLOWED_LICENSES = {
    "cc0": "CC0 1.0",
    "cc-by": "CC BY 4.0",
    "cc-by-sa": "CC BY-SA 4.0",
    "cc-by-nc": "CC BY-NC 4.0",
    "cc-by-nc-sa": "CC BY-NC-SA 4.0",
    "pd": "Public Domain",
    "unsplash": "Unsplash License",
    "pexels": "Pexels License",
}
LICENSE_URL = {
    "cc0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "cc-by": "https://creativecommons.org/licenses/by/4.0/",
    "cc-by-sa": "https://creativecommons.org/licenses/by-sa/4.0/",
    "cc-by-nc": "https://creativecommons.org/licenses/by-nc/4.0/",
    "cc-by-nc-sa": "https://creativecommons.org/licenses/by-nc-sa/4.0/",
    "pd": "https://creativecommons.org/publicdomain/mark/1.0/",
    "unsplash": "https://unsplash.com/license",
    "pexels": "https://www.pexels.com/license/",
}


def read_csv(name: str) -> list[dict]:
    path = DATA / name
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(name: str, rows: list[dict], header: list[str] | None = None) -> Path:
    path = DATA / name
    if header is None:
        header = list(rows[0].keys()) if rows else []
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return path


def append_license(rows: list[dict]) -> int:
    """向 license_table.csv 追加授权行（自动编号、去重）。"""
    path = DATA / "license_table.csv"
    exists = path.exists()
    header = ["no", "item_id", "file_name", "source_platform", "source_url", "author",
              "license", "license_url", "collected_at", "proof_path", "note"]
    existing = []
    if exists:
        with open(path, encoding="utf-8-sig", newline="") as f:
            existing = list(csv.DictReader(f))
    seen = {(r["file_name"], r["source_url"]) for r in existing}
    n = len(existing)
    added = 0
    with open(path, "a", encoding="utf-8-sig" if not exists else "utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        if not exists:
            w.writeheader()
        for r in rows:
            key = (r.get("file_name", ""), r.get("source_url", ""))
            if key in seen:
                continue
            n += 1
            r = dict(r)
            r["no"] = n
            r.setdefault("collected_at", TODAY)
            w.writerow(r)
            seen.add(key)
            added += 1
    return added


def log(event: str, **kw) -> None:
    rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "event": event, **kw}
    with open(LOGS / f"collect_{time.strftime('%Y%m%d')}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def plant_index() -> dict[str, dict]:
    return {r["plant_id"]: r for r in read_csv("plants_master.csv")}


def human_size(n: int) -> str:
    return f"{n/1024/1024:.1f}MB" if n > 1024 * 1024 else f"{n/1024:.0f}KB"
