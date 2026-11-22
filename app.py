# -*- coding: utf-8 -*-
"""植境 Verda 后端入口（D 角色交付物）

开发运行（仓库根目录）：
    python app.py                 # http://127.0.0.1:5000
    python app.py --mock         # mock 模式：/api/compose 返回原图，其余接口真实
    python app.py --port 8000

生产部署（Linux）：
    gunicorn -w 4 -b 127.0.0.1:8000 app:app    # 前面挂 nginx

接口契约见 docs/14_接口契约.md。
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from server import create_app                      # noqa: E402

app = create_app()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="植境 Verda 后端")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--mock", action="store_true",
                        help="mock 模式：合成返回原图，便于前端先行联调")
    args = parser.parse_args()

    app = create_app(mock=args.mock)
    print("植境 Verda 后端启动：%s:%d  mock=%s"
          % (args.host, args.port, args.mock))
    app.run(host=args.host, port=args.port, debug=False)
