# -*- coding: utf-8 -*-
"""火山方舟 Seedream 5.0 Flash 图像编辑客户端。

输入一张底图 + 一句中文指令，返回编辑后的 PNG。
Key 优先取请求头覆盖值，其次环境变量 ARK_API_KEY；
模型可用 ARK_IMAGE_MODEL 覆盖（默认 doubao-seedream-5-0-flash-260915）。
"""

import base64
import json
import os
import urllib.error
import urllib.request

BASE = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_MODEL = "doubao-seedream-5-0-flash-260915"


def _key(overrides: dict = None) -> str:
    if overrides and overrides.get("api_key"):
        return str(overrides["api_key"]).strip()
    return os.environ.get("ARK_API_KEY", "").strip()


def _model(overrides: dict = None) -> str:
    if overrides and overrides.get("model"):
        return str(overrides["model"]).strip()
    return os.environ.get("ARK_IMAGE_MODEL", DEFAULT_MODEL).strip()


def available(overrides: dict = None) -> bool:
    return bool(_key(overrides))


def _data_url(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def edit_image(base_png: bytes, prompt: str, overrides: dict = None) -> bytes | None:
    key = _key(overrides)
    if not key:
        return None

    body = {
        "model": _model(overrides),
        "prompt": prompt,
        "image": [_data_url(base_png)],
        "size": "2K",
        "response_format": "url",
        "watermark": False,
    }
    req = urllib.request.Request(
        BASE + "/images/generations",
        data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + key,
                 "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, ValueError, OSError):
        return None

    try:
        item = data["data"][0]
        if item.get("b64_json"):
            return base64.b64decode(item["b64_json"])
        url = item.get("url")
        if not url:
            return None
        with urllib.request.urlopen(url, timeout=60) as img:
            return img.read()
    except (KeyError, IndexError, ValueError, OSError):
        return None
