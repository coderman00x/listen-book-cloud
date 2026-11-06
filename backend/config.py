"""听书宝后端全局配置。

集中管理路径常量、服务端口、默认生成参数与中文音色目录。
v2.0 增量：新增标准 PORT / LISTENBOOK_DATA_DIR / LISTENBOOK_PUBLIC /
LISTENBOOK_PUBLIC_URL 四个环境变量（全部有默认值，默认行为完全不变）。
关键红线：本模块定义的 DATA_DIR / BOOKS_DIR / AUDIO_DIR 全部位于 app 自身目录内，
后端在任何路径下都只读写这些目录，**绝不访问用户原始 txt 的绝对路径**。
"""
from __future__ import annotations

import os
from pathlib import Path

# 项目根目录：backend/ 的上一级（即 listen-book/）
BASE_DIR: Path = Path(__file__).resolve().parent.parent

# app 自身数据目录（运行期生成，gitignore）
# v2.0：允许用 LISTENBOOK_DATA_DIR 指向挂载卷（仍是 app 自身数据目录，红线不变），
# 未设置/为空时完全保持原来的 BASE_DIR / "data"。以下派生常量会自动跟随。
DATA_DIR: Path = Path(os.environ.get("LISTENBOOK_DATA_DIR") or (BASE_DIR / "data"))
BOOKS_DIR: Path = DATA_DIR / "books"          # 文本副本：<id>.txt
AUDIO_DIR: Path = DATA_DIR / "audio"          # 音频：<id>.mp3
EXPORT_DIR: Path = DATA_DIR / "export"        # 整本合并导出缓存：<id>.mp3

BOOKS_JSON: Path = DATA_DIR / "books.json"    # 书籍元数据（Book 数组）
SETTINGS_JSON: Path = DATA_DIR / "settings.json"  # 全局默认设置

# 服务监听（v1.3 增量：默认监听所有网卡，支持局域网/手机访问）
HOST: str = os.environ.get("LISTENBOOK_HOST", "0.0.0.0")
# v2.0：优先读云平台标准 PORT（Render / Cloud Run / HF 均注入），回退旧 LISTENBOOK_PORT
PORT: int = int(os.environ.get("PORT") or os.environ.get("LISTENBOOK_PORT") or 8000)

# v1.3 增量：可选访问口令；空字符串 = 不启用。
# 统一环境变量名为 ACCESS_TOKEN（与架构一致；PRD 的 LISTENBOOK_TOKEN 以本实现为准）。
ACCESS_TOKEN: str = os.environ.get("ACCESS_TOKEN", "")

# v1.3 增量：显式指定局域网地址（多网卡/VPN/容器桥接/NAT 兜底）。空 = 自动探测。
LAN_IP: str = os.environ.get("LISTENBOOK_LAN_IP", "")

# v2.0 增量：公网部署开关。开启后不向前端暴露容器内网 IP，改显示公网 HTTPS 地址。
PUBLIC_MODE: bool = os.environ.get("LISTENBOOK_PUBLIC", "0").lower() in ("1", "true", "yes", "on")

# v2.0 增量：公网地址（展示用，去除结尾斜杠）；空 = 前端回退当前页面地址。
PUBLIC_URL: str = os.environ.get("LISTENBOOK_PUBLIC_URL", "").rstrip("/")

# 长文分片大小（字符）。优先在换行/句号处断开。
CHUNK_SIZE: int = 2000

# 生成并发上限（有限并发，避免 edge-tts 限流）
MAX_CONCURRENCY: int = 2

# 默认生成参数（新导入书籍套用，可被设置面板覆盖）
DEFAULT_VOICE: str = "zh-CN-XiaoxiaoNeural"
DEFAULT_RATE: str = "+0%"

# 中文音色目录（与 docs/ARCHITECTURE.md 第 3.3 节 /api/voices 对齐）
VOICES: list[dict] = [
    {"id": "zh-CN-XiaoxiaoNeural", "name": "晓晓（女声）", "gender": "female", "locale": "zh-CN"},
    {"id": "zh-CN-XiaoyiNeural", "name": "晓伊（女声）", "gender": "female", "locale": "zh-CN"},
    {"id": "zh-CN-XiaochenNeural", "name": "晓辰（女声）", "gender": "female", "locale": "zh-CN"},
    {"id": "zh-CN-YunyangNeural", "name": "云扬（男声）", "gender": "male", "locale": "zh-CN"},
    {"id": "zh-CN-YunxiNeural", "name": "云希（男声）", "gender": "male", "locale": "zh-CN"},
]


def ensure_dirs() -> None:
    """确保 app 数据目录存在（幂等，可重复调用）。"""
    BOOKS_DIR.mkdir(parents=True, exist_ok=True)
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)  # 新增：整本导出缓存目录
