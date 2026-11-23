# -*- coding: utf-8 -*-
"""后端 HTTP 接口测试（Flask test client，不监听端口）

跑法（仓库根目录，需要 flask + pillow）：
    python -m unittest discover -s tests -p test_api.py -v

对照 docs/14_接口契约.md：上传 → 锚定 → 评分 → 推荐 → 合成 全链路。
"""

import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image

from server import create_app
from server.store import PhotoStore


def _jpg_bytes(w=1300, h=900, sigma=45):
    buf = io.BytesIO()
    Image.effect_noise((w, h), sigma).convert("RGB").save(buf, "JPEG", quality=80)
    return buf.getvalue()


def _dark_jpg_bytes(w=1300, h=900):
    buf = io.BytesIO()
    img = Image.effect_noise((w, h), 40).point(lambda v: v * 0.12).convert("RGB")
    img.save(buf, "JPEG", quality=80)
    return buf.getvalue()


SCENE = {"room": "living", "style": "nordic", "light": 2,
         "weekly_minutes": 30, "has_pet": True, "budget": 400}


class ApiTestBase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.store_dir = cls.tmpdir.name
        cls.app = create_app()
        cls.app.extensions["verda_store"] = PhotoStore(
            base_dir=cls.store_dir, ttl_seconds=1800)
        cls.client = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls.tmpdir.cleanup()

    def _upload(self, raw=None, name="photo.jpg"):
        raw = raw or _jpg_bytes()
        return self.client.post("/api/upload",
                                data={"photo": (io.BytesIO(raw), name)},
                                content_type="multipart/form-data")


class TestHealthAndMeta(ApiTestBase):

    def test_healthz(self):
        r = self.client.get("/healthz")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["status"], "ok")
        self.assertEqual(r.headers.get("X-Verda-API-Version"), "1")

    def test_404_shape(self):
        r = self.client.get("/api/nothing")
        self.assertEqual(r.status_code, 404)
        self.assertIn("error", r.get_json())


class TestUploadFlow(ApiTestBase):

    def test_upload_ok(self):
        r = self._upload()
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertTrue(body["usable"], body)
        self.assertRegex(body["photo_id"], r"^ph_[0-9a-f]{6,12}$")
        self.assertEqual(len(body["checks"]), 5)
        self.assertEqual((body["width"], body["height"]), (1300, 900))

    def test_upload_dark_rejected(self):
        r = self._upload(_dark_jpg_bytes())
        body = r.get_json()
        self.assertFalse(body["usable"])
        self.assertTrue(body["suggestion"])

    def test_upload_missing_field(self):
        r = self.client.post("/api/upload", data={},
                             content_type="multipart/form-data")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["error"]["code"], "E40001")

    def test_upload_bad_format(self):
        r = self._upload(b"garbage bytes here", name="photo.jpg")
        self.assertEqual(r.status_code, 415)
        self.assertEqual(r.get_json()["error"]["code"], "E40002")


