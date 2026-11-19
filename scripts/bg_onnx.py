# -*- coding: utf-8 -*-
"""U2Net 去底（onnxruntime 直跑，无需 rembg / opencv）。

模型：~/.u2net/u2net.onnx（rembg 同款，176MB）
下载：https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx
"""
from __future__ import annotations
import os
from pathlib import Path

import numpy as np
from PIL import Image

MODEL = Path(os.environ.get("U2NET_HOME", Path.home() / ".u2net")) / "u2net.onnx"
_session = None


def available() -> bool:
    return MODEL.exists() and MODEL.stat().st_size > 100 * 1024 * 1024


def _sess():
    global _session
    if _session is None:
        import onnxruntime as ort
        _session = ort.InferenceSession(str(MODEL), providers=["CPUExecutionProvider"])
    return _session


def remove(img: Image.Image, size: int = 320) -> Image.Image:
    """输入 PIL 图，返回带 alpha 的 RGBA。"""
    im = img.convert("RGB")
    w, h = im.size
    small = im.resize((size, size), Image.BILINEAR)
    x = np.asarray(small, dtype=np.float32) / 255.0
    x = (x - np.array([0.485, 0.456, 0.406], dtype=np.float32)) / np.array([0.229, 0.224, 0.225], dtype=np.float32)
    x = x.transpose(2, 0, 1)[None, ...]
    sess = _sess()
    pred = sess.run(None, {sess.get_inputs()[0].name: x.astype(np.float32)})[0][0, 0]
    pred = (pred - pred.min()) / (pred.max() - pred.min() + 1e-8)
    mask = Image.fromarray((pred * 255).astype(np.uint8)).resize((w, h), Image.BILINEAR)
    out = im.convert("RGBA")
    out.putalpha(mask)
    return out
