# -*- coding: utf-8 -*-
"""FR-04 照片合成（W1 MVP：单株即可用，多株自然支持）

已实现：
    - 按锚定比例等比缩放（px_per_cm x height_cm）
    - 株高校验并夹回真实区间（FR-07：高度锁定真实株高，不允许自由缩放）
    - 落地：底边贴 ground_y
    - 柔和接触阴影：椭圆 + 高斯模糊 + 半透明黑
    - 层级：layer 越大越靠后，layer 0 最前（docs/14 第 8 节）
    - 右下角「效果示意」水印（合规要求）

W2 再做：色温匹配、多株遮挡关系优化（目前靠 layer 手动控制）。

纯函数实现，不依赖 Flask，单测直接调 compose_photo()。
"""

import math
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

MAX_ITEMS = 6                       # FR-07：自选最多 6 株
PX_PER_CM_RANGE = (0.5, 40.0)       # docs/14：锚定合理区间

_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",                       # Windows 微软雅黑
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",   # Linux 文泉驿
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
]


def _find_font(size: int):
    """找一个支持中文的字体，找不到退回 PIL 内置（水印降级为英文）"""
    for path in _FONT_CANDIDATES:
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size), True
            except OSError:
                continue
    try:
        return ImageFont.load_default(size=size), False
    except TypeError:
        return ImageFont.load_default(), False


def _resolve_height_cm(requested, height_range_cm) -> (float, bool):
    """株高：缺省取区间中值；越界夹回区间。

    返回 (actual_cm, clamped)。真实区间 [80, 180] 的植物请求 400cm
    会被夹回 180cm。
    """
    lo, hi = height_range_cm
    if requested is None:
        return round((lo + hi) / 2.0, 1), False
    requested = float(requested)
    if not math.isfinite(requested):
        raise ValueError("height_cm 应为有限数字")
    actual = min(max(requested, lo), hi)
    return round(actual, 1), actual != requested


def _contact_shadow(shadow_img, draw_img, cx, base_y, w, h):
    """在落地点画一圈柔和阴影（椭圆 + 模糊）"""
    rx = max(12, int(w * 0.45))
    ry = max(6, int(h * 0.055))
    cx = int(cx)
    cy = int(base_y)
    draw_img.ellipse([cx - rx, cy - ry, cx + rx, cy + ry],
                     fill=(0, 0, 0, 90))
    blur = max(3, rx // 6)
    left, top = max(0, cx - rx * 2), max(0, cy - ry * 4)
    right = min(shadow_img.width, cx + rx * 2)
    bottom = min(shadow_img.height, cy + ry * 4)
    if right <= left or bottom <= top:
        return
    region = shadow_img.crop((left, top, right, bottom))
    blurred = region.filter(ImageFilter.GaussianBlur(blur))
    shadow_img.paste(blurred, (left, top))


def _draw_watermark(img):
    """右下角标「效果示意」（需求 FR-04：合成图必须标注）"""
    w, h = img.size
    size = max(16, min(64, max(w, h) // 40))
    font, has_cjk = _find_font(size)
    text = "效果示意 · 植境 Verda" if has_cjk else "PREVIEW ONLY - Verda"

    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    tw = d.textlength(text, font=font)
    pad = size // 2
    x1, y1 = w - tw - pad * 3, h - size - pad * 2
    d.rectangle([x1, y1, w - pad, h - pad], fill=(0, 0, 0, 120))
    d.text((x1 + pad, y1 + pad), text, fill=(255, 255, 255, 220), font=font)
    img.paste(layer, (0, 0), layer)


def compose_photo(base_img: Image.Image, items, assets_by_id: dict,
                  px_per_cm: float, ground_y: float,
                  watermark: bool = True):
    """把若干株植物合成进房间照片。

    :param base_img: 房间照片（RGB 或 RGBA，函数内转 RGB）
    :param items: [{plant_id, x, height_cm?, layer?}, ...]，1..6 株
    :param assets_by_id: server.assets.load_assets() 返回的 by_id
    :param px_per_cm: /api/anchor 得到的像素/厘米
    :param ground_y: 落地基准线的 y（像素）
    :return: (合成图 RGB, items_meta 列表, warnings 列表)
    """
    if not PX_PER_CM_RANGE[0] <= px_per_cm <= PX_PER_CM_RANGE[1]:
        raise ValueError("px_per_cm 超出合理范围 %.1f~%.1f，当前 %.2f"
                         % (PX_PER_CM_RANGE[0], PX_PER_CM_RANGE[1], px_per_cm))
    if not 1 <= len(items) <= MAX_ITEMS:
        raise ValueError("plants 数量应在 1~%d 株，收到 %d" % (MAX_ITEMS, len(items)))

    canvas = base_img.convert("RGB").copy()
    warnings = []

    # 按 alpha 的有效区域缩放，保证可见底边与阴影都落在 ground_y。
    resolved = []
    for it in items:
        asset = assets_by_id.get(it.get("plant_id", ""))
        if not asset or not asset["available"]:
            raise KeyError(it.get("plant_id", ""))
        h_cm, clamped = _resolve_height_cm(it.get("height_cm"),
                                           asset["height_range_cm"])
        if clamped:
            warnings.append("%s 的株高已按真实区间调整为 %.0fcm"
                            % (asset["name_cn"], h_cm))
        with Image.open(asset["abs_path"]) as source:
            src = source.convert("RGBA")
        visible_bounds = src.getchannel("A").getbbox()
        if visible_bounds is None:
            raise ValueError("%s 的素材完全透明" % asset["plant_id"])
        src = src.crop(visible_bounds)
        target_h = max(2, int(round(h_cm * px_per_cm)))
        scale = target_h / src.height
        target_w = max(2, int(round(src.width * scale)))
        plant = src.resize((target_w, target_h), Image.LANCZOS)
        resolved.append((it, asset, h_cm, int(it.get("layer") or 0), plant))

    # 层级：数值大的靠后先画，layer 0 最前最后画
    resolved.sort(key=lambda r: -r[3])

    # 1. 所有株的接触阴影先铺一层
    shadow_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow_layer)
    for it, asset, h_cm, layer, plant in resolved:
        _contact_shadow(shadow_layer, sdraw, it["x"], ground_y,
                        plant.width, plant.height)
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(2))
    canvas.paste(shadow_layer, (0, 0), shadow_layer)

    # 2. 植物按层级顺序贴入
    items_meta = []
    for it, asset, h_cm, layer, plant in resolved:
        px = int(it["x"]) - plant.width // 2
        py = int(ground_y) - plant.height
        canvas.paste(plant, (px, py), plant)

        bbox = [px, py, px + plant.width, py + plant.height]
        items_meta.append({
            "plant_id": asset["plant_id"],
            "name_cn": asset["name_cn"],
            "kind": asset["kind"],
            "drawn_height_px": plant.height,
            "requested_height_cm": it.get("height_cm"),
            "actual_height_cm": h_cm,
            "layer": layer,
            "bbox": bbox,
        })

    # 3. 水印
    if watermark:
        _draw_watermark(canvas)

    return canvas, items_meta, warnings
