"""后台生成队列与 worker（单例模式）。

职责（见 docs/ARCHITECTURE.md 第 3.4 节 GenerationQueue）：
- ``enqueue(book_id)``：将一本书加入后台生成（若已在队列则忽略）。
- 有限并发（Semaphore，默认上限 2），避免 edge-tts 限流。
- 状态流转：pending -> generating -> done / failed。
- 通过内存进度 map 实时上报进度，并落盘元数据供轮询。
- 失败记录 error，便于前端展示与重试。

实现说明：生成任务通过 ``asyncio.create_task`` 挂到运行中的事件循环上，
由 uvicorn 的事件循环持续驱动，无需独立线程。任务引用保存在 ``_tasks`` 中防 GC。
"""
from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path
from typing import Dict, Optional

from . import chapter, tts
from .config import AUDIO_DIR, BOOKS_DIR, MAX_CONCURRENCY, ensure_dirs
from .models import Book, BookStatus
from .store import get_book, save_book


class GenerationQueue:
    """生成队列（单例）。"""

    def __init__(self) -> None:
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
        self._tasks: Dict[str, "asyncio.Task[None]"] = {}
        self._progress: Dict[str, int] = {}   # book_id -> 实时百分比
        self._lock = asyncio.Lock()

    async def enqueue(self, book_id: str) -> None:
        """将一本书加入生成队列（若已在运行则忽略）。

        必须在运行中的事件循环里调用（请求处理上下文中满足条件）。
        """
        async with self._lock:
            existing = self._tasks.get(book_id)
            if existing is not None and not existing.done():
                return
            self._tasks[book_id] = asyncio.create_task(self._run(book_id))

    async def _run(self, book_id: str) -> None:
        async with self._semaphore:
            await self._process(book_id)

    async def _process(self, book_id: str) -> None:
        ensure_dirs()
        book = get_book(book_id)
        if book is None:
            return

        # 进入生成中
        book.status = BookStatus.GENERATING
        book.progress = 0
        book.error = None
        self._progress[book_id] = 0
        self._touch_and_save(book)

        try:
            src_path = BOOKS_DIR / f"{book_id}.txt"
            if not src_path.exists():
                raise FileNotFoundError("源文本副本丢失，无法生成")

            full_text = src_path.read_text(encoding="utf-8", errors="replace")
            # 重新分章，保证与 Book.chapters 的顺序 / 索引一致
            split = chapter.split_chapters(full_text)
            total = len(split)
            if total == 0:
                raise ValueError("未切分出任何章节")

            book_dir = AUDIO_DIR / book_id
            book_dir.mkdir(parents=True, exist_ok=True)

            done = 0
            for piece in split:
                # 生成期间该书被删除：清理整个按章音频目录后退出，不复活、无孤儿
                if get_book(book_id) is None:
                    self._discard_deleted(book_id)
                    return

                idx = int(piece["index"])  # type: ignore[arg-type]
                chapter_text = str(piece["text"])
                if not chapter_text.strip():
                    done += 1
                    continue

                out_path = book_dir / f"{idx}.mp3"
                if out_path.exists():
                    out_path.unlink()  # 清掉旧音频，避免拼接脏数据

                def _make_cb(cur_done: int) -> "Callable[[int], None]":
                    def _cb(pct: int) -> None:
                        # 进度 = 已完成章占比 + 当前章内分片进度（按比例摊薄）
                        base = cur_done * 100 // total
                        within = pct // total
                        self._progress[book_id] = min(99, base + within)

                    return _cb

                written = await tts.generate(
                    text=chapter_text,
                    voice=book.voice,
                    rate=book.rate,
                    out_path=str(out_path),
                    progress_cb=_make_cb(done),
                )

                # 生成当前章后复查：若期间已被删除，清理目录并退出
                if get_book(book_id) is None:
                    self._discard_deleted(book_id)
                    return

                # 回填该章元数据（时长 / 大小）
                duration = self._estimate_duration(written)
                for ch in book.chapters:
                    if ch.index == idx:
                        ch.audio_rel_path = f"audio/{book_id}/{idx}.mp3"
                        ch.size_bytes = written
                        ch.duration_sec = duration
                        break
                # 持久化以便前端实时看到「某章完成」
                self._touch_and_save(book)
                done += 1
                self._progress[book_id] = max(
                    self._progress.get(book_id, 0), done * 100 // total
                )

            # 收尾前复查：生成期间该书被删除则不复活
            if get_book(book_id) is None:
                self._discard_deleted(book_id)
                return

            # 收尾：聚合全书时长/大小并标记完成
            book.status = BookStatus.DONE
            book.progress = 100
            total_dur = round(sum((c.duration_sec or 0) for c in book.chapters), 1)
            total_size = sum((c.size_bytes or 0) for c in book.chapters)
            book.duration_sec = total_dur or None
            book.size_bytes = total_size or None
            book.chapter_count = len(book.chapters)
            self._progress.pop(book_id, None)
            self._touch_and_save(book)

        except Exception as exc:  # noqa: BLE001 - 捕获所有异常以标记失败
            # 生成失败：若期间已被删除，同样不落盘、清理孤儿资源后退出。
            if get_book(book_id) is None:
                self._discard_deleted(book_id)
                return
            book.status = BookStatus.FAILED
            book.error = str(exc) or "生成失败"
            self._progress.pop(book_id, None)
            self._touch_and_save(book)

    def _discard_deleted(self, book_id: str) -> None:
        """书籍在生成期间被删除时的清理：移除整个按章音频目录（含所有 mp3）与内存进度。

        仅删除 app 自身目录内的 AUDIO_DIR/<book_id>/（存在才删），
        兼容清理旧单文件 AUDIO_DIR/<book_id>.mp3；
        绝不触碰用户原始文件；且不调用 save_book，避免把已删元数据复活回 books.json。
        """
        book_dir = AUDIO_DIR / book_id
        if book_dir.exists():
            shutil.rmtree(book_dir, ignore_errors=True)
        legacy = AUDIO_DIR / f"{book_id}.mp3"
        if legacy.exists():
            legacy.unlink()
        self._progress.pop(book_id, None)

    @staticmethod
    def _estimate_duration(size_bytes: int) -> float:
        """edge-tts 默认约 48kbps mono mp3：秒数 = 字节 / (48000/8)。"""
        return round(size_bytes / (48000.0 / 8), 1)

    def _touch_and_save(self, book: Book) -> None:
        book.touch()
        try:
            save_book(book)
        except Exception:  # noqa: BLE001 - 持久化失败不应中断生成流程
            pass

    def get_progress(self, book_id: str) -> Dict[str, object]:
        """返回进度查询结果（供 /api/books/{id}/progress 轮询）。

        生成中优先返回内存实时进度；其余情况返回元数据中的状态。
        """
        book = get_book(book_id)
        if book is None:
            return {"status": None, "progress": 0, "error": "not found"}
        status = book.status
        progress = book.progress
        if status == BookStatus.GENERATING and book_id in self._progress:
            progress = self._progress[book_id]
        return {
            "status": status.value,
            "progress": progress,
            "error": book.error,
        }


# 模块级单例（被 main.py 引用为 gen_queue.queue）
queue = GenerationQueue()
