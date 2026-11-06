"""整本合并导出（ffmpeg concat）。

职责（见 docs/ARCHITECTURE_INCREMENT2.md 第 3 节）：
- 仅读取 ``data/audio/<book_id>/<idx>.mp3``（分章副本，**零写入/零修改**分章文件）；
- 产物原子落盘到 ``data/export/<book_id>.mp3``（先写 ``.tmp.mp3`` 再 ``os.replace``）；
- 默认 ``-c copy`` 直拼（edge-tts 同书各章参数一致）；
- 若 copy 失败（返回非 0）回退重编码 ``libmp3lame``；
- ``subprocess`` 设 ``timeout=120`` 防卡死；
- 缺章 / 空文件立即抛清晰 ``ValueError``，由端点转 4xx。

红线：本模块绝不读取/修改用户原始 txt/epub/pdf，也不回写分章 mp3。
"""
from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import List, Sequence

from .config import AUDIO_DIR, EXPORT_DIR
from .models import Book, Chapter

# 文件名非法字符（含文件系统禁用符与 ASCII 控制字符 0x00-0x1f / DEL 0x7f）
_ILLEGAL_FS_CHARS = re.compile(r'[/\\:*?"<>|\x00-\x1f\x7f]')

# ffmpeg 探测：优先用系统 PATH，其次常见沙箱路径，再次环境变量覆盖
_FFMPEG = (
    os.environ.get("FFMPEG_BIN")
    or ("/usr/local/bin/ffmpeg" if os.path.exists("/usr/local/bin/ffmpeg") else "ffmpeg")
)


class MergeError(Exception):
    """合并失败（ffmpeg 异常 / 超时 / 产物非法）。"""


def ffmpeg_available() -> bool:
    """探测 ffmpeg 是否可用。"""
    try:
        proc = subprocess.run(
            [_FFMPEG, "-version"],
            timeout=10,
            capture_output=True,
        )
        return proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _resolve_chapter_paths(book_id: str, chapters: Sequence[Chapter]) -> List[Path]:
    """按章节 index 升序解析各章绝对路径；缺章/空文件抛清晰 ValueError。"""
    ordered = sorted(chapters, key=lambda c: c.index)
    paths: List[Path] = []
    for ch in ordered:
        p = AUDIO_DIR / book_id / f"{ch.index}.mp3"
        if not p.exists():
            raise ValueError(f"第 {ch.index} 章音频缺失（{p.name}），无法合并整本")
        if p.stat().st_size == 0:
            raise ValueError(f"第 {ch.index} 章音频为空文件（{p.name}），无法合并整本")
        paths.append(p)
    return paths


def _write_concat_list(paths: Sequence[Path], list_path: Path) -> None:
    """写 ffmpeg concat 列表：每行 ``file '<绝对路径>'``。"""
    with open(list_path, "w", encoding="utf-8") as handle:
        for p in paths:
            handle.write(f"file '{p.resolve()}'\n")


def _run_ffmpeg(list_path: Path, out_path: Path) -> None:
    """优先 copy 直拼；copy 失败（返回非 0）回退重编码 libmp3lame。

    超时 120s，任何 ffmpeg 异常/超时统一转换为 ``MergeError``（含清晰信息）。
    """
    # 1) copy 直拼（无损、最快，适用于同参数分章）
    try:
        proc = subprocess.run(
            [
                _FFMPEG,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_path),
                "-c",
                "copy",
                str(out_path),
            ],
            timeout=120,
            capture_output=True,
        )
    except subprocess.TimeoutExpired as exc:
        raise MergeError(f"ffmpeg 合并超时（>120s）：{exc}") from exc

    if proc.returncode == 0:
        return

    # 2) 回退重编码（统一转 48k mono mp3，避免 header 不一致导致爆音/拒播）
    try:
        proc2 = subprocess.run(
            [
                _FFMPEG,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_path),
                "-c:a",
                "libmp3lame",
                "-ar",
                "48000",
                "-ac",
                "1",
                "-b:a",
                "48k",
                str(out_path),
            ],
            timeout=120,
            capture_output=True,
        )
    except subprocess.TimeoutExpired as exc:
        raise MergeError(f"ffmpeg 合并超时（>120s）：{exc}") from exc

    if proc2.returncode != 0:
        stderr = (proc2.stderr or b"").decode("utf-8", "replace")[:500]
        raise MergeError(f"ffmpeg 合并失败：{stderr}")


