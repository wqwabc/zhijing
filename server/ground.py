# -*- coding: utf-8 -*-
"""落地线自动估计（纯 PIL，不依赖 OpenCV / 模型）。

思路：取照片底部区域的颜色作为“地板参考色”，在画面下半部找一条水平线：
线以上离地板色远、线以下离地板色近，且线以下纹理更强（地板通常有木纹/砖缝）。
找不到明显边界时退回 82% 高度，并给出低置信度。

局限：正面/轻微斜角的室内照最稳；地毯占满、地面被家具挡住、逆光时会失准。
"""

from PIL import Image

FALLBACK_RATIO = 0.85


def _row_stats(im):
    w, h = im.size
    px = im.load()
    means, tex = [], []
    for y in range(h):
        r = g = b = 0
        n = 0
        t = 0.0
        prev = None
        for x in range(0, w, 2):
            p = px[x, y]
            r += p[0]
            g += p[1]
            b += p[2]
            if prev is not None:
                t += abs(p[0] - prev[0]) + abs(p[1] - prev[1]) + abs(p[2] - prev[2])
            prev = p
            n += 1
        n = max(1, n)
        means.append((r / n, g / n, b / n))
        tex.append(t / n)
    return means, tex


def _dist(a, b):
    return sum(abs(a[i] - b[i]) for i in range(3))


def detect_groundline(path: str) -> dict:
    with Image.open(path) as im:
        im = im.convert("RGB")
        orig_w, orig_h = im.size
        im.thumbnail((320, 320))
        w, h = im.size
        means, tex = _row_stats(im)

    def rows_mean(a, b):
        a, b = max(0, a), min(h, b)
        n = max(1, b - a)
        return tuple(sum(means[i][k] for i in range(a, b)) / n for k in range(3))

    def rows_tex(a, b):
        a, b = max(0, a), min(h, b)
        n = max(1, b - a)
        return sum(tex[i] for i in range(a, b)) / n

    floor = rows_mean(int(h * 0.90), h)
    # 只在下部找：室内照片的地面线通常在 78%~90%，再往上多是家具/窗台边缘
    lo, hi = int(h * 0.78), int(h * 0.90)
    best_y, best_score = None, -1e9
    for y in range(lo, hi):
        below = rows_mean(y + 1, y + 9)
        above = rows_mean(y - 9, y)
        d_below = _dist(below, floor)
        d_above = _dist(above, floor)
        if d_below > 45:
            continue
        score = (d_above - d_below) + 0.35 * (rows_tex(y + 1, y + 9) - rows_tex(y - 9, y))
        score -= abs(y - h * 0.84) / h * 8.0
        if score > best_score:
            best_y, best_score = y, score

    if best_y is None or best_score < 8:
        y = int(orig_h * FALLBACK_RATIO)
        return {"ground_y": y, "confidence": 0.2,
                "method": "fallback", "points": [{"x": 0, "y": y}, {"x": orig_w, "y": y}]}

    conf = max(0.2, min(1.0, best_score / 55.0))
    y = round(best_y / h * orig_h, 1)
    return {"ground_y": y, "confidence": round(conf, 2),
            "method": "color-boundary", "points": [{"x": 0, "y": y}, {"x": orig_w, "y": y}],
            "image_width": orig_w, "image_height": orig_h}
