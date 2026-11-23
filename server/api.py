# -*- coding: utf-8 -*-
"""HTTP 路由层。契约：docs/14_接口契约.md（改字段先改文档，版本号 +1）。

评分 / 推荐 / 改稿直接包装 verda 包（C 交付），返回结构原样透传，
不另造一套（保证 AC-11 双入口分数一致）。
"""

import datetime
import math
import os
import time

from flask import (Blueprint, current_app, jsonify, request, send_file)

from verda import Combo, Scene, recommend, revise, score_combo
from verda.loader import load_plants

from .assets import load_assets
from .chat import reply as chat_reply
from .compose import MAX_ITEMS, PX_PER_CM_RANGE, compose_photo
from .design import design
from .generate import generate as generate_image
from .ground import detect_groundline
from .store import RESULT_NAME_RE
from .validation import SUPPORTED_FORMATS, PhotoFormatError, load_photo, \
    validate_photo

api_bp = Blueprint("api", __name__)

REF_HEIGHTS = {"door": 200.0, "bed": 50.0, "sofa": 80.0}

_PLANTS_CACHE = {}       # repo_root -> (plants, by_id)


def _store():
    return current_app.extensions["verda_store"]


def _repo_root() -> str:
    return current_app.config["REPO_ROOT"]


def _err(status: int, code: str, message: str, hint: str = None, field: str = None):
    body = {"error": {"code": code, "message": message}}
    if hint:
        body["error"]["hint"] = hint
    if field:
        body["error"]["field"] = field
    return jsonify(body), status


def _body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError(400, "E40001", "请求体应为 JSON 对象")
    return data


def _llm_cfg():
    """前端设置里填的 Key/Base，仅本次请求使用，不落盘。"""
    key = request.headers.get("X-LLM-Key", "").strip()
    base = request.headers.get("X-LLM-Base", "").strip()
    return {"api_key": key, "base": base} if key else None


def _image_cfg():
    """前端填的图像模型 Key，仅本次请求使用。

    X-Ark-Key  → 火山方舟 Seedream（默认）
    X-Wanx-Key → 通义万相
    X-Image-Provider / X-Image-Model 可显式覆盖。
    """
    ark = request.headers.get("X-Ark-Key", "").strip()
    wanx = request.headers.get("X-Wanx-Key", "").strip()
    provider = request.headers.get("X-Image-Provider", "").strip().lower()
    model = request.headers.get("X-Image-Model", "").strip()
    if ark:
        cfg = {"api_key": ark, "provider": "seedream"}
    elif wanx:
        cfg = {"api_key": wanx, "provider": "wanx"}
    else:
        return None
    if provider in ("seedream", "wanx"):
        cfg["provider"] = provider
    if model:
        cfg["model"] = model
    return cfg


class ApiError(Exception):
    def __init__(self, status, code, message, hint=None, field=None):
        super().__init__(message)
        self.status, self.code = status, code
        self.message, self.hint, self.field = message, hint, field


@api_bp.errorhandler(ApiError)
def _api_error(e: ApiError):
    return _err(e.status, e.code, e.message, e.hint, e.field)


def _get_plants():
    """植物主数据（进程内缓存，B 更新数据重启即可）"""
    root = _repo_root()
    if root not in _PLANTS_CACHE:
        plants = load_plants(os.path.join(root, "data"))
        _PLANTS_CACHE[root] = (plants, {p.plant_id: p for p in plants})
    return _PLANTS_CACHE[root]


