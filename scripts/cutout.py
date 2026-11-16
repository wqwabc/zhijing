# -*- coding: utf-8 -*-
"""去底与规格化：inbox 原图 → 带 alpha 的 ≤1600px PNG + 主色 + 预览图 + 素材清单回写。

用法：
    python cutout.py                      # 处理 assets/inbox 下全部新图
    python cutout.py --engine simple      # 无 rembg 时的兜底（要求纯色背景）
    python cutout.py --file assets/inbox/P01/P01_inat_ab12cd34.jpg
"""
from __future__ import annotations
import argparse, io, re, sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops

from common import CUTOUT, INBOX, ASSETS, TODAY, read_csv, write_csv, log

LONG_EDGE = 1600


# ---------------------------------------------------------------- 去底
def cut_rembg(im: Image.Image) -> Image.Image:
    from rembg import remove, new_session
    session = new_session("u2net")
    return remove(im, session=session, alpha_matting=False)


def cut_onnx(im: Image.Image) -> Image.Image:
    import bg_onnx
    return bg_onnx.remove(im)


def cut_simple(im: Image.Image) -> Image.Image:
    """纯色背景兜底：从四边泛洪，去掉与角落颜色相近的区域。"""
    rgb = np.asarray(im.convert("RGB")).astype(np.int16)
    h, w, _ = rgb.shape
    corners = np.array([rgb[0, 0], rgb[0, w - 1], rgb[h - 1, 0], rgb[h - 1, w - 1]])
    bg = np.median(corners, axis=0)
    dist = np.sqrt(((rgb - bg) ** 2).sum(axis=2))
    tol = 38.0
    mask = dist < tol
    # 只保留与边缘连通的背景，避免误删叶片内部相近色
    from collections import deque
    bgmask = np.zeros((h, w), dtype=bool)
    dq = deque()
    for x in range(w):
        for y in (0, h - 1):
            if mask[y, x] and not bgmask[y, x]:
                bgmask[y, x] = True
                dq.append((y, x))
    for y in range(h):
        for x in (0, w - 1):
            if mask[y, x] and not bgmask[y, x]:
                bgmask[y, x] = True
                dq.append((y, x))
    while dq:
        y, x = dq.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not bgmask[ny, nx]:
                bgmask[ny, nx] = True
                dq.append((ny, nx))
    alpha = np.where(bgmask, 0, 255).astype(np.uint8)
    out = im.convert("RGBA")
    out.putalpha(Image.fromarray(alpha))
    return out


def harden_alpha(im: Image.Image, lo: int = 80, hi: int = 150) -> Image.Image:
    """压掉柔和阴影/灰边：把 alpha 拉成近似二值，再轻微羽化。"""
    import numpy as np
    from PIL import ImageFilter
    a = np.asarray(im.getchannel("A")).astype(np.float32)
    a = np.clip((a - lo) / max(1, hi - lo), 0, 1) * 255
    out = im.copy()
    out.putalpha(Image.fromarray(a.astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.6)))
    return out


def trim(im: Image.Image, pad_ratio: float = 0.015) -> Image.Image:
    alpha = im.getchannel("A")
    bbox = alpha.point(lambda v: 255 if v > 12 else 0).getbbox()
    if not bbox:
        return im
    pad = int(max(im.size) * pad_ratio)
    l, t, r, b = bbox
    l, t = max(0, l - pad), max(0, t - pad)
    r, b = min(im.width, r + pad), min(im.height, b + pad)
    return im.crop((l, t, r, b))


