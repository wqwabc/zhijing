# -*- coding: utf-8 -*-
"""落地线自动估计：合成图 + 接口。"""

import io
import unittest

from PIL import Image, ImageDraw

from server import create_app
from server.ground import detect_groundline


def _room_bytes(w=400, h=300, floor_ratio=0.80) -> bytes:
    im = Image.new("RGB", (w, h), (205, 203, 198))
    d = ImageDraw.Draw(im)
    top = int(h * floor_ratio)
    d.rectangle([0, top, w, h], fill=(135, 96, 58))
    for y in range(top, h, 6):
        d.line([0, y, w, y], fill=(120, 84, 50))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


class TestGroundline(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()
        self.store = self.app.extensions["verda_store"]

    def test_detect_synthetic(self):
        photo_id = self.store.put_photo(_room_bytes(), "png")
        r = self.client.post("/api/groundline", json={"photo_id": photo_id})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        data = r.get_json()
        self.assertAlmostEqual(data["ground_y"], 240, delta=20)
        self.assertGreaterEqual(data["confidence"], 0.3)
        self.assertEqual(len(data["points"]), 2)

    def test_fallback_uniform(self):
        im = Image.new("RGB", (300, 200), (180, 180, 180))
        buf = io.BytesIO()
        im.save(buf, "PNG")
        path = self.store.put_photo(buf.getvalue(), "png")
        data = detect_groundline(self.store.photo_path(path))
        self.assertEqual(data["method"], "fallback")
        self.assertAlmostEqual(data["ground_y"], 170, delta=3)

    def test_unknown_photo(self):
        r = self.client.post("/api/groundline", json={"photo_id": "ph_000000"})
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
