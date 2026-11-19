# -*- coding: utf-8 -*-
"""程序化插画回退：为缺实拍素材的植物生成透明底示意图（需求 FR-05 允许的回退）。

不是照片，不冒充照片：清单里 source=illustration，许可标「自制 CC BY 4.0」。
    python gen_illustration.py --plants P07,P12
"""
from __future__ import annotations
import argparse, math, random
from pathlib import Path

from PIL import Image, ImageDraw

from common import ILLUS, read_csv, TODAY

W, H = 1200, 1600

# 每种：叶色、花色、盆色、形态参数
SPEC = {
    "P07": dict(form="clump", leaf="#2E7D32", accent="#D81B60", pot="#E8E2D8", n=9, flower="spathe"),
    "P12": dict(form="climb", leaf="#1B5E20", accent=None, pot="#8D6E63", n=7, split=True),
    "P14": dict(form="tree", leaf="#4E7A3A", accent=None, pot="#A1887F", n=8, round=True),
    "P20": dict(form="trail", leaf="#2F6B3A", accent=None, pot="#D7CCC8", n=10, lobed=True),
    "P21": dict(form="trail", leaf="#5B8C3E", accent="#E8F0C8", pot="#F5F5F5", n=9, stripe=True),
    "P27": dict(form="clump", leaf="#2E5E2A", accent="#FFFFFF", pot="#C8A165", n=8, flower="small"),
    "P28": dict(form="clump", leaf="#1F4D2E", accent="#FAFAFA", pot="#E0E0E0", n=8, flower="small"),
    "P29": dict(form="clump", leaf="#2F6B3A", accent="#7E9BD6", pot="#B0BEC5", n=9, flower="ball"),
    "P30": dict(form="upright", leaf="#4F6B3A", accent=None, pot="#EFEBE9", n=14, needle=True),
    "P31": dict(form="upright", leaf="#3F7A34", accent=None, pot="#D7CCC8", n=8, serrate=True),
    "P32": dict(form="epiphyte", leaf="#8FA37A", accent=None, pot=None, n=12, needle=True),
    "P33": dict(form="epiphyte", leaf="#4C7A4A", accent=None, pot=None, n=6, antler=True),
    "P37": dict(form="trail", leaf="#3B6E8F", accent="#7FB3C8", pot="#E0E0E0", n=12, stripe=True),
    "P38": dict(form="clump", leaf="#2F7A3E", accent=None, pot="#F0EDE8", n=14, round=True),
    "P39": dict(form="clump", leaf="#4E7A4A", accent=None, pot="#D7CCC8", n=12, needle=True),
    "P40": dict(form="clump", leaf="#2E7D32", accent="#E8A0B4", pot="#EFEBE9", n=7),
    "P41": dict(form="tree", leaf="#3F6B34", accent=None, pot="#C8A165", n=7),
    "P42": dict(form="trail", leaf="#3F7A4A", accent="#E58FA8", pot="#D7CCC8", n=10),
    "P43": dict(form="clump", leaf="#2F6B3A", accent="#E4C441", pot="#EFEBE9", n=9, flower="ball"),
    "P44": dict(form="tree", leaf="#9DB4A8", accent=None, pot="#B0BEC5", n=9),
    "P46": dict(form="upright", leaf="#3F7A4A", accent=None, pot="#5D4037", n=5, needle=True),
    "P47": dict(form="clump", leaf="#2F6B3A", accent=None, pot="#D7CCC8", n=9),
    "P35": dict(form="tree", leaf="#2E6B34", accent=None, pot="#5D4037", n=9, palmate=True),
}


def leaf_shape(d, cx, cy, rx, ry, ang, color):
    pts = []
    for t in range(0, 360, 12):
        a = math.radians(t)
        r = 1 - 0.35 * abs(math.cos(a))
        x = rx * r * math.cos(a)
        y = ry * math.sin(a)
        pts.append((x, y))
    ca, sa = math.cos(ang), math.sin(ang)
    pts = [(cx + x * ca - y * sa, cy + x * sa + y * ca) for x, y in pts]
    d.polygon(pts, fill=color)


