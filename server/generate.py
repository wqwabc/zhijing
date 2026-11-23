# -*- coding: utf-8 -*-
"""AI 效果图：先按位置合成初稿，再交给图像模型做真实感融合。

默认用火山方舟 Seedream 5.0 Flash（参考图 + 指令编辑）。
可用 IMAGE_PROVIDER=wanx 切回通义万相的 mask 局部重绘。
没有 Key / 调用失败时退回初稿（本地合成），接口结构不变。
"""

import os
from io import BytesIO

from PIL import Image, ImageDraw, ImageFilter

from . import seedream, wanx
from .compose import _draw_watermark, compose_photo

WANX_PROMPT = (
    "白色蒙版区域内是一株绿植（含花盆）。请保留它的叶片、枝干和花盆形态，"
    "只按照房间的自然光方向、色温和地面接触阴影调整明暗与颜色，"
    "让它真实地融入这个客厅；不要删除或替换植物，不要修改蒙版外的房间、家具和构图。"
)

SEEDREAM_PROMPT = (
    "以这张室内照片为基础，把画面中的绿植自然地融入环境：保留房间、家具、"
    "植物品种与摆放位置，只匹配自然光方向、色温和地面接触阴影，照片级真实；"
    "不要新增或删除物体，不要改变构图。"
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


def _provider(overrides: dict = None) -> str:
    if overrides and overrides.get("provider"):
        return str(overrides["provider"]).lower()
    return os.environ.get("IMAGE_PROVIDER", "seedream").lower()


def generate(base: Image.Image, items, assets_by_id: dict, px_per_cm: float,
             ground_y: float, overrides: dict = None,
             lighting: str = "", time_of_day: str = ""):
    """返回 (PNG bytes, source, items_meta, warnings, elapsed_ms, reason)。"""
    import time
    t0 = time.time()

    init, meta, warnings = compose_photo(
        base, items, assets_by_id, px_per_cm, ground_y, watermark=False)

    buf = BytesIO()
    init.save(buf, "PNG")
    provider = _provider(overrides)
    reason = ""

    env = ""
    if lighting or time_of_day:
        env = " 环境：光照为%s，时间为%s，请按这个光线条件匹配色温、明暗和阴影。" % (
            lighting or "自然光", time_of_day or "白天")
    seedream_prompt = SEEDREAM_PROMPT + env
    wanx_prompt = WANX_PROMPT + env

    try:
        if provider == "wanx":
            mask_buf = BytesIO()
            build_mask(init.size, meta, assets_by_id).save(mask_buf, "PNG")
            out = wanx.edit_image(buf.getvalue(), mask_buf.getvalue(),
                                  wanx_prompt, overrides)
            source = "wanx"
        else:
            out = seedream.edit_image(buf.getvalue(), seedream_prompt, overrides)
            source = "seedream"
    except Exception as e:
        out = None
        source = "local"
        reason = str(e) or e.__class__.__name__

    if out:
        try:
            result = Image.open(BytesIO(out)).convert("RGB")
        except Exception as e:
            result = init.copy()
            source = "local"
            reason = "生成图无法解析：%s" % e
    else:
        result = init.copy()
        if source != "local":
            source = "local"
            reason = reason or "图像模型没有返回结果"

    _draw_watermark(result)
    final = BytesIO()
    result.save(final, "PNG")
    return (final.getvalue(), source, meta, warnings,
            round((time.time() - t0) * 1000, 1), reason)
