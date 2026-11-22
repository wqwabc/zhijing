# -*- coding: utf-8 -*-
"""AI 效果图：mask 生成 + 无 Key 兜底 + mock 万相。"""

import io
import unittest
from unittest import mock

from PIL import Image

from server import create_app
from server.generate import build_mask
from server import generate as gen_mod


def _png(w=400, h=300, color=(180, 180, 175)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


class TestGenerate(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()
        self.store = self.app.extensions["verda_store"]
        self.photo_id = self.store.put_photo(_png(), "png")
        self.store.put_meta(self.photo_id, {"usable": True})
        self.body = {
            "photo_id": self.photo_id,
            "items": [{"plant_id": "P17", "x": 200, "height_cm": 120, "layer": 0}],
        }

    def test_mask_covers_bbox(self):
        meta = [{"bbox": [100, 80, 200, 220]}]
        mask = build_mask((400, 300), meta)
        self.assertEqual(mask.getpixel((150, 150)), 255)
        self.assertEqual(mask.getpixel((5, 5)), 0)

    def test_fallback_without_key(self):
        with mock.patch.object(gen_mod.wanx, "available", return_value=False), \
                mock.patch.object(gen_mod.wanx, "edit_image", return_value=None):
            r = self.client.post("/api/generate", json=self.body)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        data = r.get_json()
        self.assertEqual(data["source"], "local")
        self.assertTrue(data["image_url"])
        self.assertEqual(data["width"], 400)

    def test_wanx_path(self):
        with mock.patch.object(gen_mod.wanx, "available", return_value=True), \
                mock.patch.object(gen_mod.wanx, "edit_image", return_value=_png(600, 450, (200, 210, 200))):
            r = self.client.post("/api/generate", json=self.body)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        data = r.get_json()
        self.assertEqual(data["source"], "wanx")
        self.assertEqual(data["width"], 600)

    def test_missing_items(self):
        r = self.client.post("/api/generate", json={"photo_id": self.photo_id, "items": []})
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
