# -*- coding: utf-8 -*-
"""生成结果的历史保存（默认 data/generated/，不进仓库）。

- 文件名 gen_YYYYmmdd_HHMMSS_xxxx.png
- 同名 .json 存元信息（时间、来源、光照、时间、株数）
- 只保留最近 MAX_KEEP 张，避免无限增长
"""

import json
import os
import re
import secrets
import time

MAX_KEEP = 60
NAME_RE = re.compile(r"^gen_\d{8}_\d{6}_[0-9a-f]{4}\.png$")


def _dir(base_dir: str) -> str:
    os.makedirs(base_dir, exist_ok=True)
    return base_dir


def save(base_dir: str, png: bytes, meta: dict) -> dict:
    d = _dir(base_dir)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    name = "gen_%s_%s.png" % (stamp, secrets.token_hex(2))
    with open(os.path.join(d, name), "wb") as f:
        f.write(png)
    item = dict(meta)
    item["name"] = name
    item["created_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(os.path.join(d, name[:-4] + ".json"), "w", encoding="utf-8") as f:
        json.dump(item, f, ensure_ascii=False)
    _prune(d)
    return item


def _prune(d: str, keep: int = MAX_KEEP) -> None:
    names = sorted(n for n in os.listdir(d) if n.endswith(".png"))
    for old in names[:max(0, len(names) - keep)]:
        for path in (os.path.join(d, old), os.path.join(d, old[:-4] + ".json")):
            try:
                os.remove(path)
            except OSError:
                pass


def path(base_dir: str, name: str):
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        return None
    p = os.path.join(base_dir, name)
    return p if os.path.isfile(p) else None


def list_items(base_dir: str, limit: int = MAX_KEEP) -> list:
    d = _dir(base_dir)
    out = []
    for name in sorted((n for n in os.listdir(d) if n.endswith(".png")), reverse=True):
        meta_path = os.path.join(d, name[:-4] + ".json")
        item = {"name": name, "created_at": ""}
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                item.update(json.load(f))
        except (OSError, ValueError):
            pass
        out.append(item)
        if len(out) >= limit:
            break
    return out
