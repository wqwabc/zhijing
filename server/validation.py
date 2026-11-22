# -*- coding: utf-8 -*-
"""FR-01 照片可用性校验

五个检查（对应验收的 5 类测试图）：
    resolution  长边 >= 1200px
    blur        拉普拉斯方差（越小越模糊）
    brightness  平均亮度（过暗 / 过亮）
    exposure    过曝像素占比（>=250 的比例）
    ground      画面下部 20% 的纹理方差（无地面 → 接近纯色）

阈值都集中在这里，方便 A 拿真实照片校准。
斜角检测是启发式（左右亮度不对称），只给 warning 不阻断（FR-01：不阻断流程）。
"""

import io

from PIL import Image, ImageFilter, ImageStat

MAX_BYTES = 10 * 1024 * 1024
MIN_LONG_SIDE = 1200

# ---- 可调阈值（默认值按常见手机照片经验设定，W2 用 A 的测试图校准）----
BLUR_VAR_MIN = 60.0          # 拉普拉斯方差下限
DARK_MEAN_MAX = 40.0         # 平均亮度上限（过暗）
BRIGHT_MEAN_MIN = 215.0      # 平均亮度下限（整体过亮）
OVEREXP_RATIO_MAX = 0.05     # 过曝像素比例上限
GROUND_STD_MIN = 7.0         # 下部纹理标准差下限（无地面判定）
SKEW_ASYM_MAX = 40.0         # 左右亮度不对称上限（斜角预警）

SUPPORTED_FORMATS = {"JPEG": "jpg", "PNG": "png"}

# 3x3 拉普拉斯核（锐度检测标准做法）
_LAPLACIAN = ImageFilter.Kernel((3, 3), (0, 1, 0, 1, -4, 1, 0, 1, 0), 1, 0)


class PhotoFormatError(ValueError):
    """格式不支持 / 超大小限制（对应 E40002）"""


def load_photo(data: bytes) -> Image.Image:
    """从字节流解析照片，失败抛 PhotoFormatError"""
    if len(data) > MAX_BYTES:
        raise PhotoFormatError("照片超过 10MB 上限")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        raise PhotoFormatError("无法解析的照片文件")
    if img.format not in SUPPORTED_FORMATS:
        raise PhotoFormatError("仅支持 JPG/PNG，收到 %s" % (img.format or "未知格式"))
    return img


def _gray_small(img: Image.Image, max_side: int = 512) -> Image.Image:
    """灰度 + 缩小，所有统计统一在 512px 上做（速度 + 阈值稳定）

    缩小必须用 LANCZOS：BICUBIC 无抗锯齿，强边缘下采样会产生振铃，
    会把模糊照片的拉普拉斯方差虚高到 200+，导致模糊检测失效。
    """
    gray = img.convert("L")
    w, h = gray.size
    if max(w, h) > max_side:
        ratio = max_side / max(w, h)
        gray = gray.resize((max(1, int(w * ratio)), max(1, int(h * ratio))),
                           Image.Resampling.LANCZOS)
    return gray


def check_resolution(img: Image.Image) -> dict:
    long_side = max(img.size)
    ok = long_side >= MIN_LONG_SIDE
    return {
        "name": "resolution",
        "pass": ok,
        "message": "长边 %dpx %s 1200px" % (long_side,
                                           ">=" if ok else "<"),
    }


def check_blur(img: Image.Image) -> dict:
    lap = _gray_small(img).filter(_LAPLACIAN)
    # PIL 的 Kernel 不处理图像边缘（边框像素保留原值），会把方差垫高
    # 出一个 ~155 的假底；统计前先裁掉 1px 边框。
    w, h = lap.size
    lap = lap.crop((1, 1, w - 1, h - 1))
    var = (ImageStat.Stat(lap).stddev[0] or 0.0) ** 2
    ok = var >= BLUR_VAR_MIN
    return {
        "name": "blur",
        "pass": ok,
        "message": "清晰度 %.1f（阈值 %.0f），%s"
                   % (var, BLUR_VAR_MIN, "画面清晰" if ok else "照片模糊"),
    }


def check_brightness(img: Image.Image) -> dict:
    mean = ImageStat.Stat(_gray_small(img)).mean[0]
    if mean < DARK_MEAN_MAX:
        ok, tip = False, "过暗"
    elif mean > BRIGHT_MEAN_MIN:
        ok, tip = False, "整体过亮"
    else:
        ok, tip = True, "正常"
    return {
        "name": "brightness",
        "pass": ok,
        "message": "平均亮度 %d/255，%s" % (round(mean), tip),
    }


def check_exposure(img: Image.Image) -> dict:
    hist = _gray_small(img).histogram()
    total = sum(hist)
    over = sum(hist[250:]) / total if total else 1.0
    ok = over <= OVEREXP_RATIO_MAX
    return {
        "name": "exposure",
        "pass": ok,
        "message": "过曝像素占比 %.1f%%%s"
                   % (over * 100, "" if ok else "，高光细节丢失"),
    }


def check_ground(img: Image.Image) -> dict:
    """下部 20% 纹理检测：地面/地板必有纹理；纯色墙或天花板方差接近 0"""
    gray = _gray_small(img)
    w, h = gray.size
    bottom = gray.crop((0, int(h * 0.8), w, h))
    std = ImageStat.Stat(bottom).stddev[0] or 0.0
    ok = std >= GROUND_STD_MIN

    # 斜角启发式：下部左右两半亮度差大 → 疑似斜拍（只预警）
    left = bottom.crop((0, 0, w // 2, bottom.size[1]))
    right = bottom.crop((w // 2, 0, w, bottom.size[1]))
    asym = abs(ImageStat.Stat(left).mean[0] - ImageStat.Stat(right).mean[0])

    message = "画面下部纹理标准差 %.1f（阈值 %.0f）" % (std, GROUND_STD_MIN)
    warning = None
    if not ok:
        message += "，可能没拍到地面"
    elif asym > SKEW_ASYM_MAX:
        warning = ("画面左右明暗不对称（差 %d），疑似斜角拍摄，建议正对拍摄"
                   % round(asym))
    return {"name": "ground", "pass": ok, "message": message, "warning": warning}


def validate_photo(img: Image.Image) -> dict:
    """跑全部检查，汇总为契约里的响应结构（docs/14 第 3 节）"""
    checks = [check_resolution(img), check_blur(img),
              check_brightness(img), check_exposure(img), check_ground(img)]

    warnings = []
    for c in checks:
        w = c.pop("warning", None)
        if w:
            warnings.append(w)
    failed = [c["name"] for c in checks if not c["pass"]]
    usable = not failed

    suggestion = ""
    if "resolution" in failed:
        suggestion = "分辨率不足，请用原图上传（长边至少 1200px）"
    elif "blur" in failed:
        suggestion = "照片模糊，建议擦净镜头、对焦后重拍"
    elif "brightness" in failed or "exposure" in failed:
        suggestion = "光线不佳，建议面向窗户重拍；或改用立面模式"
    elif "ground" in failed:
        suggestion = "画面里看不到地面，建议把地面拍进来；或改用立面模式"

    return {
        "usable": usable,
        "checks": checks,
        "warnings": warnings,
        "suggestion": suggestion,
    }