class TestAnchorFlow(ApiTestBase):

    def _photo(self):
        r = self._upload()
        return r.get_json()["photo_id"]

    def test_anchor_math(self):
        photo_id = self._photo()
        # 门高 2.0m：两点竖直跨 1248px → px_per_cm = 6.24
        r = self.client.post("/api/anchor", json={
            "photo_id": photo_id,
            "ground": [{"x": 100, "y": 800}, {"x": 1200, "y": 810}],
            "ref": [{"x": 1000, "y": 800}, {"x": 1002, "y": -448}],
            "ref_type": "door",
        })
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertAlmostEqual(body["px_per_cm"], 6.24, delta=0.01)
        self.assertEqual(body["ref_height_cm"], 200.0)
        self.assertEqual(body["preview"]["suggest_px"], round(150 * 6.24))

    def test_anchor_unknown_photo(self):
        r = self.client.post("/api/anchor", json={
            "photo_id": "ph_000000",
            "ground": [{"x": 0, "y": 0}, {"x": 1, "y": 1}],
            "ref": [{"x": 0, "y": 0}, {"x": 1, "y": 500}],
            "ref_type": "door"})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.get_json()["error"]["code"], "E40401")

    def test_anchor_bad_ref_type(self):
        photo_id = self._photo()
        r = self.client.post("/api/anchor", json={
            "photo_id": photo_id,
            "ground": [{"x": 0, "y": 0}, {"x": 1, "y": 1}],
            "ref": [{"x": 0, "y": 0}, {"x": 1, "y": 500}],
            "ref_type": "window"})
        self.assertEqual(r.status_code, 400)

    def test_anchor_rejects_horizontal_height_reference(self):
        photo_id = self._photo()
        r = self.client.post("/api/anchor", json={
            "photo_id": photo_id,
            "ground": [{"x": 0, "y": 850}, {"x": 1000, "y": 850}],
            "ref": [{"x": 100, "y": 500}, {"x": 1100, "y": 500}],
            "ref_type": "door"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["error"]["field"], "ref")


class TestScoringEndpoints(ApiTestBase):

    def test_score_shape_matches_contract(self):
        r = self.client.post("/api/score", json={
            "plant_ids": ["P01", "P05", "P04"], "scene": SCENE})
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        for key in ("aesthetic", "fit", "total", "hard_flags",
                    "reasons", "dimensions"):
            self.assertIn(key, body)
        self.assertEqual(len(body["dimensions"]), 6)
        weights = [d["weight"] for d in body["dimensions"]]
        self.assertAlmostEqual(sum(weights), 1.0, delta=0.001,
                                msg="六个维度权重之和应为 1（docs/13）")

    def test_score_same_result_for_same_input(self):
        """AC-11 的服务端基础：同参数两次调用结果一致"""
        r1 = self.client.post("/api/score", json={
            "plant_ids": ["P01", "P05", "P04"], "scene": SCENE})
        r2 = self.client.post("/api/score", json={
            "plant_ids": ["P01", "P05", "P04"], "scene": SCENE})
        d1, d2 = r1.get_json(), r2.get_json()
        d1.pop("elapsed_ms", None), d2.pop("elapsed_ms", None)
        self.assertEqual(d1, d2)

    def test_score_unknown_plant(self):
        r = self.client.post("/api/score", json={
            "plant_ids": ["P99"], "scene": SCENE})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.get_json()["error"]["code"], "E40402")

    def test_score_bad_scene(self):
        r = self.client.post("/api/score", json={
            "plant_ids": ["P01"], "scene": {"room": "kitchen", "style": "nordic"}})
        self.assertEqual(r.status_code, 400)

    def test_has_pet_false_string_matches_boolean(self):
        scene = dict(SCENE, has_pet=False)
        expected = self.client.post("/api/score", json={
            "plant_ids": ["P01"], "scene": scene}).get_json()
        actual = self.client.post("/api/score", json={
            "plant_ids": ["P01"],
            "scene": dict(scene, has_pet="false")}).get_json()
        expected.pop("elapsed_ms", None)
        actual.pop("elapsed_ms", None)
        self.assertEqual(actual, expected)

    def test_recommend(self):
        r = self.client.post("/api/recommend", json={"scene": SCENE})
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertIn("plans", body)
        self.assertIn("jaccard", body)
        if not body.get("degraded"):
            self.assertEqual(len(body["plans"]), 3)
            for p in body["plans"]:
                self.assertIn("score", p)
                self.assertIn(p["personality"], ("稳妥", "对比", "个性"))

    def test_revise(self):
        r = self.client.post("/api/revise", json={
            "plant_ids": ["P01", "P05", "P04"],
            "scene": SCENE, "instruction": "更好养"})
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertTrue(body["supported"])
        self.assertIn("diff", body)


class TestAssetsEndpoints(ApiTestBase):

    def test_assets_counts(self):
        r = self.client.get("/api/assets")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["count"]["total"], 48)
        self.assertEqual(body["count"]["photo"], 25)
        self.assertEqual(body["count"]["illustration"], 23)
        for it in body["items"]:
            self.assertIn(it["kind"], ("photo", "illustration"))

    def test_assets_etag_304(self):
        r1 = self.client.get("/api/assets")
        etag = r1.headers["ETag"]
        r2 = self.client.get("/api/assets", headers={"If-None-Match": etag})
        self.assertEqual(r2.status_code, 304)

    def test_plants_panel(self):
        r = self.client.get("/api/plants")
        body = r.get_json()
        self.assertEqual(body["count"], 48)
        p01 = next(p for p in body["plants"] if p["plant_id"] == "P01")
        self.assertEqual(p01["name_cn"], "龟背竹")
        self.assertIn("大叶", p01["tags"])
        self.assertIn("有毒", p01["tags"])
        self.assertTrue(p01["available"])

    def test_plants_filter_available(self):
        r = self.client.get("/api/plants?available=true&tag=宠物友好")
        body = r.get_json()
        self.assertTrue(body["plants"])
        for p in body["plants"]:
            self.assertIn("宠物友好", p["tags"])

    def test_asset_image(self):
        r = self.client.get("/api/assets/P01/image")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["Content-Type"], "image/png")
        self.assertEqual(r.headers["Cache-Control"], "public, max-age=86400")

    def test_asset_image_missing(self):
        self.assertEqual(self.client.get("/api/assets/P99/image").status_code, 404)


