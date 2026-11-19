# -*- coding: utf-8 -*-
"""案例图自动打标：主色 5 色、绿色占比、明度、高低分布；写回 cases_manifest.csv。

房间/风格/数量需人工或 CLIP 判定（W2 接入），脚本只做可解释的确定性部分。
    python tag_cases.py
"""
from __future__ import annotations
import numpy as np
from PIL import Image

from common import ROOT, read_csv, write_csv


def palette(arr: np.ndarray, k: int = 5) -> list[str]:
    px = arr.reshape(-1, 3)[::7].astype(np.int32)
    if len(px) > 20000:
        idx = np.linspace(0, len(px) - 1, 20000).astype(int)
        px = px[idx]
    q = (px // 32)
    keys = q[:, 0] * 64 + q[:, 1] * 8 + q[:, 2]
    vals, counts = np.unique(keys, return_counts=True)
    order = vals[np.argsort(-counts)][:k * 3]
    out, seen = [], set()
    for v in order:
        sel = px[keys == v]
        r, g, b = sel.mean(axis=0).round().astype(int)
        hexv = f"#{r:02X}{g:02X}{b:02X}"
        # 合并相近色（欧氏距离 < 30）
        if all(sum((a - b) ** 2 for a, b in zip((r, g, b), t)) > 900 for t in seen):
            out.append(hexv)
            seen.add((r, g, b))
        if len(out) >= k:
            break
    return out


def main() -> None:
    rows = read_csv("cases_manifest.csv")
    tagged = 0
    for r in rows:
        path = ROOT / r["file_path"] if r.get("file_path") else None
        if not path or not path.exists():
            continue
        im = Image.open(path).convert("RGB")
        small = np.asarray(im.resize((256, 256)))
        r_, g_, b_ = (small[:, :, i].astype(int) for i in range(3))
        green = ((g_ > r_ + 8) & (g_ > b_ + 8))
        ys, xs = np.where(green)
        if len(ys) == 0:
            r["height_profile"] = "none"
        else:
            top, bottom = ys.min() / 255, ys.max() / 255
            r["height_profile"] = "high" if bottom - top > 0.55 else ("mid" if bottom - top > 0.28 else "low")
            r["plant_count"] = str(max(1, min(9, int(len(ys) / (0.02 * 65536)))))
        r["palette_hex"] = "/".join(palette(small))
        tagged += 1
    if rows:
        write_csv("cases_manifest.csv", rows)
    print(f"打标完成 {tagged}/{len(rows)}")


if __name__ == "__main__":
    main()
