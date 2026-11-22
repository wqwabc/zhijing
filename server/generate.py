# -*- coding: utf-8 -*-
"""AI 效果图：先按位置合成初稿 + 植物 mask，再交给通义万相做局部重绘。

没有 Key / 调用失败时退回初稿（本地合成），接口结构不变。
"""

from io import BytesIO

from PIL import Image, ImageDraw, ImageFilter

from . import wanx
from .compose import _draw_watermark, compose_photo

PROMPT = (
    "白色蒙版区域内是一株绿植（含花盆）。请保留它的叶片、枝干和花盆形态，"
    "只按照房间的自然光方向、色温和地面接触阴影调整明暗与颜色，"
    "让它真实地融入这个客厅；不要删除或替换植物，不要修改蒙版外的房间、家具和构图。"
)


def build_mask(size, items_meta, assets_by_id: dict = None,
               pad_ratio: float = 0.04) -> Image.Image:
    """按植物 alpha 画掩膜（没有素材时退回 bbox），再外扩、柔化。"""
    mask = Image.new("L", size, 0)
    for m in items_meta:
        x1, y1, x2, y2 = m["bbox"]
        w, h = max(1, x2 - x1), max(1, y2 - y1)
        asset = (assets_by_id or {}).get(m.get("plant_id"))
        pasted = False
        if asset and asset.get("abs_path"):
            try:
                with Image.open(asset["abs_path"]) as src:
                    alpha = src.convert("RGBA").getchannel("A").resize(
                        (w, h), Image.LANCZOS)
                mask.paste(alpha, (x1, y1))
                pasted = True
            except Exception:
                pasted = False
        if not pasted:
            pad = max(10, int(max(w, h) * pad_ratio))
            ImageDraw.Draw(mask).rectangle(
                [x1 - pad, y1 - pad, x2 + pad, y2 + pad], fill=255)

    # 外扩一点包住接触阴影，再柔化边缘
    mask = mask.filter(ImageFilter.MaxFilter(11))
    return mask.filter(ImageFilter.GaussianBlur(4))


def generate(base: Image.Image, items, assets_by_id: dict, px_per_cm: float,
             ground_y: float, overrides: dict = None):
    """返回 (PNG bytes, source, items_meta, warnings, elapsed_ms)。"""
    import time
    t0 = time.time()

    init, meta, warnings = compose_photo(
        base, items, assets_by_id, px_per_cm, ground_y, watermark=False)

    buf = BytesIO()
    init.save(buf, "PNG")
    mask_buf = BytesIO()
    build_mask(init.size, meta, assets_by_id).save(mask_buf, "PNG")

    out = wanx.edit_image(buf.getvalue(), mask_buf.getvalue(), PROMPT, overrides)
    source = "wanx"
    if out:
        try:
            result = Image.open(BytesIO(out)).convert("RGB")
        except Exception:
            result = init.copy()
            source = "local"
    else:
        result = init.copy()
        source = "local"

    _draw_watermark(result)
    final = BytesIO()
    result.save(final, "PNG")
    return final.getvalue(), source, meta, warnings, round((time.time() - t0) * 1000, 1)
