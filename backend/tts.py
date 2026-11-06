"""edge-tts 封装：按 voice/rate 生成、长文分片、顺序拼接落盘 mp3。

关键约束（见 docs/ARCHITECTURE.md 第 7 节）：
- 调用 ``edge_tts.Communicate(text, voice, rate=...)``，
  逐片 ``stream()``，只取 ``chunk["type"] == "audio"`` 的字节顺序写入同一 mp3。
- 同码率（edge-tts 默认 48kbps/mono）mp3 可直接顺序拼接，边界可能有极轻微爆音（v1 可接受）。
- 长文本按约 CHUNK_SIZE 字符在换行/句号处切分，避免截断半句话。
"""
from __future__ import annotations

import edge_tts
from typing import Callable, List, Optional

from .config import CHUNK_SIZE

# 断句优先使用的标点（句末优先于逗号，使切片更自然）
_SENTENCE_BREAKS = "。！？!?；;\n\r"
_SOFT_BREAKS = "，,、 "


def chunk_text(text: str, max_chars: int = CHUNK_SIZE) -> List[str]:
    """将长文本在换行/句末标点处切分为长度 <= max_chars 的分片。

    :param text: 完整文本
    :param max_chars: 单分片最大字符数
    :return: 分片列表（已去除首尾空白，非空）
    """
    text = text.strip()
    if not text:
        return []

    chunks: List[str] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + max_chars, length)
        if end < length:
            # 向前寻找最近的断句点：优先换行，其次句末标点，最后逗号等软断点
            cut = -1
            # 限定回溯窗口，避免极端长句导致切分过大
            look_back_from = max(start, end - 300)
            for i in range(end, look_back_from, -1):
                ch = text[i]
                if ch in "\n\r":
                    cut = i + 1
                    break
                if ch in "。！？!?；;":
                    cut = i + 1
                    break
            if cut <= start:
                for i in range(end, look_back_from, -1):
                    if text[i] in _SOFT_BREAKS:
                        cut = i + 1
                        break
            if cut <= start:
                cut = end  # 连续无断点，硬切
            end = cut

        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        start = end
    return chunks


async def generate(
    text: str,
    voice: str,
    rate: str,
    out_path: str,
    progress_cb: Optional[Callable[[int], None]] = None,
) -> int:
    """分片生成 mp3 并顺序追加写入 out_path。

    :param text: 完整文本
    :param voice: 音色 id，如 "zh-CN-XiaoxiaoNeural"
    :param rate: 语速字符串，如 "+0%" / "+20%" / "-30%"
    :param out_path: 输出 mp3 绝对路径
    :param progress_cb: 进度回调，参数为已完成的百分比（0-100），可空
    :return: 写入的音频总字节数
    """
    chunks = chunk_text(text)
    total = len(chunks)
    if total == 0:
        raise ValueError("空文本，无法生成音频")

    written = 0
    # 以二进制写模式打开，逐片顺序写入（同码率可直接拼接）
    with open(out_path, "wb") as handle:
        for idx, piece in enumerate(chunks):
            communicate = edge_tts.Communicate(piece, voice, rate=rate)
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    handle.write(chunk["data"])
            handle.flush()
            written = handle.tell()
            if progress_cb is not None:
                progress_cb(int((idx + 1) / total * 100))
    return written


def list_voices() -> List[dict]:
    """返回配置中的中文音色列表（与 /api/voices 对齐）。"""
    from .config import VOICES

    return [dict(v) for v in VOICES]