def fit(im: Image.Image, long_edge: int = LONG_EDGE, floor_edge: int = 1200) -> Image.Image:
    w, h = im.size
    if max(w, h) > long_edge:
        s = long_edge / max(w, h)
        im = im.resize((max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS)
    elif max(w, h) < floor_edge and floor_edge / max(w, h) <= 1.3:
        s = floor_edge / max(w, h)           # 小幅放大到质检下限，最多 1.3 倍
        im = im.resize((max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS)
    return im


def dominant_hex(im: Image.Image) -> tuple[str, float]:
    a = np.asarray(im)
    if a.shape[2] < 4:
        return "#000000", 0.0
    px = a[a[:, :, 3] > 200][:, :3].astype(np.int16)
    if len(px) == 0:
        return "#000000", 0.0
    lum = px.mean(axis=1)
    px = px[(lum > 25) & (lum < 240)]
    if len(px) == 0:
        return "#000000", 0.0
    q = (px // 32).astype(np.int32)
    keys = q[:, 0] * 64 + q[:, 1] * 8 + q[:, 2]
    vals, counts = np.unique(keys, return_counts=True)
    top = vals[counts.argmax()]
    sel = px[keys == top]
    r, g, b = sel.mean(axis=0).round().astype(int)
    return f"#{r:02X}{g:02X}{b:02X}", len(px) / (a.shape[0] * a.shape[1])


def checker_preview(im: Image.Image, width: int = 900) -> Image.Image:
    w, h = im.size
    s = width / max(w, h)
    im2 = im.resize((max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS)
    W, H = im2.size
    bg = Image.new("RGB", (W, H), (242, 242, 242))
    tile = 16
    draw = np.zeros((H, W, 3), dtype=np.uint8)
    for y in range(0, H, tile):
        for x in range(0, W, tile):
            c = 232 if ((x // tile) + (y // tile)) % 2 == 0 else 246
            draw[y:y + tile, x:x + tile] = c
    bg = Image.fromarray(draw)
    bg.paste(im2, (0, 0), im2)
    return bg


# ---------------------------------------------------------------- 主流程
def process(path: Path, engine: str, harden: bool = False) -> dict | None:
    m = re.match(r"(P\d{2})_(inat|unsplash|pexels|commons)_([0-9a-f]{5,12})", path.stem, re.I)
    if not m:
        print(f"  skip（命名不符）：{path.name}")
        return None
    plant_id, source = m.group(1), m.group(2)
    im = Image.open(path).convert("RGBA")
    if engine == "auto":
        import bg_onnx
        engine = "onnx" if bg_onnx.available() else "rembg"
    print(f"  {path.name} {im.width}x{im.height} -> {engine}")
    try:
        cut = {"rembg": cut_rembg, "onnx": cut_onnx, "simple": cut_simple}[engine](im)
    except Exception as e:
        print(f"  ! 去底失败 {type(e).__name__}: {e}")
        return None
    if harden:
        cut = harden_alpha(cut)
    cut = fit(trim(cut))
    folder = CUTOUT / plant_id
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{plant_id}_front_{source}.png"
    cut.save(out, "PNG", optimize=True)
    hexv, ratio = dominant_hex(cut)
    prev = checker_preview(cut)
    prev.save(folder / f"{plant_id}_front_{source}_preview.jpg", quality=88)
    print(f"  -> {out.name} {cut.width}x{cut.height} alpha={ratio:.1%} 主色 {hexv}")
    rec = {
        "plant_id": plant_id, "source": source, "file": str(out.relative_to(ASSETS.parent)),
        "width": cut.width, "height": cut.height, "alpha_ratio": ratio,
        "dominant_hex": hexv, "engine": engine, "src": str(path.relative_to(ASSETS.parent)),
    }
    log("cutout", **rec)
    return rec


def update_manifest(results: list[dict]) -> None:
    rows = read_csv("assets_manifest.csv")
    lic = {r["file_name"]: r for r in read_csv("license_table.csv")}
    by_plant = {}
    for r in results:
        by_plant.setdefault(r["plant_id"], r)
    for row in rows:
        hit = by_plant.get(row["plant_id"])
        if not hit:
            continue
        row.update({
            "status": "ready",
            "file_path": hit["file"],
            "width": str(hit["width"]),
            "height": str(hit["height"]),
            "has_alpha": "yes",
            "dominant_hex": hit["dominant_hex"],
            "cutout_engine": hit["engine"],
            "collected_at": TODAY,
            "note": f'alpha 覆盖 {hit["alpha_ratio"]:.1%}；原图 {hit["src"]}',
        })
        lr = lic.get(hit["file"])
        if lr:
            row.update({"source_url": lr["source_url"], "author": lr["author"],
                        "license": lr["license"], "license_url": lr["license_url"]})
    write_csv("assets_manifest.csv", rows)
    print(f"manifest 更新完成：{sum(1 for r in rows if r['status']=='ready')}/{len(rows)} 已就绪")


def main() -> None:
    ap = argparse.ArgumentParser(description="去底 / 规格化")
    ap.add_argument("--engine", choices=["auto", "onnx", "rembg", "simple"], default="auto")
    ap.add_argument("--file", default="")
    ap.add_argument("--harden", action="store_true", help="压掉阴影与灰边")
    a = ap.parse_args()
    files = [Path(a.file)] if a.file else sorted(INBOX.glob("P*/*.jpg"))
    if not files:
        sys.exit("assets/inbox 下没有候选图，先运行 collect.py")
    print(f"待处理 {len(files)} 张")
    results = []
    for f in files:
        r = process(f, a.engine, a.harden)
        if r:
            results.append(r)
    if results:
        update_manifest(results)
    print(f"完成 {len(results)}/{len(files)}")


if __name__ == "__main__":
    main()
