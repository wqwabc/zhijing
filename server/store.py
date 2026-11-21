# -*- coding: utf-8 -*-
"""照片与合成结果的临时存储（FR-01 合规：仅临时目录，过期即删）

- 照片 photo_id 形如 ``ph_8f3a1c``，合成结果 ``so_9d2f01.png``
- 存放于系统临时目录下的 verda_photos/，TTL 默认 30 分钟
- id 只允许 ``ph_/so_`` + 十六进制，杜绝路径穿越
- 每次访问会刷新过期时间（用户还在操作，就不删）
"""

import os
import re
import secrets
import tempfile
import threading
import time
from typing import Optional

PHOTO_ID_RE = re.compile(r"^ph_[0-9a-f]{6,12}$")
RESULT_NAME_RE = re.compile(r"^so_[0-9a-f]{6,12}\.png$")


class PhotoStore:

    def __init__(self, base_dir: str = None, ttl_seconds: int = 1800):
        self.base = base_dir or os.path.join(
            tempfile.gettempdir(), "verda_photos")
        self.ttl = ttl_seconds
        self._lock = threading.Lock()
        self._cleanup_thread = None
        self._cleanup_stop = threading.Event()
        os.makedirs(self.base, exist_ok=True)

    # ---- 写 ----

    def put_photo(self, data: bytes, ext: str) -> str:
        """保存上传照片，返回 photo_id"""
        photo_id = "ph_" + secrets.token_hex(4)
        path = os.path.join(self.base, photo_id + "." + ext)
        with self._lock:
            with open(path, "wb") as f:
                f.write(data)
            os.utime(path, None)
        return photo_id

    def put_result(self, data: bytes) -> str:
        """保存合成结果 PNG，返回文件名（so_xxx.png）"""
        name = "so_" + secrets.token_hex(4) + ".png"
        path = os.path.join(self.base, name)
        with self._lock:
            with open(path, "wb") as f:
                f.write(data)
            os.utime(path, None)
        return name

    # ---- 读 ----

    def _live_path(self, path: str, now: float) -> bool:
        try:
            if os.stat(path).st_mtime + self.ttl <= now:
                return False
            os.utime(path, (now, now))
            return True
        except OSError:
            return False

    def photo_path(self, photo_id: str) -> Optional[str]:
        """照片路径；不存在或已过期返回 None"""
        if not isinstance(photo_id, str) or not PHOTO_ID_RE.fullmatch(photo_id):
            return None
        with self._lock:
            now = time.time()
            for ext in ("jpg", "jpeg", "png"):
                path = os.path.join(self.base, photo_id + "." + ext)
                if self._live_path(path, now):
                    meta_path = os.path.join(self.base, photo_id + ".meta.json")
                    self._live_path(meta_path, now)
                    return path
        return None

    def result_path(self, name: str) -> Optional[str]:
        if not isinstance(name, str) or not RESULT_NAME_RE.fullmatch(name):
            return None
        path = os.path.join(self.base, name)
        with self._lock:
            if self._live_path(path, time.time()):
                return path
        return None

    def expires_at(self, path: str) -> float:
        """文件过期时间戳（= mtime + ttl）"""
        return os.path.getmtime(path) + self.ttl

    def put_meta(self, photo_id: str, meta: dict) -> None:
        """照片的校验结论等元数据，存 <photo_id>.meta.json"""
        import json
        path = os.path.join(self.base, photo_id + ".meta.json")
        with self._lock:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False)

    def get_meta(self, photo_id: str) -> Optional[dict]:
        import json
        if not isinstance(photo_id, str) or not PHOTO_ID_RE.fullmatch(photo_id):
            return None
        path = os.path.join(self.base, photo_id + ".meta.json")
        with self._lock:
            if not self._live_path(path, time.time()):
                return None
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, json.JSONDecodeError):
                return None

    # ---- 清理 ----

    def cleanup_expired(self, now: float = None) -> int:
        """删除过期文件，返回删除数量"""
        now = time.time() if now is None else now
        removed = 0
        with self._lock:
            try:
                names = os.listdir(self.base)
            except OSError:
                return 0
            for name in names:
                path = os.path.join(self.base, name)
                try:
                    if os.path.getmtime(path) + self.ttl <= now:
                        os.remove(path)
                        removed += 1
                except OSError:
                    continue
        return removed

    def start_cleanup(self, interval_seconds: int = 60) -> None:
        """在无请求时也定期清理过期文件。"""
        if self._cleanup_thread is not None:
            return
        self.cleanup_expired()

        def run():
            while not self._cleanup_stop.wait(interval_seconds):
                self.cleanup_expired()

        self._cleanup_thread = threading.Thread(target=run, daemon=True)
        self._cleanup_thread.start()

    def stop_cleanup(self) -> None:
        self._cleanup_stop.set()
        if self._cleanup_thread is not None:
            self._cleanup_thread.join(timeout=1)
