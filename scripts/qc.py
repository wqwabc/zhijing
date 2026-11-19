# -*- coding: utf-8 -*-
"""素材 / 案例质检：按《分工表》第 10 节与需求 AC 逐项校验，输出 qc_report.csv。

用法：
    python qc.py            # 校验素材清单与案例清单
    python qc.py --strict   # 有 fail 时返回码 1（可挂到 CI / 提交前）
"""
from __future__ import annotations
import argparse, csv, math, re, sys
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

from common import ASSETS, DATA, ROOT, read_csv, write_csv

NAMING = re.compile(r"^P\d{2}_front_(inat|unsplash|pexels|commons|illustration)\.png$")


def srgb_to_lab(arr: np.ndarray) -> np.ndarray:
    """arr: (N,3) uint8 sRGB -> (N,3) CIELAB (D65)."""
    x = arr.astype(np.float64) / 255.0
    x = np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)
    M = np.array([[0.4124, 0.3576, 0.1805],
                  [0.2126, 0.7152, 0.0722],
                  [0.0193, 0.1192, 0.9505]])
    xyz = x @ M.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    L = 116 * f[:, 1] - 16
    a = 500 * (f[:, 0] - f[:, 1])
    b = 200 * (f[:, 1] - f[:, 2])
    return np.stack([L, a, b], axis=1)


def largest_component_ratio(alpha: np.ndarray) -> float:
    """最大连通域占不透明像素的比例（256px 缩略图上做，够用且快）。"""
    m = alpha > 128
    h, w = m.shape
    seen = np.zeros_like(m, dtype=bool)
    best = total = int(m.sum())
    if total == 0:
        return 0.0
    for y in range(h):
        for x in range(w):
            if not m[y, x] or seen[y, x]:
                continue
            q = deque([(y, x)])
            seen[y, x] = True
            size = 0
            while q:
                cy, cx = q.popleft()
                size += 1
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < h and 0 <= nx < w and m[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        q.append((ny, nx))
            best = max(best, size)
    return best / total


def check_asset(row: dict) -> dict:
    issues = []
    path = ROOT / row["file_path"] if row["file_path"] else None
    if not path or not path.exists():
        return {"verdict": "fail", "issues": "文件不存在", "long_edge": 0, "alpha_ratio": 0,
                "border_alpha": 1, "component": 0, "b_star": 0}
    im = Image.open(path)
    alpha = np.asarray(im.getchannel("A")) if im.mode == "RGBA" else None
    width, height = im.size
    long_edge = max(width, height)
    if alpha is None:
        issues.append("无 alpha 通道")
        return {"verdict": "fail", "issues": "；".join(issues), "long_edge": long_edge,
                "alpha_ratio": 0, "border_alpha": 1, "component": 0, "b_star": 0}
    opaque = alpha > 16
    ratio = float(opaque.mean())
    border = np.concatenate([alpha[0], alpha[-1], alpha[:, 0], alpha[:, -1]])
    border_alpha = float((border > 16).mean())
    small = np.asarray(im.resize((256, 256), Image.BILINEAR))
    comp = largest_component_ratio(small[:, :, 3])

    rgb = small[:, :, :3][small[:, :, 3] > 200]
    b_star = 0.0
    if len(rgb) > 50:
        lab = srgb_to_lab(rgb)
        # 只用叶片像素（排除偏白/偏黑的高光与阴影）
        leaf = lab[(lab[:, 0] > 20) & (lab[:, 0] < 92)]
        if len(leaf):
            b_star = float(np.median(leaf[:, 2]))

    if long_edge < 1200:
        issues.append(f"长边 {long_edge}<1200")
    if ratio < 0.04:
        issues.append(f"主体过小 {ratio:.1%}")
    if ratio > 0.85:
        issues.append(f"几乎无透明区域 {ratio:.1%}")
    if border_alpha > 0.10:
        issues.append(f"边缘未去净 {border_alpha:.0%}")
    if comp < 0.80:
        issues.append(f"疑似多株/碎片 最大连通域 {comp:.0%}")
    if b_star < -45 or b_star > 60:
        issues.append(f"色温偏色 b*={b_star:.0f}")
    if not NAMING.match(Path(row["file_path"]).name):
        issues.append("命名不符规范")
    illus = row.get("cutout_engine") == "illustration"
    if not illus and not row.get("source_url"):
        issues.append("缺来源 URL")
    if not row.get("license"):
        issues.append("缺许可")

    hard = [i for i in issues if not i.startswith("色温")]
    verdict = "fail" if hard else ("warn" if issues else "pass")
    return {"verdict": verdict, "issues": "；".join(issues), "long_edge": long_edge,
            "alpha_ratio": round(ratio, 3), "border_alpha": round(border_alpha, 3),
            "component": round(comp, 3), "b_star": round(b_star, 1)}


def check_case(row: dict) -> dict:
    issues = []
    path = ROOT / row["file_path"]
    if not path.exists():
        return {"verdict": "fail", "issues": "文件不存在"}
    im = Image.open(path).convert("RGB")
    w, h = im.size
    if max(w, h) < 800:
        issues.append("长边<800")
    arr = np.asarray(im.resize((256, 256)))
    r, g, b = arr[:, :, 0].astype(int), arr[:, :, 1].astype(int), arr[:, :, 2].astype(int)
    green = ((g > r + 8) & (g > b + 8)).mean()
    if green < 0.04:
        issues.append(f"绿色占比过低 {green:.1%}")
    if row.get("background") == "white_product":
        issues.append("白底产品图不可用")
    for k in ("room", "style", "license", "source_url"):
        if not row.get(k):
            issues.append(f"缺字段 {k}")
    verdict = "fail" if any("不可用" in i or "文件" in i or "白底" in i for i in issues) else (
        "warn" if issues else "pass")
    return {"verdict": verdict, "issues": "；".join(issues)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()
    assets = [r for r in read_csv("assets_manifest.csv") if r["file_path"]]
    cases = [r for r in read_csv("cases_manifest.csv") if r.get("file_path")]
    print(f"待检素材 {len(assets)}，案例 {len(cases)}")
    rows = []
    counts = {"pass": 0, "warn": 0, "fail": 0}
    for r in assets:
        res = check_asset(r)
        counts[res["verdict"]] += 1
        rows.append({"item": r["asset_id"], "type": "asset", "plant_id": r["plant_id"],
                     "file": r["file_path"], **res})
        flag = {"pass": "OK  ", "warn": "WARN", "fail": "FAIL"}[res["verdict"]]
        print(f"  {flag} {r['asset_id']} {res['long_edge']}px a={res['alpha_ratio']:.0%} "
              f"b*={res['b_star']:+.0f} {res['issues']}")
    for r in cases:
        res = check_case(r)
        counts[res["verdict"]] += 1
        rows.append({"item": r["case_id"], "type": "case", "plant_id": "",
                     "file": r["file_path"], **res})
    if rows:
        write_csv("qc_report.csv", rows)
    print(f"结果：pass {counts['pass']} / warn {counts['warn']} / fail {counts['fail']}")
    if counts["fail"]:
        print("有 fail 项：先修素材，不要入库。")
        if a.strict:
            sys.exit(1)


if __name__ == "__main__":
    main()