def draw(pid: str, spec: dict) -> Image.Image:
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    rnd = random.Random(pid)
    leaf, accent, pot = spec["leaf"], spec["accent"], spec.get("pot")
    form = spec["form"]
    base_y = 1430

    if pot:
        pw, ph = 360, 300
        d.polygon([(W / 2 - pw / 2, base_y - ph), (W / 2 + pw / 2, base_y - ph),
                   (W / 2 + pw / 2 - 45, base_y), (W / 2 - pw / 2 + 45, base_y)], fill=pot)
        d.rectangle([W / 2 - pw / 2 - 12, base_y - ph - 26, W / 2 + pw / 2 + 12, base_y - ph + 4], fill=pot)
        soil_y = base_y - ph + 6
    else:
        # 附生：木板
        d.rounded_rectangle([W / 2 - 210, 420, W / 2 + 210, 1150], 18, fill="#8D6E63")
        soil_y = 700

    def stem(x0, y0, x1, y1, w=10, color="#4E6B3A"):
        d.line([(x0, y0), (x1, y1)], fill=color, width=w)

    if form == "tree":
        y = soil_y
        for i in range(3):
            stem(W / 2, y, W / 2 + rnd.randint(-40, 40), y - 380, 16, "#6D4C41")
            y -= 320
        for i in range(spec["n"]):
            ang = rnd.uniform(-0.9, 0.9)
            cx = W / 2 + rnd.randint(-330, 330)
            cy = rnd.randint(300, 950)
            leaf_shape(d, cx, cy, 110, 70, ang, leaf)
    elif form == "clump":
        for i in range(spec["n"] + 4):
            x = W / 2 + rnd.randint(-150, 150)
            stem(x, soil_y, x + rnd.randint(-220, 220), rnd.randint(700, 1050), 9)
        for i in range(spec["n"]):
            cx = W / 2 + rnd.randint(-360, 360)
            cy = rnd.randint(560, 1000)
            leaf_shape(d, cx, cy, 140, 80, rnd.uniform(-1, 1), leaf)
        if accent and spec.get("flower") == "small":
            for i in range(6):
                cx, cy = W / 2 + rnd.randint(-300, 300), rnd.randint(520, 860)
                for k in range(5):
                    a = k * 72 + rnd.randint(-8, 8)
                    leaf_shape(d, cx + 26 * math.cos(math.radians(a)), cy + 26 * math.sin(math.radians(a)),
                               34, 22, math.radians(a), accent)
                d.ellipse([cx - 9, cy - 9, cx + 9, cy + 9], fill="#F2C94C")
        if accent and spec.get("flower") == "ball":
            for i in range(3):
                cx, cy = W / 2 + rnd.randint(-280, 280), rnd.randint(520, 800)
                d.ellipse([cx - 95, cy - 95, cx + 95, cy + 95], fill=accent)
        if accent and spec.get("flower") == "spathe":
            for i in range(4):
                cx, cy = W / 2 + rnd.randint(-260, 260), rnd.randint(600, 900)
                leaf_shape(d, cx, cy, 70, 120, rnd.uniform(-0.4, 0.4), accent)
                d.line([(cx, cy + 60), (cx, cy + 210)], fill="#2E7D32", width=8)
    elif form == "climb":
        stem(W / 2, soil_y, W / 2 + 20, 520, 18, "#6D4C41")
        for i in range(spec["n"]):
            ang = rnd.uniform(-1.1, 1.1)
            cx = W / 2 + rnd.randint(-300, 300)
            cy = rnd.randint(420, 980)
            leaf_shape(d, cx, cy, 170 if spec.get("split") else 110, 120, ang, leaf)
    elif form == "upright":
        for i in range(spec["n"]):
            x = W / 2 + rnd.randint(-160, 160)
            top = rnd.randint(520, 1050)
            stem(x, soil_y, x, top, 7)
            for k in range(4):
                yy = top + k * 80
                if spec.get("needle"):
                    d.line([(x, yy), (x + rnd.choice([-110, 110]), yy - 90)], fill=leaf, width=6)
                else:
                    leaf_shape(d, x + rnd.choice([-90, 90]), yy, 70, 34, rnd.uniform(-0.6, 0.6), leaf)
    elif form == "trail":
        for i in range(spec["n"]):
            x0 = W / 2 + rnd.randint(-80, 80)
            x1 = x0 + rnd.randint(-420, 420)
            y1 = rnd.randint(980, 1400)
            d.line([(x0, soil_y), (x1, y1)], fill="#4E6B3A", width=6)
            for k in range(5):
                t = k / 5
                cx = x0 + (x1 - x0) * t + rnd.randint(-40, 40)
                cy = soil_y + (y1 - soil_y) * t
                color = accent if (spec.get("stripe") and k % 2) else leaf
                leaf_shape(d, cx, cy, 78, 42, rnd.uniform(-1.2, 1.2), color)
    elif form == "epiphyte":
        for i in range(spec["n"]):
            cx = W / 2 + rnd.randint(-160, 160)
            cy = rnd.randint(520, 980)
            if spec.get("antler"):
                leaf_shape(d, cx, cy, 60, 150, rnd.uniform(-0.8, 0.8), leaf)
            else:
                leaf_shape(d, cx, cy, 30, 120, rnd.uniform(-0.9, 0.9), leaf)
    return im


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plants", default="")
    a = ap.parse_args()
    rows = read_csv("assets_manifest.csv")
    todo = [p for p in (a.plants.split(",") if a.plants else SPEC) if p in SPEC]
    for pid in todo:
        ILLUS.mkdir(parents=True, exist_ok=True)
        im = draw(pid, SPEC[pid])
        out = ILLUS / f"{pid}_front_illustration.png"
        im.save(out, "PNG", optimize=True)
        prev = im.copy()
        bg = Image.new("RGB", prev.size, (244, 244, 244))
        bg.paste(prev, (0, 0), prev)
        bg.thumbnail((600, 800))
        bg.save(ILLUS / f"{pid}_front_illustration_preview.jpg", quality=88)
        print("ok", pid, out.relative_to(ILLUS.parents[1]))
    print("done", len(todo))


if __name__ == "__main__":
    main()
