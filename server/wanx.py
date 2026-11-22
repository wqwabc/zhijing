# -*- coding: utf-8 -*-
"""通义万相图像编辑（DashScope）客户端。

只做一件事：给一张底图 + 一张 mask + 一句中文指令，返回编辑后的 PNG。
Key 优先取请求头传入的覆盖值，其次环境变量 DASHSCOPE_API_KEY；
都不存在时返回 None，由上层退回本地合成。
"""

import base64
import json
import os
import time
import urllib.error
import urllib.request

BASE = "https://dashscope.aliyuncs.com/api/v1"
MODEL = "wanx2.1-imageedit"
TIMEOUT = 90


def _key(overrides: dict = None) -> str:
    if overrides and overrides.get("api_key"):
        return str(overrides["api_key"]).strip()
    return os.environ.get("DASHSCOPE_API_KEY", "").strip()


def available(overrides: dict = None) -> bool:
    return bool(_key(overrides))


def _data_url(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def _request(url: str, key: str, payload: dict = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json",
                 **({"X-DashScope-Async": "enable"} if payload is not None else {})},
        method="POST" if payload is not None else "GET")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def edit_image(base_png: bytes, mask_png: bytes, prompt: str,
               overrides: dict = None) -> bytes | None:
    key = _key(overrides)
    if not key:
        return None

    body = {
        "model": MODEL,
        "input": {
            "function": "description_edit_with_mask",
            "prompt": prompt,
            "base_image_url": _data_url(base_png),
            "mask_image_url": _data_url(mask_png),
        },
        "parameters": {"n": 1},
    }
    try:
        resp = _request(BASE + "/services/aigc/image2image/image-synthesis", key, body)
        task_id = resp["output"]["task_id"]
    except (urllib.error.URLError, KeyError, ValueError, OSError):
        return None

    deadline = time.time() + TIMEOUT
    while time.time() < deadline:
        time.sleep(2)
        try:
            r = _request(BASE + "/tasks/" + task_id, key)
            status = r.get("output", {}).get("task_status")
        except (urllib.error.URLError, ValueError, OSError):
            continue
        if status == "SUCCEEDED":
            try:
                url = r["output"]["results"][0]["url"]
                with urllib.request.urlopen(url, timeout=60) as img:
                    return img.read()
            except (urllib.error.URLError, KeyError, IndexError, OSError):
                return None
        if status in ("FAILED", "CANCELED"):
            return None
    return None
