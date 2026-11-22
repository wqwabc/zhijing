# -*- coding: utf-8 -*-
"""对话接口单测：模板兜底 + mock 模型回答。"""

import unittest
from unittest import mock

from server import create_app
from server import chat as chat_mod


class TestChat(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()
        self.body = {
            "message": "这套为什么这样搭？",
            "scene": {"room": "living", "style": "nordic", "light": 2,
                      "weekly_minutes": 30, "has_pet": False, "budget": 600},
            "plant_ids": ["P17", "P05", "P16"],
        }

    def test_fallback_without_key(self):
        with mock.patch.object(chat_mod.llm, "available", return_value=False):
            r = self.client.post("/api/chat", json=self.body)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        data = r.get_json()
        self.assertEqual(data["source"], "template")
        self.assertTrue(data["reply"])
        self.assertIn("分", data["reply"])

    def test_llm_reply(self):
        with mock.patch.object(chat_mod.llm, "available", return_value=True), \
                mock.patch.object(chat_mod.llm, "complete",
                                  return_value="因为窗边的明亮散射光更适合琴叶榕。"):
            r = self.client.post("/api/chat", json=self.body)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        data = r.get_json()
        self.assertEqual(data["source"], "llm")
        self.assertIn("琴叶榕", data["reply"])

    def test_empty_message(self):
        r = self.client.post("/api/chat", json={"message": "  "})
        self.assertEqual(r.status_code, 400)

    def test_bad_history(self):
        body = dict(self.body, history="not-a-list")
        r = self.client.post("/api/chat", json=body)
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
