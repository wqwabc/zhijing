# -*- coding: utf-8 -*-
"""DeepSeek 接入层（OpenAI 兼容 /chat/completions）。

设计原则：
1. 只把**房间特征**（主色、亮度、色温、估计风格/光照）和植物目录发给模型，
   照片本身不出本机；
2. 模型只负责“选哪几株、多高、放哪”，不负责打分；
3. 没 Key、超时、返回不合法 JSON 时一律返回 None，由上层走规则兜底（AC-10）。
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

DEFAULTS = {
    "base": "https://api.deepseek.com",
    "model": "deepseek-chat",
    "timeout": 20.0,
}


def _config() -> dict:
    return {
        "api_key": os.environ.get("DEEPSEEK_API_KEY", "").strip(),
        "base": (os.environ.get("DEEPSEEK_BASE") or DEFAULTS["base"]).rstrip("/"),
        "model": os.environ.get("DEEPSEEK_MODEL") or DEFAULTS["model"],
        "timeout": float(os.environ.get("DEEPSEEK_TIMEOUT") or DEFAULTS["timeout"]),
    }


def available() -> bool:
    return bool(_config()["api_key"])


def _post(payload: dict) -> dict | None:
    cfg = _config()
    if not cfg["api_key"]:
        return None
    req = urllib.request.Request(
        cfg["base"] + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + cfg["api_key"],
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=cfg["timeout"]) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None


def complete(messages: list, temperature: float = 0.3,
             max_tokens: int = 900) -> str | None:
    """返回模型文本；失败返回 None。"""
    cfg = _config()
    if not cfg["api_key"]:
        return None
    data = _post({
        "model": cfg["model"],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    })
    if not data:
        return None
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError):
        return None


def extract_json(text: str) -> dict | None:
    """从模型输出里抠出第一个 JSON 对象（容忍 ```json 围栏）。"""
    if not text:
        return None
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _catalog_lines(catalog: list) -> str:
    rows = []
    for p in catalog:
        rows.append("%s | %s | %d-%dcm | %s | %s | %s | %s" % (
            p["plant_id"], p["name_cn"], p["height_min_cm"], p["height_max_cm"],
            p["light_level"], "是" if p["pet_safe"] else "否",
            ";".join(p["style_tags"]), p["price_cny"]))
    return "\n".join(rows)


def plan_plants(features: dict, scene: dict, catalog: list,
                count: int = 3) -> dict | None:
    """让模型从目录里选 count 株，返回 {plants:[...], summary} 或 None。"""
    if not available() or not catalog:
        return None

    palette = ", ".join("%s(%.0f%%)" % (c["hex"], c["share"] * 100)
                        for c in features.get("palette", [])[:4])
    prompt = (
        "房间特征（从照片统计，非照片本身）：\n"
        "- 主色：%s\n- 亮度：%.2f\n- 暖度：%.2f\n- 绿色占比：%.2f\n"
        "- 估计风格：%s\n- 估计光照：%.1f\n\n"
        "用户约束：\n- 场景：%s\n- 风格：%s\n- 光照：%d\n- 每周养护：%d 分钟\n"
        "- 有宠物：%s\n- 预算：%.0f 元\n\n"
        "候选植物（id | 名称 | 株高 | 光照 | 宠物安全 | 风格 | 价格）：\n%s\n\n"
        "规则：\n"
        "1. 选 %d 株（2~5 株均可），plant_id 必须来自候选表；\n"
        "2. 有宠物时只能选「宠物安全=是」；\n"
        "3. 植物光照等级数字不能比用户光照高 2 档以上；\n"
        "4. height_cm 必须落在该植物株高区间内；\n"
        "5. x_frac 是 0~1 的横向位置，从左到右分布，不要挤在一起；\n"
        "6. 只输出 JSON，不要解释：\n"
        '{"plants":[{"plant_id":"P01","height_cm":150,"x_frac":0.2,'
        '"layer":0,"why":"一句话"}],"summary":"一句话总结"}\n'
        % (palette, features.get("brightness", 0), features.get("warmth", 0),
           features.get("green_share", 0), features.get("style_guess", ""),
           features.get("light_guess", 2), scene.get("room", ""),
           scene.get("style", ""), int(scene.get("light", 2)),
           int(scene.get("weekly_minutes", 30)),
           "是" if scene.get("has_pet") else "否",
           float(scene.get("budget", 500)), _catalog_lines(catalog), count)
    )

    system = ("你是植境 Verda 的绿植搭配师。只根据给定的房间特征和植物目录选株，"
              "严格遵守宠物安全与光照约束，只输出合法 JSON，不编造不存在的 plant_id。")
    t0 = time.time()
    text = complete([{"role": "system", "content": system},
                     {"role": "user", "content": prompt}],
                    temperature=0.3, max_tokens=900)
    if not text:
        return None
    data = extract_json(text)
    if not data or not isinstance(data.get("plants"), list):
        return None
    data["_elapsed_ms"] = round((time.time() - t0) * 1000, 1)
    data["_model"] = _config()["model"]
    return data
