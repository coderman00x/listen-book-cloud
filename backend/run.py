"""运行态入口：启动 uvicorn 并托管 frontend/dist 静态资源。

启动方式（二选一）：
    python backend/run.py            # 直接以脚本运行（本文件已注入项目根到 sys.path）
    python -m backend.run            # 以模块运行

前端需先 `cd frontend && npm run build` 产出 dist，后端即可在
http://127.0.0.1:8000 提供完整站点（开发态则用 vite dev server + proxy）。
"""
from __future__ import annotations

import os
import sys

# 项目根目录（listen-book/）
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 脚本自身所在目录（backend/）：直接 `python backend/run.py` 运行时，
# 该目录会被 Python 自动加入 sys.path[0]，导致标准库模块（如 queue）
# 被同名文件（backend/queue.py）遮蔽，进而使 uvicorn 启动失败。
# 因此先将其从 sys.path 移除，再注入项目根，确保 `backend` 作为包可正常导入。
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path = [p for p in sys.path if p != _THIS_DIR]
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import uvicorn  # noqa: E402

from backend.config import HOST, PORT  # noqa: E402


def main() -> None:
    """启动 uvicorn（挂载 backend.main:app）。"""
    uvicorn.run("backend.main:app", host=HOST, port=PORT, reload=False)


if __name__ == "__main__":
    main()