def _merge_sync(book_id: str, chapters: Sequence[Chapter], force: bool = False) -> str:
    """同步合并实现（在线程池中执行，避免阻塞事件循环）。

    缓存命中条件（同时满足才直接返回现有产物，不重生成）：
      1. ``EXPORT_DIR/<book_id>.mp3`` 已存在；
      2. 章节数未变（所有分章文件均存在，len(paths)==len(chapters)）；
      3. 产物 mtime >= 所有分章文件 mtime（分章未被重新生成/覆盖）。
    ``force=True`` 显式绕过缓存命中判断（仍做缺章校验）。
    """
    if not chapters:
        raise ValueError("该书没有任何章节，无法合并整本")

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = EXPORT_DIR / f"{book_id}.mp3"
    tmp_path = EXPORT_DIR / f"{book_id}.tmp.mp3"

    # 解析各章路径（缺章立即抛错，不调用 ffmpeg）
    paths = _resolve_chapter_paths(book_id, chapters)

    # 缓存命中判断
    if not force and out_path.exists():
        out_mtime = out_path.stat().st_mtime
        all_sources_older = all(out_mtime >= p.stat().st_mtime for p in paths)
        if len(paths) == len(chapters) and all_sources_older:
            return str(out_path)

    # 合并（先写临时文件，成功后再原子替换，避免半成品被前端当作可下载）
    list_path = EXPORT_DIR / f"{book_id}.list.txt"
    _write_concat_list(paths, list_path)
    try:
        try:
            _run_ffmpeg(list_path, tmp_path)
        finally:
            if list_path.exists():
                list_path.unlink()  # 清理 concat 列表
        if not tmp_path.exists() or tmp_path.stat().st_size == 0:
            raise MergeError("ffmpeg 未产出有效音频文件")
        os.replace(tmp_path, out_path)  # 原子落盘
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()  # 清理半成品
        raise

    return str(out_path)


async def merge_book(
    book_id: str, chapters: Sequence[Chapter], force: bool = False
) -> str:
    """异步合并分章 mp3 为整本（在线程池执行阻塞的 ffmpeg 调用）。

    :param book_id: 书籍 id（音频位于 ``data/audio/<book_id>/``）
    :param chapters: 章节列表（按 index 升序合并）
    :param force: 是否强制重生成（绕过缓存命中）
    :return: 最终整本 mp3 的绝对路径字符串
    :raises ValueError: 缺章 / 空文件
    :raises MergeError: ffmpeg 失败 / 超时
    """
    import asyncio

    return await asyncio.to_thread(_merge_sync, book_id, chapters, force)


# 同步包装：供非 async 上下文（如单测）直接调用
def merge_book_sync(
    book_id: str, chapters: Sequence[Chapter], force: bool = False
) -> str:
    """同步合并（等价 ``_merge_sync``，供端点/单测直接调用）。"""
    return _merge_sync(book_id, chapters, force)


# ----------------------------------------------------------------------------
# v1.4 增量：分章 zip 导出（每章一个 mp3，手机听书可逐章跳转）
# ----------------------------------------------------------------------------
def _safe_filename(title: str, idx: int) -> str:
    """生成 zip 内安全的分章文件名（如 ``01 第一章.mp3``）。

    - 去除文件系统非法字符 ``/ \\ : * ? " < > |`` 及控制字符；
    - 折叠空白为单个空格并 strip；
    - 标题截断到约 60 字符避免过长；
    - 返回 ``f"{idx+1:02d} {title}.mp3"``（0-based 章索引用 01/02 前缀便于手机排序）。

    仅返回纯文件名（不含任何路径分隔符），杜绝 zip 路径穿越。
    """
    cleaned = _ILLEGAL_FS_CHARS.sub(" ", title or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > 60:
        cleaned = cleaned[:60].rstrip()
    if not cleaned:
        cleaned = f"第{idx + 1}章"
    return f"{idx + 1:02d} {cleaned}.mp3"


async def build_chapters_zip(book_id: str, chapters: Sequence[Chapter]) -> bytes:
    """异步打包分章 mp3 为 zip 字节（仅文件名，杜绝路径穿越）。

    复用 ``_resolve_chapter_paths`` 按 index 升序拿到各章路径；
    缺章 / 空文件会抛 ``ValueError``（由端点转 409）。

    :param book_id: 书籍 id（音频位于 ``data/audio/<book_id>/``）
    :param chapters: 章节列表（按 index 升序）
    :return: zip 归档的字节内容（application/zip）
    :raises ValueError: 缺章 / 空文件
    """
    import asyncio

    def _build_sync() -> bytes:
        # 缺章 / 空文件在此抛 ValueError（与整本合并保持一致）
        paths = _resolve_chapter_paths(book_id, chapters)
        ordered = sorted(chapters, key=lambda c: c.index)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for ch, p in zip(ordered, paths):
                # 仅写入纯文件名，绝不含路径分隔符（防 zip 路径穿越）
                zf.write(p, arcname=_safe_filename(ch.title, ch.index))
        return bytes(buf.getvalue())

    return await asyncio.to_thread(_build_sync)
