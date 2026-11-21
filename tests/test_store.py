import os
import tempfile
import time
import unittest

from server.store import PhotoStore


class TestPhotoStoreTtl(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = PhotoStore(base_dir=self.tmp.name, ttl_seconds=10)

    def tearDown(self):
        self.store.stop_cleanup()
        self.tmp.cleanup()

    def test_expired_photo_and_result_cannot_be_revived(self):
        photo_id = self.store.put_photo(b"photo", "jpg")
        self.store.put_meta(photo_id, {"usable": False})
        result = self.store.put_result(b"result")
        old = time.time() - 11
        for name in (photo_id + ".jpg", photo_id + ".meta.json", result):
            os.utime(os.path.join(self.tmp.name, name), (old, old))

        self.assertIsNone(self.store.photo_path(photo_id))
        self.assertIsNone(self.store.get_meta(photo_id))
        self.assertIsNone(self.store.result_path(result))
        self.assertEqual(self.store.cleanup_expired(), 3)

    def test_active_photo_renews_validation_meta(self):
        photo_id = self.store.put_photo(b"photo", "jpg")
        self.store.put_meta(photo_id, {"usable": False})
        old = time.time() - 9
        for suffix in (".jpg", ".meta.json"):
            os.utime(os.path.join(self.tmp.name, photo_id + suffix), (old, old))

        self.assertIsNotNone(self.store.photo_path(photo_id))
        self.assertEqual(self.store.get_meta(photo_id), {"usable": False})
        self.assertEqual(self.store.cleanup_expired(now=time.time() + 2), 0)

    def test_background_cleanup_without_requests(self):
        self.store.ttl = 0.05
        self.store.start_cleanup(interval_seconds=0.02)
        photo_id = self.store.put_photo(b"photo", "jpg")
        path = os.path.join(self.tmp.name, photo_id + ".jpg")
        deadline = time.time() + 1
        while os.path.exists(path) and time.time() < deadline:
            time.sleep(0.02)
        self.assertFalse(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
