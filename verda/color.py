# -*- coding: utf-8 -*-
"""色彩工具：sRGB ↔ OKLab ↔ OKLCH

为什么用 OKLCH 而不是 HSL？
    HSL 的「明度」是相对亮度，同样 L=50% 的黄色和蓝色，人眼看着亮度差很远。
    OKLCH 是感知均匀色彩空间，L 值相同就真的看起来一样亮，色相差多少也符合直觉。
    需求文档里「色彩和谐」维度指定了 OKLCH，这里照着实现。

参考：https://bottosson.github.io/posts/oklab/
"""

import math


def _srgb_to_linear(c):
    """sRGB 分量（0~1）转线性光"""
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def hex_to_rgb(hex_str):
    """#RRGGBB 或 #RGB 转 (r, g, b)，取值 0~255"""
    s = hex_str.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    if len(s) != 6:
        raise ValueError("颜色格式不对：%s" % hex_str)
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_oklab(rgb):
    """sRGB (0~255) → OKLab (L, a, b)，L 在 0~1"""
    r, g, b = (_srgb_to_linear(v / 255.0) for v in rgb)

    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b

    l_ = l ** (1 / 3) if l > 0 else 0.0
    m_ = m ** (1 / 3) if m > 0 else 0.0
    s_ = s ** (1 / 3) if s > 0 else 0.0

    return (
        0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
        1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
        0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_,
    )


def oklab_to_oklch(lab):
    """OKLab → OKLCH (L, C, H)，H 是角度 0~360"""
    L, a, b = lab
    C = math.hypot(a, b)
    H = math.degrees(math.atan2(b, a)) % 360.0
    return (L, C, H)


def hex_to_oklch(hex_str):
    """#RRGGBB → (L, C, H)"""
    return oklab_to_oklch(rgb_to_oklab(hex_to_rgb(hex_str)))


def lightness(hex_str):
    """取明度 L（0~1）"""
    return hex_to_oklch(hex_str)[0]


def chroma(hex_str):
    """取彩度 C（0 附近就是中性色）"""
    return hex_to_oklch(hex_str)[1]


def hue(hex_str):
    """取色相角 H（0~360）"""
    return hex_to_oklch(hex_str)[2]


def hue_distance(h1, h2):
    """两个色相角的最短距离（0~180）"""
    d = abs(h1 - h2) % 360.0
    return min(d, 360.0 - d)


def is_greenish(hex_str, min_chroma=0.03):
    """判断是不是「绿色系」叶子

    绿色在 OKLCH 里的色相大约落在 120°~160°（OKLab 的色相环和 HSL 不一样，
    HSL 的绿色在 120°，OKLab 里偏到 140° 上下）。黄绿会往 100° 偏，蓝绿往 180° 偏，
    所以范围放宽到 90°~175°。
    """
    L, C, H = hex_to_oklch(hex_str)
    if C < min_chroma:          # 彩度太低，算中性色
        return False
    return 90.0 <= H <= 175.0


def is_neutral(hex_str, max_chroma=0.04):
    """判断是不是中性色（灰绿、银叶、白斑这类）"""
    return chroma(hex_str) < max_chroma
