# -*- coding: utf-8 -*-
"""房间照片的轻量特征提取（不依赖 numpy / 模型）。

只做确定性统计：主色、亮度、色温、绿色占比、风格与光照估计。
这些特征会以**文本**形式发给大模型，照片本身不出本机（合规）。
"""

import colorsys
from collections import Counter

from PIL import Image


def _hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(c))) for c in rgb)


def analyze(path: str) -> dict:
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((240, 240))
        q = im.quantize(colors=8, method=2).convert("RGB")

    pixels = list(q.getdata())
    total = len(pixels) or 1
    counts = Counter(pixels)

    palette = [{"hex": _hex(rgb), "share": round(n / total, 3)}
               for rgb, n in counts.most_common(8)]

    rs = [p[0] for p in pixels]
    gs = [p[1] for p in pixels]
    bs = [p[2] for p in pixels]
    brightness = (0.2126 * sum(rs) + 0.7152 * sum(gs) + 0.0722 * sum(bs)) / total / 255.0

    hsv = [colorsys.rgb_to_hsv(r / 255, g / 255, b / 255) for r, g, b in pixels]
    saturation = sum(h[1] for h in hsv) / total
    warmth = (sum(rs) - sum(bs)) / total / 255.0
    green_share = sum(1 for r, g, b in pixels if g > r + 8 and g > b + 8) / total

    if saturation < 0.16:
        style = "oriental"
    elif green_share > 0.3 and saturation > 0.28:
        style = "tropical"
    elif brightness > 0.62 and warmth > 0.05:
        style = "nordic"
    elif brightness < 0.42:
        style = "modern"
    elif warmth > 0.12:
        style = "midcentury"
    else:
        style = "mediterranean"

    light = 1.5 if brightness < 0.4 else (2.0 if brightness < 0.52 else (3.0 if brightness < 0.7 else 4.0))

    return {
        "palette": palette,
        "brightness": round(brightness, 2),
        "saturation": round(saturation, 2),
        "warmth": round(warmth, 2),
        "green_share": round(green_share, 2),
        "style_guess": style,
        "light_guess": light,
        "method": "color-heuristic",
    }