def _make_scene(raw: dict) -> Scene:
    if not isinstance(raw, dict):
        raise ApiError(400, "E40001", "scene 应为对象")
    has_pet = raw.get("has_pet", False)
    if isinstance(has_pet, str) and has_pet.strip().lower() in ("true", "false", "1", "0"):
        has_pet = has_pet.strip().lower() in ("true", "1")
    elif type(has_pet) is int and has_pet in (0, 1):
        has_pet = bool(has_pet)
    elif not isinstance(has_pet, bool):
        raise ApiError(400, "E40001", "scene.has_pet 应为布尔值", field="scene.has_pet")
    try:
        return Scene(
            room=str(raw.get("room", "")).strip(),
            style=str(raw.get("style", "")).strip(),
            light=int(raw.get("light", 2)),
            weekly_minutes=int(raw.get("weekly_minutes", 30)),
            has_pet=has_pet,
            budget=float(raw.get("budget", 500)),
        )
    except (ValueError, TypeError) as e:
        raise ApiError(400, "E40001", "scene 参数不合法：%s" % e, field="scene")


def _make_combo(plant_ids: list) -> Combo:
    if not isinstance(plant_ids, list) or not plant_ids:
        raise ApiError(400, "E40001", "plant_ids 应为非空数组", field="plant_ids")
    _, by_id = _get_plants()
    picked = []
    for pid in plant_ids:
        if not isinstance(pid, str):
            raise ApiError(400, "E40001", "plant_ids 中每项都应为字符串", field="plant_ids")
        p = by_id.get(pid)
        if p is None:
            raise ApiError(404, "E40402", "植物不存在：%s" % pid, field="plant_ids")
        picked.append(p)
    return Combo(picked)


def _point(raw):
    if not isinstance(raw, dict) or "x" not in raw or "y" not in raw:
        raise ApiError(400, "E40001", "点的坐标应为 {x, y} 像素")
    return _finite_number(raw["x"], "point.x"), _finite_number(raw["y"], "point.y")


