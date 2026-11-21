# -*- coding: utf-8 -*-
"""FR-01 照片校验单元测试（纯函数，不依赖 Flask）

跑法（仓库根目录，需要 Pillow）：
    python -m unittest discover -s tests -p test_upload.py -v

对照验收 AC-01 的 5 类测试图：正常 / 过暗 / 模糊 / 无地面 / 低分辨率。
"""

import io
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from server import validation as V


def _noise(w=1300, h=900, sigma=45):
    """模拟正常室内照：全图带纹理噪声"""
    return Image.effect_noise((w, h), sigma).convert("RGB")


def _dark(w=1300, h=900):
    """过暗：噪声整体压暗到 15%"""
    return Image.effect_noise((w, h), 40).point(lambda v: v * 0.15).convert("RGB")


def _photo_like(w=1300, h=900):
    """模拟真实室内照：地板缝 + 沙发 + 门 + 传感器噪声"""
    img = Image.new("L", (w, h), 150)
    d = ImageDraw.Draw(img)
    floor = int(h * 0.72)
    for x in range(0, w, 60):
        d.line([(x, floor), (x, h)], fill=100, width=2)       # 地板竖缝
    for y in range(floor, h, 45):
        d.line([(0, y), (w, y)], fill=85, width=1)            # 地板横缝
    d.rectangle([180, int(h * 0.50), 620, floor], fill=70)    # 沙发
    d.rectangle([680, int(h * 0.25), 740, floor], fill=55)    # 门
    d.rectangle([800, int(h * 0.45), 900, int(h * 0.62)], fill=200)   # 抱枕
    noise = Image.effect_noise((w, h), 12)
    # effect_noise 均值 128，offset -128 把噪声中心拉回 0
    return ImageChops.add(img, noise, 1, -128).convert("RGB")


def _blurred(w=1300, h=900):
    """模糊：真实场景 + 传感器噪声 + 强高斯模糊（模拟手抖/失焦）"""
    return _photo_like(w, h).filter(
        ImageFilter.GaussianBlur(12)).convert("RGB")


def _no_ground(w=1300, h=900):
    """无地面：上部有纹理，下部 25% 是纯色（天花板/墙面入镜）"""
    img = Image.effect_noise((w, h), 40).convert("RGB")
    wall = Image.new("RGB", (w, h // 4), (200, 200, 200))
    img.paste(wall, (0, int(h * 0.75)))
    return img


def _tiny(w=800, h=600):
    """低分辨率"""
    return Image.effect_noise((w, h), 40).convert("RGB")


class TestPhotoFormat(unittest.TestCase):

    def test_jpeg_png_ok(self):
        for fmt in ("JPEG", "PNG"):
            buf = io.BytesIO()
            _noise(1300, 900).save(buf, fmt)
            img = V.load_photo(buf.getvalue())
            self.assertEqual(img.format, fmt)

    def test_unsupported_format(self):
        buf = io.BytesIO()
        _noise(1300, 900).save(buf, "BMP")
        with self.assertRaises(V.PhotoFormatError):
            V.load_photo(buf.getvalue())

    def test_garbage_bytes(self):
        with self.assertRaises(V.PhotoFormatError):
            V.load_photo(b"this is not an image at all")

    def test_oversize(self):
        with self.assertRaises(V.PhotoFormatError):
            V.load_photo(b"\x00" * (V.MAX_BYTES + 1))


class TestValidatePhoto(unittest.TestCase):
    """AC-01：5 类测试图全部正确处置"""

    def _names(self, result):
        return [c["name"] for c in result["checks"] if not c["pass"]]

    def test_normal_passes_all(self):
        result = V.validate_photo(_noise())
        self.assertTrue(result["usable"], result["suggestion"])
        self.assertEqual(self._names(result), [])
        self.assertEqual(result["suggestion"], "")

    def test_dark_rejected(self):
        result = V.validate_photo(_dark())
        self.assertFalse(result["usable"])
        self.assertIn("brightness", self._names(result))
        self.assertTrue(result["suggestion"], "过暗要给重拍建议")

    def test_blur_rejected(self):
        result = V.validate_photo(_blurred())
        self.assertFalse(result["usable"])
        self.assertIn("blur", self._names(result))

    def test_no_ground_rejected(self):
        result = V.validate_photo(_no_ground())
        self.assertFalse(result["usable"])
        self.assertIn("ground", self._names(result))

    def test_tiny_rejected(self):
        result = V.validate_photo(_tiny())
        self.assertFalse(result["usable"])
        self.assertIn("resolution", self._names(result))

    def test_every_check_has_message(self):
        for img in (_noise(), _dark(), _blurred(), _no_ground(), _tiny()):
            for c in V.validate_photo(img)["checks"]:
                self.assertTrue(c["message"], "每项检查都该有人话说明")


if __name__ == "__main__":
    unittest.main()