class TestComposeEndpoint(ApiTestBase):

    def _anchor(self, px_per_cm=4.0, ground_y=850):
        photo_id = self._upload().get_json()["photo_id"]
        self.client.post("/api/anchor", json={
            "photo_id": photo_id,
            "ground": [{"x": 100, "y": ground_y}, {"x": 1000, "y": ground_y}],
            "ref": [{"x": 100, "y": ground_y},
                    {"x": 100, "y": ground_y - px_per_cm * 200}],
            "ref_type": "door"})
        return photo_id, px_per_cm, ground_y

    def test_compose_end_to_end(self):
        """上传 → 锚定 → 单株合成 → 取结果图，全链路走通（W1 交付判据）"""
        photo_id, px_per_cm, ground_y = self._anchor()
        r = self.client.post("/api/compose", json={
            "photo_id": photo_id,
            "anchor": {"px_per_cm": px_per_cm, "ground_y": ground_y},
            "items": [{"plant_id": "P01", "x": 650, "height_cm": 150}],
        })
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertIn("items_meta", body)
        self.assertEqual(body["items_meta"][0]["kind"], "photo")
        self.assertEqual(body["items_meta"][0]["actual_height_cm"], 150.0)
        self.assertEqual(body["items_meta"][0]["drawn_height_px"], 600)

        img = self.client.get(body["image_url"])
        self.assertEqual(img.status_code, 200)
        self.assertEqual(img.headers["Content-Type"], "image/png")

    def test_compose_reject_unusable_photo(self):
        """过暗照片不能合成（E40003）"""
        r = self._upload(_dark_jpg_bytes())
        photo_id = r.get_json()["photo_id"]
        r = self.client.post("/api/compose", json={
            "photo_id": photo_id,
            "anchor": {"px_per_cm": 4.0, "ground_y": 850},
            "items": [{"plant_id": "P01", "x": 650}]})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.get_json()["error"]["code"], "E40003")

    def test_compose_bad_anchor(self):
        photo_id = self._upload().get_json()["photo_id"]
        r = self.client.post("/api/compose", json={
            "photo_id": photo_id,
            "anchor": {"px_per_cm": 100.0, "ground_y": 850},
            "items": [{"plant_id": "P01", "x": 650}]})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.get_json()["error"]["code"], "E40901")

    def test_compose_too_many_plants(self):
        photo_id = self._upload().get_json()["photo_id"]
        items = [{"plant_id": "P01", "x": 100 + i * 100} for i in range(7)]
        r = self.client.post("/api/compose", json={
            "photo_id": photo_id,
            "anchor": {"px_per_cm": 4.0, "ground_y": 850},
            "items": items})
        self.assertEqual(r.status_code, 400)

    def test_compose_unknown_photo(self):
        r = self.client.post("/api/compose", json={
            "photo_id": "ph_000000",
            "anchor": {"px_per_cm": 4.0, "ground_y": 850},
            "items": [{"plant_id": "P01", "x": 650}]})
        self.assertEqual(r.status_code, 404)

    def test_compose_missing_validation_meta_fails_closed(self):
        photo_id = self._upload().get_json()["photo_id"]
        os.remove(os.path.join(self.store_dir, photo_id + ".meta.json"))
        r = self.client.post("/api/compose", json={
            "photo_id": photo_id,
            "anchor": {"px_per_cm": 4.0, "ground_y": 850},
            "items": [{"plant_id": "P01", "x": 650}]})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.get_json()["error"]["code"], "E40401")

    def test_compose_rejects_invalid_coordinates_and_types(self):
        photo_id = self._upload().get_json()["photo_id"]
        good = {"photo_id": photo_id,
                "anchor": {"px_per_cm": 4.0, "ground_y": 850},
                "items": [{"plant_id": "P01", "x": 650}]}
        bad = [
            dict(good, anchor=[]),
            dict(good, anchor={"px_per_cm": 4.0, "ground_y": 5000}),
            dict(good, items=[{"plant_id": "P01", "x": None}]),
            dict(good, items=[{"plant_id": "P01", "x": 650,
                               "height_cm": "150"}]),
            dict(good, items=[{"plant_id": "P01", "x": 650,
                               "layer": []}]),
        ]
        for payload in bad:
            with self.subTest(payload=payload):
                r = self.client.post("/api/compose", json=payload)
                self.assertEqual(r.status_code, 400, r.get_json())
                self.assertEqual(r.get_json()["error"]["code"], "E40001")


