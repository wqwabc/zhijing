# -*- coding: utf-8 -*-
"""大模型选株接口的单测：用 mock 代替真实 DeepSeek 调用。"""

import io
import unittest
from unittest import mock

from PIL import Image

from server import create_app
from server import llm as llm_mod


def _photo_bytes() -> bytes:
    im = Image.new("RGB", (800, 600), (212, 206, 196))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


class TestDesign(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()
        self.store = self.app.extensions["verda_store"]
        self.photo_id = self.store.put_photo(_photo_bytes(), "png")
        self.store.put_meta(self.photo_id, {"usable": True})
        self.body = {
            "photo_id": self.photo_id,
            "scene": {"room": "living", "style": "nordic", "light": 2,
                      "weekly_minutes": 30, "has_pet": False, "budget": 500},
            "count": 3,
            "anchor": {"px_per_cm": 3.0, "ground_y": 500},
        }

    def _proposal(self, *ids, summary="测试方案"):
        return {"plants": [{"plant_id": pid, "height_cm": 90,
                            "x_frac": 0.2 + 0.2 * i, "layer": 0, "why": "测试"}
                           for i, pid in enumerate(ids)],
                "summary": summary, "_model": "deepseek-chat"}

    def test_llm_selection(self):
        proposal = self._proposal("P17", "P05", "P16")
        with mock.patch.object(llm_mod, "available", return_value=True), \
                mock.patch.object(llm_mod, "plan_plants", return_value=proposal):
            r = self.client.post("/api/design", json=self.body)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        data = r.get_json()
        self.assertEqual(data["design"]["source"], "llm")
        self.assertEqual([p["plant_id"] for p in data["plants"]],
                         ["P17", "P05", "P16"])
        self.assertIn("score", data)
        self.assertIn("image_url", data)

    def test_pet_safe_filter(self):
        # P01 与 P05 有毒，只有 P17 安全；有宠物时应只剩 P17
        body = dict(self.body)
        body["scene"] = dict(self.body["scene"], has_pet=True)
        proposal = self._proposal("P01", "P05", "P17")
        with mock.patch.object(llm_mod, "available", return_value=True), \
                mock.patch.object(llm_mod, "plan_plants", return_value=proposal):
            r = self.client.post("/api/design", json=body)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        ids = [p["plant_id"] for p in r.get_json()["plants"]]
        self.assertEqual(ids, ["P17"])

    def test_fallback_when_no_key(self):
        with mock.patch.object(llm_mod, "available", return_value=False):
            r = self.client.post("/api/design", json=self.body)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        data = r.get_json()
        self.assertEqual(data["design"]["source"], "rules")
        self.assertTrue(data["plants"])
        self.assertLessEqual(len(data["plants"]), self.body["count"])

    def test_invalid_ids_fall_back(self):
        proposal = self._proposal("X99", "P999")
        with mock.patch.object(llm_mod, "available", return_value=True), \
                mock.patch.object(llm_mod, "plan_plants", return_value=proposal):
            r = self.client.post("/api/design", json=self.body)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual(r.get_json()["design"]["source"], "rules")

    def test_extract_json(self):
        text = '```json\n{"plants": [], "summary": "ok"}\n```'
        self.assertEqual(llm_mod.extract_json(text)["summary"], "ok")


if __name__ == "__main__":
    unittest.main()
