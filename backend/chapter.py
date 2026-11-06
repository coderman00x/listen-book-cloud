"""章节检测模块（v1.1 增量）。

输入整篇文本 -> 输出章节切分结果。与 TTS / 队列解耦，便于单测。

检测规则（优先级从高到低，命中即作为章首）：
1. 中文「第X章 / 第X回 / 第X卷 / 第X节 / 第X部 / 第X篇」（含数字与中文数字）
2. 英文 ``Chapter N`` / ``CHAPTER N``
3. Markdown ``#`` / ``##`` 标题
4. 若以上均无，则整篇作为单个章节（title 取「全文」，由调用方按需替换为书名）

切分仅在「章首标题行」处进行，正文聚合到下一标题之前；空正文章节会被跳过。
"""
from __future__ import annotations

import re
from typing import Dict, List

from .models import Chapter

# 中文数字（覆盖到「千」，如 十二 / 三百 / 一千零五）
_CN_NUM = r"[0-9零一二三四五六七八九十百千]+"

# P1: 中文章回卷节部篇
_RE_CN_CHAPTER = re.compile(r"^\s*第" + _CN_NUM + r"[章回卷节部篇]\b")

# P2: 英文 Chapter（大小写不敏感）
_RE_EN_CHAPTER = re.compile(r"^\s*chapter\s+\d+\b", re.IGNORECASE)

# P3: Markdown 标题（1-6 个 #，捕获标题文本去掉 #）
_RE_MD_HEAD = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")


def _heading_info(line: str) -> tuple[bool, str]:
    """判断一行是否为章首标题，返回 (是否标题, 标题文本)。"""
    if _RE_CN_CHAPTER.match(line):
        return True, line.strip()
    if _RE_EN_CHAPTER.match(line):
        return True, line.strip()
    m = _RE_MD_HEAD.match(line)
    if m:
        return True, m.group(2).strip()
    return False, ""


def split_chapters(text: str) -> List[Dict[str, object]]:
    """将整篇文本切分为章节列表。

    :param text: 完整文本（可为空）
    :return: ``[{"index":0,"title":"...","text":"..."}, ...]``，至少返回 1 章，
             ``index`` 从 0 起且连续。
    """
    if text is None:
        text = ""

    lines = text.split("\n")
    heads: List[tuple[int, str]] = []  # (行号, 标题)
    for i, line in enumerate(lines):
        is_head, title = _heading_info(line)
        if is_head:
            heads.append((i, title))

    # 命中 >= 2 个章首才做按标题切分，否则整体作为单章
    if len(heads) >= 2:
        chapters: List[Dict[str, object]] = []
        for k, (line_idx, title) in enumerate(heads):
            start = line_idx + 1
            end = heads[k + 1][0] if k + 1 < len(heads) else len(lines)
            # 章首所在行全文计入本章正文（兼容"标题与正文同行"的提取文本）
            parts = [lines[line_idx]]
            if start < end:
                parts.append("\n".join(lines[start:end]))
            body = "\n".join(parts).strip()
            if not body:
                # 空正文章节跳过（避免空章、相邻标题合并）
                continue
            chapters.append(
                {
                    "index": len(chapters),
                    "title": title or f"第 {len(chapters) + 1} 章",
                    "text": body,
                }
            )
        if chapters:
            return chapters

    # 兜底：单章
    return [{"index": 0, "title": "全文", "text": text.strip()}]


def build_chapters(book_id: str, text: str) -> List[Chapter]:
    """``split_chapters`` 的封装：生成 ``Chapter`` 占位（填 index/title/audio_rel_path）。

    实际时长 / 大小在生成完成后由队列回填。
    """
    result: List[Chapter] = []
    for c in split_chapters(text):
        idx = int(c["index"])  # type: ignore[arg-type]
        result.append(
            Chapter(
                index=idx,
                title=str(c["title"]),
                audio_rel_path=f"audio/{book_id}/{idx}.mp3",
            )
        )
    return result