def _finite_number(value, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(400, "E40001", "%s 应为数字" % field, field=field)
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ApiError(400, "E40001", "%s 应为数字" % field, field=field)
    if not math.isfinite(number):
        raise ApiError(400, "E40001", "%s 应为有限数字" % field, field=field)
    return number


# ---------------------------------------------------------------- 基础

@api_bp.get("/healthz")
def healthz():
    from server import BACKEND_VERSION
    from verda import __version__ as verda_version
    from . import llm, seedream, wanx
    return jsonify(status="ok", verda=verda_version, backend=BACKEND_VERSION,
                   uptime_s=round(time.time() - _START, 1),
                   llm={"available": llm.available(),
                        "model": llm._config()["model"]},
                   image={"provider": os.environ.get("IMAGE_PROVIDER", "seedream"),
                          "ark_key": seedream.available(),
                          "wanx_key": wanx.available(),
                          "model": seedream._model()})


_START = time.time()


# ---------------------------------------------------------------- FR-01

@api_bp.post("/api/upload")
def upload():
    f = request.files.get("photo")
    if f is None:
        raise ApiError(400, "E40001", "multipart 字段 photo 缺失", field="photo")
    data = f.read()
    try:
        img = load_photo(data)
    except PhotoFormatError as e:
        raise ApiError(415, "E40002", str(e),
                       hint="支持 JPG/PNG，不超过 10MB", field="photo")

    result = validate_photo(img)
    photo_id = _store().put_photo(data, SUPPORTED_FORMATS[img.format])

    # 校验结论存元数据，供 /api/compose 拦截不可用照片（E40003）
    _store().put_meta(photo_id, {"usable": result["usable"]})

    resp = {
        "photo_id": photo_id,
        "width": img.size[0],
        "height": img.size[1],
    }
    resp.update(result)
    return jsonify(resp)


# ---------------------------------------------------------------- FR-02

@api_bp.post("/api/anchor")
def anchor():
    body = _body()
    photo_id = body.get("photo_id", "")
    if not _store().photo_path(photo_id):
        raise ApiError(404, "E40401", "photo_id 不存在或已过期", field="photo_id")

    for key in ("ground", "ref"):
        if not isinstance(body.get(key), list) or len(body[key]) != 2:
            raise ApiError(400, "E40001", "%s 应为两个点" % key, field=key)

    g1, g2 = _point(body["ground"][0]), _point(body["ground"][1])
    r1, r2 = _point(body["ref"][0]), _point(body["ref"][1])

    ref_type = body.get("ref_type", "door")
    if ref_type == "custom":
        try:
            ref_h = float(body.get("custom_height_cm", 0))
        except (TypeError, ValueError):
            ref_h = 0.0
        if not 20 <= ref_h <= 400:
            raise ApiError(400, "E40001",
                           "custom_height_cm 应在 20~400cm", field="custom_height_cm")
    elif ref_type in REF_HEIGHTS:
        ref_h = REF_HEIGHTS[ref_type]
    else:
        raise ApiError(400, "E40001",
                       "ref_type 应为 door/bed/sofa/custom", field="ref_type")

    ref_len_px = math.hypot(r2[0] - r1[0], r2[1] - r1[1])
    if ref_len_px < 10:
        raise ApiError(400, "E40001", "参照线太短（<10px），请拉开门高全高",
                       field="ref")
    if abs(r2[1] - r1[1]) < ref_len_px * 0.2:
        raise ApiError(400, "E40001", "高度参照线接近水平，请沿竖直方向点选",
                       field="ref")
    px_per_cm = ref_len_px / ref_h
    if not PX_PER_CM_RANGE[0] <= px_per_cm <= PX_PER_CM_RANGE[1]:
        raise ApiError(409, "E40901",
                       "锚定结果 %.2f px/cm 超出合理范围 %.1f~%.1f，参照可能点错了"
                       % (px_per_cm, *PX_PER_CM_RANGE))

    ground_y_mid = (g1[1] + g2[1]) / 2.0
    ground_angle = math.degrees(math.atan2(g2[1] - g1[1], g2[0] - g1[0]))

    warnings = []
    return jsonify(
        px_per_cm=round(px_per_cm, 2),
        ref_height_cm=ref_h,
        ground_y_mid=round(ground_y_mid, 1),
        ground_y=round(ground_y_mid, 1),      # 别名：/api/compose 直接透传用
        ground_angle_deg=round(ground_angle, 2),
        ref_length_px=round(ref_len_px, 1),
        warnings=warnings,
        preview={"suggest_plant": "P01", "suggest_height_cm": 150,
                 "suggest_px": round(150 * px_per_cm)},
    )


# ---------------------------------------------------------------- FR-03/06/07

@api_bp.post("/api/score")
def score():
    body = _body()
    combo = _make_combo(body.get("plant_ids"))
    scene = _make_scene(body.get("scene"))
    t0 = time.time()
    result = score_combo(combo, scene).as_dict()
    result["elapsed_ms"] = round((time.time() - t0) * 1000, 1)
    return jsonify(result)


@api_bp.post("/api/recommend")
def api_recommend():
    body = _body()
    scene = _make_scene(body.get("scene"))
    t0 = time.time()
    plans = recommend(scene, _get_plants()[0])
    plans["elapsed_ms"] = round((time.time() - t0) * 1000, 1)
    return jsonify(plans)


@api_bp.post("/api/revise")
def api_revise():
    body = _body()
    combo = _make_combo(body.get("plant_ids"))
    scene = _make_scene(body.get("scene"))
    instruction = str(body.get("instruction", "")).strip()
    if not instruction:
        raise ApiError(400, "E40001", "instruction 不能为空", field="instruction")
    result = revise(combo, scene, instruction)
    return jsonify(result)


# ---------------------------------------------------------------- FR-04

@api_bp.post("/api/compose")
def api_compose():
    body = _body()
    photo_id = body.get("photo_id", "")
    photo_path = _store().photo_path(photo_id)
    if not photo_path:
        raise ApiError(404, "E40401", "photo_id 不存在或已过期", field="photo_id")

    meta = _store().get_meta(photo_id)
    if meta is None or "usable" not in meta:
        raise ApiError(404, "E40401", "照片校验记录不存在或已过期，请重新上传",
                       field="photo_id")
    if meta["usable"] is False:
        raise ApiError(422, "E40003", "该照片未通过可用性校验，不能用于合成",
                       hint="请重新上传，或改用立面模式", field="photo_id")

    anchor = body.get("anchor")
    if not isinstance(anchor, dict):
        raise ApiError(400, "E40001", "anchor 应为对象", field="anchor")
    px_per_cm = _finite_number(anchor.get("px_per_cm"), "anchor.px_per_cm")
    ground_y = _finite_number(anchor.get("ground_y"), "anchor.ground_y")
    if not PX_PER_CM_RANGE[0] <= px_per_cm <= PX_PER_CM_RANGE[1]:
        raise ApiError(409, "E40901",
                       "px_per_cm=%.2f 超出合理范围，请先调用 /api/anchor"
                       % px_per_cm, field="anchor")

    items = body.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_ITEMS:
        raise ApiError(400, "E40001",
                       "items 应为 1~%d 株的数组" % MAX_ITEMS, field="items")

    from PIL import Image
    with Image.open(photo_path) as photo:
        photo_w, photo_h = photo.size
    if not 0 < ground_y <= photo_h:
        raise ApiError(400, "E40001", "anchor.ground_y 超出照片范围",
                       field="anchor.ground_y")

    assets = load_assets(_repo_root())
    normalized_items = []
    for it in items:
        if not isinstance(it, dict):
            raise ApiError(400, "E40001", "items 中每项都应为对象", field="items")
        pid = it.get("plant_id")
        if not isinstance(pid, str):
            raise ApiError(400, "E40001", "plant_id 应为字符串", field="items")
        asset = assets["by_id"].get(pid)
        if asset is None:
            raise ApiError(404, "E40402", "植物不存在：%s" % pid, field="items")
        if not asset["available"]:
            raise ApiError(404, "E40403",
                           "%s 的素材文件缺失或不可用" % pid, field="items")
        x = _finite_number(it.get("x"), "items[].x")
        if not 0 <= x <= photo_w:
            raise ApiError(400, "E40001", "items[].x 超出照片范围",
                           field="items[].x")
        height_cm = it.get("height_cm")
        if height_cm is not None:
            height_cm = _finite_number(height_cm, "items[].height_cm")
            if height_cm <= 0:
                raise ApiError(400, "E40001", "height_cm 应大于 0",
                               field="items[].height_cm")
        layer = it.get("layer", 0)
        if type(layer) is not int or layer < 0:
            raise ApiError(400, "E40001", "items[].layer 应为非负整数",
                           field="items[].layer")
        normalized_items.append({"plant_id": pid, "x": x,
                                 "height_cm": height_cm, "layer": layer})

    watermark = body.get("watermark", True)
    if not isinstance(watermark, bool):
        raise ApiError(400, "E40001", "watermark 应为布尔值", field="watermark")
    warnings = []
    t0 = time.time()

    import io
    with Image.open(photo_path) as base:
        if current_app.config.get("MOCK"):
            # mock 返回真正的 PNG，避免 .png URL 与 JPEG 字节不一致。
            canvas = base.convert("RGB")
            items_meta = [{
                "plant_id": it["plant_id"],
                "name_cn": assets["by_id"][it["plant_id"]]["name_cn"],
                "kind": assets["by_id"][it["plant_id"]]["kind"],
                "mock": True,
            } for it in normalized_items]
        else:
            try:
                canvas, items_meta, warnings = compose_photo(
                    base, normalized_items, assets["by_id"], px_per_cm,
                    ground_y, watermark)
            except ValueError as e:
                raise ApiError(400, "E40001", str(e))
            except KeyError as e:
                raise ApiError(404, "E40403", "素材缺失：%s" % e.args[0])
    buf = io.BytesIO()
    canvas.save(buf, "PNG")
    name = _store().put_result(buf.getvalue())
    w, h = canvas.size
    elapsed = 0.1 if current_app.config.get("MOCK") else round((time.time() - t0) * 1000, 1)

    path = _store().result_path(name)
    expires = datetime.datetime.fromtimestamp(_store().expires_at(path))
    return jsonify(
        image_url="/api/compose/%s" % name,
        width=w,
        height=h,
        items_meta=items_meta,
        warnings=warnings,
        elapsed_ms=elapsed,
        expires_at=expires.isoformat(timespec="seconds"),
    )


# ---------------------------------------------------------------- 自动落地线

@api_bp.post("/api/groundline")
def api_groundline():
    """根据地板颜色/纹理估计地面线；置信度低时前端提示手动调整。"""
    body = _body()
    photo_id = body.get("photo_id", "")
    path = _store().photo_path(photo_id)
    if not path:
        raise ApiError(404, "E40401", "photo_id 不存在或已过期", field="photo_id")
    return jsonify(detect_groundline(path))


# ---------------------------------------------------------------- 大模型选株

@api_bp.post("/api/design")
def api_design():
    """大模型看图选株（只看统计特征）→ 本地约束校验 → 确定性评分 → 合成。"""
    body = _body()
    photo_id = body.get("photo_id", "")
    photo_path = _store().photo_path(photo_id)
    if not photo_path:
        raise ApiError(404, "E40401", "photo_id 不存在或已过期", field="photo_id")

    meta = _store().get_meta(photo_id)
    if meta is None or "usable" not in meta:
        raise ApiError(404, "E40401", "照片校验记录不存在或已过期，请重新上传",
                       field="photo_id")
    if meta["usable"] is False:
        raise ApiError(422, "E40003", "该照片未通过可用性校验，不能用于合成",
                       hint="请重新上传，或改用立面模式", field="photo_id")

    scene = _make_scene(body.get("scene"))
    count = body.get("count", 3)
    if type(count) is not int or not 1 <= count <= 5:
        raise ApiError(400, "E40001", "count 应为 1~5 的整数", field="count")

    from PIL import Image
    with Image.open(photo_path) as im:
        photo_w, photo_h = im.size

    anchor = body.get("anchor")
    warnings = []
    if anchor is None:
        px_per_cm = round(photo_h * 0.5 / 150.0, 2)
        ground_y = round(photo_h * 0.92, 1)
        warnings.append("未提供 anchor，按默认比例合成（%.2f px/cm）" % px_per_cm)
    else:
        if not isinstance(anchor, dict):
            raise ApiError(400, "E40001", "anchor 应为对象", field="anchor")
        px_per_cm = _finite_number(anchor.get("px_per_cm"), "anchor.px_per_cm")
        ground_y = _finite_number(anchor.get("ground_y"), "anchor.ground_y")
        if not PX_PER_CM_RANGE[0] <= px_per_cm <= PX_PER_CM_RANGE[1]:
            raise ApiError(409, "E40901",
                           "px_per_cm=%.2f 超出合理范围" % px_per_cm, field="anchor")
        if not 0 < ground_y <= photo_h:
            raise ApiError(400, "E40001", "anchor.ground_y 超出照片范围",
                           field="anchor.ground_y")

    assets = load_assets(_repo_root())
    plan = design(photo_path, scene, _get_plants()[0], assets, count,
                  llm_cfg=_llm_cfg())

    items, plants_out = [], []
    for it in plan["items"]:
        x = int(round(it["x_frac"] * photo_w))
        items.append({"plant_id": it["plant_id"], "x": x,
                      "height_cm": it["height_cm"], "layer": it["layer"]})
        asset = assets["by_id"].get(it["plant_id"], {})
        plants_out.append({
            "plant_id": it["plant_id"],
            "name_cn": asset.get("name_cn", ""),
            "kind": asset.get("kind", ""),
            "height_cm": it["height_cm"],
            "x": x,
            "layer": it["layer"],
            "why": it.get("why", ""),
        })
    if not items:
        raise ApiError(409, "E40902", "没有可用的植物组合",
                       hint="请放宽光照 / 宠物 / 预算约束后重试")

    import io
    with Image.open(photo_path) as base:
        try:
            canvas, items_meta, compose_warnings = compose_photo(
                base, items, assets["by_id"], px_per_cm, ground_y,
                bool(body.get("watermark", True)))
        except ValueError as e:
            raise ApiError(400, "E40001", str(e))
        except KeyError as e:
            raise ApiError(404, "E40403", "素材缺失：%s" % e.args[0])

    warnings.extend(compose_warnings)
    buf = io.BytesIO()
    canvas.save(buf, "PNG")
    name = _store().put_result(buf.getvalue())
    path = _store().result_path(name)
    expires = datetime.datetime.fromtimestamp(_store().expires_at(path))

    return jsonify(
        design={"source": plan["source"], "model": plan["model"],
                "llm_available": plan["llm_available"],
                "summary": plan["summary"], "elapsed_ms": plan["elapsed_ms"]},
        features=plan["features"],
        plants=plants_out,
        score=plan["score"],
        image_url="/api/compose/%s" % name,
        width=canvas.size[0],
        height=canvas.size[1],
        items_meta=items_meta,
        warnings=warnings,
        expires_at=expires.isoformat(timespec="seconds"),
    )


# ---------------------------------------------------------------- AI 效果图

@api_bp.post("/api/generate")
def api_generate():
    """先合成初稿 + 植物 mask，再调通义万相做局部重绘；无 Key 退回初稿。"""
    body = _body()
    photo_id = body.get("photo_id", "")
    photo_path = _store().photo_path(photo_id)
    if not photo_path:
        raise ApiError(404, "E40401", "photo_id 不存在或已过期", field="photo_id")

    meta = _store().get_meta(photo_id)
    if meta is None or "usable" not in meta:
        raise ApiError(404, "E40401", "照片校验记录不存在或已过期，请重新上传",
                       field="photo_id")
    if meta["usable"] is False:
        raise ApiError(422, "E40003", "该照片未通过可用性校验，不能用于生成",
                       field="photo_id")

    from PIL import Image
    with Image.open(photo_path) as im:
        photo_w, photo_h = im.size

    warnings = []
    anchor = body.get("anchor")
    if anchor is None:
        px_per_cm = min(40.0, max(0.5, photo_h * 0.5 / 150.0))
        ground_y = round(photo_h * 0.85, 1)
        warnings.append("未提供 anchor，按默认比例生成（%.2f px/cm）" % px_per_cm)
    else:
        if not isinstance(anchor, dict):
            raise ApiError(400, "E40001", "anchor 应为对象", field="anchor")
        px_per_cm = _finite_number(anchor.get("px_per_cm"), "anchor.px_per_cm")
        ground_y = _finite_number(anchor.get("ground_y"), "anchor.ground_y")
        if not PX_PER_CM_RANGE[0] <= px_per_cm <= PX_PER_CM_RANGE[1]:
            raise ApiError(409, "E40901", "px_per_cm 超出合理范围", field="anchor")
        if not 0 < ground_y <= photo_h:
            raise ApiError(400, "E40001", "anchor.ground_y 超出照片范围",
                           field="anchor.ground_y")

    items = body.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_ITEMS:
        raise ApiError(400, "E40001", "items 应为 1~%d 株的数组" % MAX_ITEMS,
                       field="items")

    assets = load_assets(_repo_root())
    normalized = []
    for it in items:
        if not isinstance(it, dict):
            raise ApiError(400, "E40001", "items 中每项都应为对象", field="items")
        pid = it.get("plant_id")
        if not isinstance(pid, str):
            raise ApiError(400, "E40001", "plant_id 应为字符串", field="items")
        asset = assets["by_id"].get(pid)
        if asset is None:
            raise ApiError(404, "E40402", "植物不存在：%s" % pid, field="items")
        if not asset["available"]:
            raise ApiError(404, "E40403", "%s 的素材文件缺失或不可用" % pid, field="items")
        x = _finite_number(it.get("x"), "items[].x")
        if not 0 <= x <= photo_w:
            raise ApiError(400, "E40001", "items[].x 超出照片范围", field="items[].x")
        height_cm = it.get("height_cm")
        if height_cm is not None:
            height_cm = _finite_number(height_cm, "items[].height_cm")
            if height_cm <= 0:
                raise ApiError(400, "E40001", "height_cm 应大于 0", field="items[].height_cm")
        layer = it.get("layer", 0)
        if type(layer) is not int or layer < 0:
            raise ApiError(400, "E40001", "items[].layer 应为非负整数", field="items")
        normalized.append({"plant_id": pid, "x": x, "height_cm": height_cm, "layer": layer})

    with Image.open(photo_path) as base:
        png, source, items_meta, gen_warnings, elapsed, reason = generate_image(
            base, normalized, assets["by_id"], px_per_cm, ground_y,
            overrides=_image_cfg())
    warnings.extend(gen_warnings)

    import io
    with Image.open(io.BytesIO(png)) as out:
        out_w, out_h = out.size
    name = _store().put_result(png)
    path = _store().result_path(name)
    expires = datetime.datetime.fromtimestamp(_store().expires_at(path))

    return jsonify(
        image_url="/api/compose/%s" % name,
        source=source,
        width=out_w,
        height=out_h,
        items_meta=items_meta,
        warnings=warnings,
        elapsed_ms=elapsed,
        fallback_reason=reason,
        expires_at=expires.isoformat(timespec="seconds"),
    )


# ---------------------------------------------------------------- 对话

@api_bp.post("/api/chat")
def api_chat():
    """基于当前方案上下文的对话；无 Key 时走模板兜底。"""
    body = _body()
    message = str(body.get("message", "")).strip()
    if not message:
        raise ApiError(400, "E40001", "message 不能为空", field="message")
    if len(message) > 500:
        raise ApiError(400, "E40001", "message 过长（上限 500 字）", field="message")

    history = body.get("history") or []
    if not isinstance(history, list):
        raise ApiError(400, "E40001", "history 应为数组", field="history")
    history = [h for h in history if isinstance(h, dict)][-6:]

    plant_ids = body.get("plant_ids") or []
    context = {"scene": body.get("scene") if isinstance(body.get("scene"), dict) else {},
               "plants": [], "score": None}

    _, by_id = _get_plants()
    if isinstance(plant_ids, list):
        context["plants"] = [{"plant_id": pid, "name_cn": by_id[pid].name_cn}
                             for pid in plant_ids if pid in by_id][:6]
        if plant_ids:
            try:
                scene = _make_scene(body.get("scene") or {})
                combo = _make_combo(plant_ids)
                context["score"] = score_combo(combo, scene).as_dict()
            except (ApiError, ValueError, TypeError):
                pass

    t0 = time.time()
    result = chat_reply(message, history, context, llm_cfg=_llm_cfg())
    result["elapsed_ms"] = round((time.time() - t0) * 1000, 1)
    return jsonify(result)


@api_bp.get("/api/compose/<name>")
def compose_result(name: str):
    if not RESULT_NAME_RE.match(name):
        raise ApiError(404, "E40400", "结果文件名不合法")
    path = _store().result_path(name)
    if not path:
        raise ApiError(404, "E40401", "合成结果不存在或已过期")
    resp = send_file(path, mimetype="image/png")
    resp.headers["Cache-Control"] = "private, max-age=600"
    return resp


# ---------------------------------------------------------------- FR-05 / FR-07

def _tags_for(plant, asset) -> list:
    tags = [plant.leaf_size]
    if plant.light_level in ("L1", "L2"):
        tags.append("耐阴")
    if plant.form == "垂吊":
        tags.append("垂吊")
    if plant.pet_safe:
        tags.append("宠物友好")
    if plant.toxic == "toxic":
        tags.append("有毒")
    return tags


@api_bp.get("/api/plants")
def plants_panel():
    plants, _ = _get_plants()
    assets = load_assets(_repo_root())["by_id"]

    search = request.args.get("search", "").strip()
    tag = request.args.get("tag", "").strip()
    only_available = request.args.get("available") == "true"

    out = []
    for p in plants:
        asset = assets.get(p.plant_id, {})
        available = bool(asset.get("available"))
        if only_available and not available:
            continue
        tags = _tags_for(p, asset)
        if tag and tag not in tags:
            continue
        if search and search not in p.name_cn and \
                search.lower() not in p.name_latin.lower():
            continue
        out.append({
            "plant_id": p.plant_id,
            "name_cn": p.name_cn,
            "name_latin": p.name_latin,
            "height_range_cm": [p.height_min_cm, p.height_max_cm],
            "spread_cm": p.spread_cm,
            "difficulty": p.difficulty,
            "price_cny": p.price_cny,
            "tags": tags,
            "available": available,
            "kind": asset.get("kind", ""),
            "thumb_url": "/api/assets/%s/thumb" % p.plant_id,
            "image_url": "/api/assets/%s/image" % p.plant_id,
            "style_tags": p.style_tags,
            "pet_safe": p.pet_safe,
            "toxic": p.toxic,
        })
    return jsonify(count=len(out), plants=out)


@api_bp.get("/api/assets")
def assets_list():
    data = load_assets(_repo_root())
    if request.if_none_match.contains(data["etag"]):
        return "", 304, {"ETag": '"%s"' % data["etag"]}
    resp = jsonify(schema=data["schema"], count=data["counts"], items=data["items"])
    resp.headers["ETag"] = '"%s"' % data["etag"]
    resp.headers["Cache-Control"] = "public, max-age=300"
    return resp


@api_bp.get("/api/assets/<plant_id>/image")
def asset_image(plant_id: str):
    asset = load_assets(_repo_root())["by_id"].get(plant_id)
    if asset is None:
        raise ApiError(404, "E40402", "植物不存在：%s" % plant_id)
    if not asset["available"] or not asset.get("abs_path"):
        raise ApiError(404, "E40403", "素材文件缺失：%s" % plant_id)
    resp = send_file(asset["abs_path"], mimetype="image/png")
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


THUMB_HEIGHT = 256          # 面板缩略图高度（像素）


def _make_thumb(src_path: str):
    """把素材缩到 256px 高，按 alpha 裁掉透明边。"""
    from PIL import Image

    with Image.open(src_path) as src:
        im = src.convert("RGBA")
    bbox = im.getchannel("A").getbbox()
    if bbox:
        im = im.crop(bbox)
    w, h = im.size
    scale = THUMB_HEIGHT / float(h)
    return im.resize((max(1, int(round(w * scale))), THUMB_HEIGHT), Image.LANCZOS)


@api_bp.get("/api/assets/<plant_id>/thumb")
def asset_thumb(plant_id: str):
    """缩略图（256px 高，WebP 优先），落盘缓存到 .cache/thumbs/。

    原图单张 ~900KB，48 张面板首屏 40MB+；FR-07 要求点选 <200ms。
    """
    asset = load_assets(_repo_root())["by_id"].get(plant_id)
    if asset is None:
        raise ApiError(404, "E40402", "植物不存在：%s" % plant_id)
    if not asset["available"] or not asset.get("abs_path"):
        raise ApiError(404, "E40403", "素材文件缺失：%s" % plant_id)

    cache_dir = os.path.join(_repo_root(), ".cache", "thumbs")
    os.makedirs(cache_dir, exist_ok=True)
    stamp = int(os.path.getmtime(asset["abs_path"]))
    path = os.path.join(cache_dir, "%s_%dh_%d.webp"
                        % (plant_id, THUMB_HEIGHT, stamp))
    if not os.path.isfile(path):
        im = _make_thumb(asset["abs_path"])
        try:
            im.save(path, "WEBP", quality=82, method=4)
        except (KeyError, OSError):        # Pillow 未编 WebP 时退回 PNG
            path = path[:-5] + ".png"
            im.save(path, "PNG", optimize=True)

    resp = send_file(path, mimetype="image/webp" if path.endswith(".webp")
                     else "image/png")
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp
