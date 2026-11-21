# -*- coding: utf-8 -*-
"""FR-04 合成引擎单元测试（纯函数，不依赖 Flask）

跑法（仓库根目录，需要 Pillow）：
    python -m unittest discover -s tests -p test_compose.py -v

覆盖：等比缩放精度（AC-02 的合成侧）、株高夹回真实区间（FR-07）、
落地位置、层级顺序、水印、参数边界。
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageDraw

from server.compose import (MAX_ITEMS, PX_PER_CM_RANGE, compose_photo,
                            _resolve_height_cm)


def _fake_plant_png(path, w=120, h=360):
    """画一株「假植物」：绿色矩形杆 + 顶部圆冠，带 alpha"""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([w // 2 - 4, h // 3, w // 2 + 4, h], fill=(101, 78, 60, 255))
    d.ellipse([4, 0, w - 4, h // 2], fill=(63, 107, 74, 255))
    img.save(path, "PNG")
    return img


class TestResolveHeight(unittest.TestCase):

    def test_default_is_mid(self):
        h, clamped = _resolve_height_cm(None, [80, 180])
        self.assertEqual(h, 130.0)
        self.assertFalse(clamped)

    def test_in_range_unchanged(self):
        h, clamped = _resolve_height_cm(150, [80, 180])
        self.assertEqual(h, 150.0)
        self.assertFalse(clamped)

    def test_over_is_clamped(self):
        h, clamped = _resolve_height_cm(400, [80, 180])
        self.assertEqual(h, 180.0)
        self.assertTrue(clamped)

    def test_under_is_clamped(self):
        h, clamped = _resolve_height_cm(20, [80, 180])
        self.assertEqual(h, 80.0)
        self.assertTrue(clamped)


class TestComposePhoto(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.plant_path = os.path.join(self.tmp.name, "PXX.png")
        self.src = _fake_plant_png(self.plant_path)     # 120 x 360
        self.assets = {"PXX": {
            "plant_id": "PXX", "name_cn": "测试绿植", "available": True,
            "kind": "photo", "abs_path": self.plant_path,
            "height_range_cm": [80, 180],
        }}
        self.base = Image.effect_noise((400, 600), 30).convert("RGB")

    def tearDown(self):
        self.tmp.cleanup()

    def _compose(self, items, **kw):
        return compose_photo(self.base, items, self.assets, **kw)

    def test_scale_precision_ac02(self):
        """AC-02 合成侧：150cm 株高误差 <= 10%"""
        px_per_cm = 2.0
        canvas, meta, _ = self._compose(
            [{"plant_id": "PXX", "x": 200, "height_cm": 150}],
            px_per_cm=px_per_cm, ground_y=550)
        self.assertEqual(meta[0]["drawn_height_px"], 300)     # 精确 150*2
        self.assertEqual(meta[0]["actual_height_cm"], 150.0)
        err = abs(meta[0]["drawn_height_px"] - 150 * px_per_cm) / (150 * px_per_cm)
        self.assertLessEqual(err, 0.10)

    def test_grounded_position(self):
        """底边必须贴在 ground_y 上，不允许「悬浮」"""
        canvas, meta, _ = self._compose(
            [{"plant_id": "PXX", "x": 200, "height_cm": 150}],
            px_per_cm=2.0, ground_y=550)
        x0, y0, x1, y1 = meta[0]["bbox"]
        self.assertEqual(y1, 550)                 # 贴地
        self.assertEqual(x0 + (x1 - x0) // 2, 200)  # 中轴线对准 x

    def test_transparent_padding_does_not_float(self):
        padded = Image.new("RGBA", (120, 420), (0, 0, 0, 0))
        padded.paste(self.src, (0, 0))
        padded.save(self.plant_path, "PNG")
        canvas, meta, _ = self._compose(
            [{"plant_id": "PXX", "x": 200, "height_cm": 150}],
            px_per_cm=2.0, ground_y=550, watermark=False)
        self.assertEqual(meta[0]["bbox"][3], 550)
        self.assertEqual(meta[0]["drawn_height_px"], 300)
        self.assertNotEqual(canvas.getpixel((200, 549)), self.base.getpixel((200, 549)))

    def test_aspect_ratio_kept(self):
        """等比缩放：宽高比与原图一致（120:360 = 1:3）"""
        canvas, meta, _ = self._compose(
            [{"plant_id": "PXX", "x": 200, "height_cm": 150}],
            px_per_cm=2.0, ground_y=550)
        x0, y0, x1, y1 = meta[0]["bbox"]
        ratio = (x1 - x0) / (y1 - y0)
        self.assertAlmostEqual(ratio, 120 / 360, delta=0.02)

    def test_plant_actually_drawn(self):
        """贴入区域确实变了色（不是只算了个坐标）"""
        canvas, _, _ = self._compose(
            [{"plant_id": "PXX", "x": 200, "height_cm": 150}],
            px_per_cm=2.0, ground_y=550)
        # 顶部圆冠中心 (200, 550-300+50=300) 应该偏绿
        r, g, b = canvas.getpixel((200, 320))[:3]
        self.assertGreater(g, r, "植物冠部像素应是绿色系")
        self.assertGreater(g, b)

    def test_shadow_added(self):
        """落地点下方有阴影（比无植物时更暗）"""
        clean = self.base.copy()
        canvas, meta, _ = self._compose(
            [{"plant_id": "PXX", "x": 200, "height_cm": 150}],
            px_per_cm=2.0, ground_y=550)
        # 阴影按盆宽生成，落在地面线以下；避开植物本体（底边=550）
        before = clean.getpixel((200, 553))[:3]
        after = canvas.getpixel((200, 553))[:3]
        self.assertLess(sum(after), sum(before),
                        "落地点下方应比原图暗（接触阴影）")
        self.assertEqual(canvas.getpixel((330, 553)), clean.getpixel((330, 553)),
                         "远离落地点不应有阴影")

    def test_multiple_plants_layer_order(self):
        """layer 0 最前：后画的（layer 小）在更晚落笔，遮挡前面的"""
        items = [
            {"plant_id": "PXX", "x": 100, "height_cm": 150, "layer": 2},
            {"plant_id": "PXX", "x": 100, "height_cm": 150, "layer": 0},
        ]
        canvas, meta, _ = self._compose(items, px_per_cm=2.0, ground_y=550)
        # 两株都在 x=100 重叠：layer 0 的绿冠应盖住 layer 2 的
        self.assertEqual(meta[0]["layer"], 2)   # 先画靠后的
        self.assertEqual(meta[1]["layer"], 0)

    def test_watermark_changes_corner(self):
        no_wm, _, _ = self._compose(
            [{"plant_id": "PXX", "x": 200, "height_cm": 150}],
            px_per_cm=2.0, ground_y=550, watermark=False)
        with_wm, _, _ = self._compose(
            [{"plant_id": "PXX", "x": 200, "height_cm": 150}],
            px_per_cm=2.0, ground_y=550, watermark=True)
        self.assertNotEqual(
            no_wm.getpixel((350, 570)), with_wm.getpixel((350, 570)),
            "右下角应有「效果示意」水印")

    def test_height_clamp_warning(self):
        canvas, meta, warnings = self._compose(
            [{"plant_id": "PXX", "x": 200, "height_cm": 500}],
            px_per_cm=2.0, ground_y=550)
        self.assertEqual(meta[0]["actual_height_cm"], 180.0)
        self.assertTrue(any("株高" in w for w in warnings),
                       "夹回区间要给出提示")

    def test_bad_px_per_cm(self):
        with self.assertRaises(ValueError):
            self._compose([{"plant_id": "PXX", "x": 200}],
                          px_per_cm=PX_PER_CM_RANGE[1] + 1, ground_y=550)

    def test_bad_items_count(self):
        for items in ([], [{"plant_id": "PXX", "x": 1}] * (MAX_ITEMS + 1)):
            with self.assertRaises(ValueError):
                self._compose(items, px_per_cm=2.0, ground_y=550)

    def test_unknown_plant(self):
        with self.assertRaises(KeyError):
            self._compose([{"plant_id": "P99", "x": 200}],
                          px_per_cm=2.0, ground_y=550)

    def test_edge_x_clipped_not_cut(self):
        """x 是中轴线，贴边时整株平移进画布，不允许半株出画"""
        canvas, meta, _ = self._compose(
            [{"plant_id": "PXX", "x": 0, "height_cm": 150}],
            px_per_cm=2.0, ground_y=550, watermark=False)
        m = meta[0]
        self.assertTrue(m["clipped"])
        self.assertGreaterEqual(m["bbox"][0], 0)
        self.assertLessEqual(m["bbox"][2], self.base.width)
        self.assertEqual(m["x_actual"],
                         m["bbox"][0] + (m["bbox"][2] - m["bbox"][0]) // 2)

    def test_contact_shadow_visible_and_decays(self):
        """阴影要落在地面线以下并随距离衰减，否则观感是「浮着」"""
        pot_path = os.path.join(self.tmp.name, "POT.png")
        img = Image.new("RGBA", (120, 360), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rectangle([30, 250, 90, 360], fill=(180, 180, 170, 255))   # 花盆
        d.rectangle([58, 60, 62, 260], fill=(80, 100, 60, 255))      # 茎
        d.ellipse([10, 0, 110, 140], fill=(60, 110, 70, 255))        # 冠
        img.save(pot_path, "PNG")
        assets = {"POT": {"plant_id": "POT", "name_cn": "测试", "available": True,
                          "kind": "photo", "abs_path": pot_path,
                          "height_range_cm": [80, 180]}}
        gray = Image.new("RGB", (400, 600), (200, 200, 200))
        canvas, meta, _ = compose_photo(
            gray, [{"plant_id": "POT", "x": 200, "height_cm": 150}],
            assets, 2.0, 550, watermark=False)

        def mean_at(y):
            x0, _, x1, _ = meta[0]["bbox"]
            xs = list(range(x0, x1, 4))
            return sum(canvas.getpixel((x, y))[0] for x in xs) / len(xs)

        self.assertLess(mean_at(554), 190, "地面线下方应有可见阴影")
        self.assertGreaterEqual(mean_at(596), mean_at(554), "阴影应随距离衰减")
        self.assertEqual(canvas.getpixel((3, 554))[0], 200, "盆两侧不应有阴影")


if __name__ == "__main__":
    unittest.main()
