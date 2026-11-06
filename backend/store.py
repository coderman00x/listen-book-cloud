"""JSON 原子持久化（books.json / settings.json）。

设计要点（见 docs/ARCHITECTURE.md 第 7 节）：
- 单用户本地应用、零原生依赖、人易读易调试，故选用 JSON 文件。
- 并发安全由「单一生成 worker + 同步原子写（temp 写后 rename）」保证。
- 所有写入都通过 _atomic_write_json，先写临时文件再 os.replace 原子替换，
  避免进程中断导致半截 JSON 损坏。
"""
from __future__ import annotations

import json
import os
import tempfile
from typing import List, Optional

from .config import BOOKS_JSON, SETTINGS_JSON
from .models import Book, Chapter, Settings


def _atomic_write_json(path: str, payload: object) -> None:
    """原子写 JSON：先写临时文件，再 rename 替换目标，避免半截写入。"""
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def _read_json(path: str, default: object) -> object:
    """读取 JSON；文件不存在或解析失败时返回 default。"""
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, OSError):
        return default


def save_book(book: Book) -> None:
    """新增或更新一本书（按 id 去重）。"""
    books: List[dict] = list(_read_json(BOOKS_JSON, []))
    books = [b for b in books if b.get("id") != book.id]
    books.append(book.model_dump(mode="json"))
    _atomic_write_json(BOOKS_JSON, books)


def get_book(book_id: str) -> Optional[Book]:
    """按 id 获取一本书；不存在返回 None。"""
    for raw in _read_json(BOOKS_JSON, []):
        if raw.get("id") == book_id:
            return _migrate_legacy(Book(**raw))
    return None


def list_books() -> List[Book]:
    """返回全部书籍（按存储顺序）。"""
    return [_migrate_legacy(Book(**raw)) for raw in _read_json(BOOKS_JSON, [])]


def _migrate_legacy(book: Book) -> Book:
    """旧数据惰性迁移（仅内存补全，不回写文件）。

    v1.0 遗留的 ``audio_rel_path``（单文件 ``audio/<id>.mp3``）且无 ``chapters``
    时，合成一个单章 Chapter，使播放/删除逻辑统一走 ``chapters`` 结构。
    """
    if book.chapters:
        if not book.chapter_count:
            book.chapter_count = len(book.chapters)
        return book
    if book.audio_rel_path:
        book.chapters = [
            Chapter(
                index=0,
                title=book.title or "全文",
                audio_rel_path=book.audio_rel_path,
            )
        ]
        book.chapter_count = 1
    return book


def delete_book(book_id: str) -> bool:
    """仅删除元数据（音频/文本副本的删除由调用方负责）。

    返回 True 表示确有记录被删除；否则 False。
    """
    books: List[dict] = list(_read_json(BOOKS_JSON, []))
    new_books = [b for b in books if b.get("id") != book_id]
    if len(new_books) == len(books):
        return False
    _atomic_write_json(BOOKS_JSON, new_books)
    return True


def save_settings(settings: Settings) -> None:
    """保存全局设置（原子写）。"""
    _atomic_write_json(SETTINGS_JSON, settings.model_dump(mode="json"))


def load_settings() -> Settings:
    """读取全局设置；无记录时返回默认设置。"""
    raw = _read_json(SETTINGS_JSON, {})
    if not raw:
        return Settings()
    return Settings(**raw)