class TestCorsAndLimits(ApiTestBase):
    """E 用独立 dev server 联调时，缺 CORS 会被浏览器整片拦掉。"""

    ORIGIN = "http://localhost:5173"

    def test_preflight_allows_origin(self):
        r = self.client.options("/api/score", headers={
            "Origin": self.ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers.get("Access-Control-Allow-Origin"), self.ORIGIN)
        self.assertIn("POST", r.headers.get("Access-Control-Allow-Methods", ""))
        self.assertIn("ontent-type", r.headers.get("Access-Control-Allow-Headers", ""))

    def test_simple_request_has_cors(self):
        r = self.client.get("/healthz", headers={"Origin": self.ORIGIN})
        self.assertEqual(r.headers.get("Access-Control-Allow-Origin"), self.ORIGIN)

    def test_origin_whitelist_blocks_others(self):
        original = self.app.config["CORS_ORIGINS"]
        self.app.config["CORS_ORIGINS"] = ["http://ok.local"]
        try:
            r = self.client.get("/healthz", headers={"Origin": "http://evil.local"})
            self.assertIsNone(r.headers.get("Access-Control-Allow-Origin"))
            r = self.client.get("/healthz", headers={"Origin": "http://ok.local"})
            self.assertEqual(r.headers.get("Access-Control-Allow-Origin"),
                             "http://ok.local")
        finally:
            self.app.config["CORS_ORIGINS"] = original

    def test_body_too_large_returns_413(self):
        r = self.client.post("/api/upload", data=b"x" * (12 * 1024 * 1024),
                             content_type="multipart/form-data")
        self.assertEqual(r.status_code, 413)
        self.assertEqual(r.get_json()["error"]["code"], "E40002")


class TestThumbAndEdges(ApiTestBase):

    def test_thumb_is_small_and_cacheable(self):
        r = self.client.get("/api/assets/P01/thumb")
        self.assertEqual(r.status_code, 200)
        self.assertIn(r.mimetype, ("image/webp", "image/png"))
        self.assertLess(len(r.data), 150 * 1024, "缩略图应远小于原图")
        self.assertTrue(r.headers["Cache-Control"].startswith("public"))
        with Image.open(io.BytesIO(r.data)) as im:
            self.assertEqual(im.size[1], 256)

    def test_thumb_missing(self):
        self.assertEqual(self.client.get("/api/assets/P99/thumb").status_code, 404)

    def test_panel_uses_thumb_url(self):
        body = self.client.get("/api/plants").get_json()
        plant = body["plants"][0]
        self.assertTrue(plant["thumb_url"].endswith("/thumb"))
        self.assertTrue(plant["image_url"].endswith("/image"))

    def test_anchor_returns_ground_y_alias(self):
        photo_id = self._upload().get_json()["photo_id"]
        r = self.client.post("/api/anchor", json={
            "photo_id": photo_id,
            "ground": [{"x": 100, "y": 800}, {"x": 1200, "y": 810}],
            "ref": [{"x": 1000, "y": 800}, {"x": 1002, "y": -448}],
            "ref_type": "door"})
        body = r.get_json()
        self.assertIn("ground_y", body)
        self.assertEqual(body["ground_y"], body["ground_y_mid"])

    def test_has_pet_digit_strings(self):
        r = self.client.post("/api/score", json={
            "plant_ids": ["P01"], "scene": dict(SCENE, has_pet="0")})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["hard_flags"], [])
        r = self.client.post("/api/score", json={
            "plant_ids": ["P01"], "scene": dict(SCENE, has_pet="1")})
        self.assertTrue(r.get_json()["hard_flags"])

    def test_edge_plant_is_clipped_inside_canvas(self):
        photo_id = self._upload().get_json()["photo_id"]
        r = self.client.post("/api/compose", json={
            "photo_id": photo_id,
            "anchor": {"px_per_cm": 4.0, "ground_y": 850},
            "items": [{"plant_id": "P01", "x": 0}],
            "watermark": False})
        self.assertEqual(r.status_code, 200)
        meta = r.get_json()["items_meta"][0]
        self.assertTrue(meta["clipped"], "贴左边缘应标记 clipped")
        self.assertGreaterEqual(meta["bbox"][0], 0)
        self.assertLessEqual(meta["bbox"][2], 1300)
        self.assertGreater(meta["x_actual"], 0)


class TestMockMode(unittest.TestCase):
    """--mock 模式：合成返回原图 + meta，供 E 先行联调"""

    @classmethod
    def setUpClass(cls):
        cls.app = create_app(mock=True)
        cls.client = cls.app.test_client()

    def test_mock_compose(self):
        raw = _jpg_bytes()
        photo_id = self.client.post(
            "/api/upload",
            data={"photo": (io.BytesIO(raw), "p.jpg")},
            content_type="multipart/form-data").get_json()["photo_id"]
        r = self.client.post("/api/compose", json={
            "photo_id": photo_id,
            "anchor": {"px_per_cm": 4.0, "ground_y": 850},
            "items": [{"plant_id": "P01", "x": 650}]})
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertTrue(body["items_meta"][0]["mock"])
        # mock 模式返回的图与原图同尺寸
        img = self.client.get(body["image_url"])
        self.assertTrue(img.data.startswith(b"\x89PNG\r\n\x1a\n"))
        with Image.open(io.BytesIO(img.data)) as im:
            self.assertEqual(im.size, (1300, 900))


if __name__ == "__main__":
    unittest.main()
