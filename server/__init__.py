# -*- coding: utf-8 -*-
"""植境 Verda 后端（D 角色交付物）

结构：
    server/__init__.py   应用工厂 create_app()
    server/store.py      照片与合成结果的临时存储（内存/临时目录，过期即删）
    server/validation.py FR-01 照片可用性校验（模糊/亮度/过曝/地面/分辨率）
    server/compose.py    FR-04 照片合成（等比缩放 + 贴地 + 接触阴影 + 水印）
    server/assets.py     FR-05 素材可用性清单（含 photo/illustration 区分）
    server/api.py        全部 HTTP 路由（契约见 docs/14_接口契约.md）

依赖：Flask、Pillow（见根目录 requirements.txt）。
"""

import os
import time

from flask import Flask, jsonify

from .api import api_bp
from .store import PhotoStore

BACKEND_VERSION = "1.0.0"
PHOTO_TTL_SECONDS = 30 * 60        # 照片与合成结果 30 分钟过期（合规：不长期存储）


def create_app(mock: bool = False) -> Flask:
    """应用工厂。

    :param mock: mock 模式下 /api/compose 返回原图 + 元数据，其余接口行为不变，
                 供 E 在合成实现完成前先行联调（docs/14 第 14 节）。
    """
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    repo_root = os.environ.get("VERDA_REPO_ROOT", repo_root)

    app = Flask(__name__)
    app.json.ensure_ascii = False          # 中文原样输出
    app.config.update(
        MOCK=mock,
        REPO_ROOT=repo_root,
        MAX_PHOTO_BYTES=10 * 1024 * 1024,
    )

    store = PhotoStore(ttl_seconds=PHOTO_TTL_SECONDS)
    store.start_cleanup()
    app.extensions["verda_store"] = store

    app.register_blueprint(api_bp)

    @app.after_request
    def _headers(resp):
        resp.headers["X-Verda-API-Version"] = "1"
        return resp

    @app.errorhandler(404)
    def _404(_e):
        return jsonify(error={"code": "E40400", "message": "接口不存在"}), 404

    @app.errorhandler(405)
    def _405(_e):
        return jsonify(error={"code": "E40500", "message": "方法不允许"}), 405

    @app.errorhandler(500)
    def _500(e):
        return jsonify(error={
            "code": "E50001",
            "message": "服务端内部错误",
            "hint": "请携带响应中的时间戳反馈给 D",
            "request_id": time.strftime("%Y%m%d%H%M%S"),
        }), 500

    return app
