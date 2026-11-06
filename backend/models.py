"""听书宝数据模型（pydantic v2）。

包含：
- ``BookStatus``：生成状态枚举（pending / generating / done / failed）
- ``Book``：单本书籍元数据
- ``Settings``：全局默认设置（默认音色 / 默认语速）
- ``ApiResponse``：统一响应包装 ``{code, data, message}``

注意：``original_path`` 字段**仅记录上传时的文件名（basename）**用于展示与溯源，
后端绝不据此访问文件系统（原始文件红线）。
"""
from __future__ import annotations

import time
from enum import Enum
from typing import Any, List, Optional

from pydantic import BaseModel, Field

from .config import DEFAULT_RATE, DEFAULT_VOICE


class BookStatus(str, Enum):
    """书籍生成状态枚举（值即存储/传输用的字符串）。"""

    PENDING = "pending"        # 已登记，排队等待生成
    GENERATING = "generating"  # 生成中
    DONE = "done"              # 生成完成，可播放
    FAILED = "failed"          # 生成失败


def _now_iso() -> str:
    """返回 ISO8601 UTC 时间戳字符串。"""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Chapter(BaseModel):
    """单章音频元数据（按章播放/跳转的最小单元，index 从 0 起）。

    仅描述 app 内数据，不持有原始文本；生成期由 ``queue._process`` 回填时长与大小。
    """

    index: int                                          # 章节序号，从 0 起且连续
    title: str = "全文"                                 # 章节标题（取自检测到的标题；兜底为书名/「全文」）
    audio_rel_path: str = ""                            # app 内相对路径，如 "audio/<book_id>/<idx>.mp3"
    duration_sec: Optional[float] = None                # 该章音频时长（秒）
    size_bytes: Optional[int] = None                    # 该章 mp3 字节数


class PlaybackPosition(BaseModel):
    """断点续听位置（随 Book 持久化于 books.json）。"""

    current_chapter: int = 0       # 当前章节索引（0-based），默认第 0 章
    current_time: float = 0.0      # 章内秒数，默认 0s


class Bookmark(BaseModel):
    """手动书签（随 Book 持久化）。"""

    id: str                        # uuid hex
    chapter: int                   # 书签所在章（0-based）
    time: float                    # 章内秒数
    label: str = ""                # 用户自定义标题
    created_at: float = Field(default_factory=time.time)  # 创建时间（time.time() 秒级浮点）


class Book(BaseModel):
    """单本书籍元数据。

    所有字段与 docs/ARCHITECTURE.md 第 3.1 节严格对齐；
    v1.1 增量字段（format/chapters/chapter_count/text_rel_path）带默认值，
    保证旧 ``books.json`` 反序列化不报错。``audio_rel_path`` 保留但已 deprecated，
    仅用于 v1.0 旧数据惰性迁移，新书不再写入（唯一音频来源是 ``chapters``）。
    """

    id: str                                          # 书籍唯一标识（uuid hex）
    title: str                                       # 书名（取 txt 文件名去扩展名）
    original_path: str = ""                          # 仅记录上传文件名(basename)，绝不访问文件系统
    status: BookStatus = BookStatus.PENDING          # 生成状态
    voice: str = DEFAULT_VOICE                       # 音色 id
    rate: str = DEFAULT_RATE                         # 生成语速字符串，如 "+0%"
    duration_sec: Optional[float] = None             # 音频总时长（秒，各章求和）
    size_bytes: Optional[int] = None                 # 音频总大小（字节，各章求和）
    progress: int = 0                                # 生成进度百分比 0-100
    error: Optional[str] = None                      # 失败原因
    char_count: Optional[int] = None                 # 文本字数
    audio_rel_path: str = ""                         # [deprecated] 仅 v1.0 旧数据迁移用，新书不写

    # ---- v1.1 增量字段（分章）----
    format: str = "txt"                              # 来源格式：txt / epub / pdf
    chapters: List[Chapter] = Field(default_factory=list)  # 唯一音频来源（始终非空）
    chapter_count: int = 0                           # len(chapters) 冗余快照，便于卡片直显
    text_rel_path: str = ""                          # 文本副本相对路径，如 "books/<id>.txt"

    # ---- v1.2 增量字段（断点续听 / 书签）----
    playback: PlaybackPosition = Field(default_factory=PlaybackPosition)
    bookmarks: List[Bookmark] = Field(default_factory=list)

    created_at: str = Field(default_factory=_now_iso)   # 创建时间
    updated_at: str = Field(default_factory=_now_iso)   # 最近更新时间

    def touch(self) -> None:
        """刷新 updated_at 为当前时间。"""
        self.updated_at = _now_iso()


class Settings(BaseModel):
    """全局默认设置（新导入书籍套用）。"""

    default_voice: str = DEFAULT_VOICE
    default_rate: str = DEFAULT_RATE


class ApiResponse(BaseModel):
    """统一响应包装。

    - code == 0 表示成功；非 0 为业务错误码。
    - data 为业务数据，失败时为 None。
    - message 为可读提示。
    """

    code: int = 0
    data: Any = None
    message: str = "ok"
