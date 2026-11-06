"""文本提取模块（v1.1 增量）。

按扩展名从上传文件字节中提取纯文本：
- ``.txt``：直接 UTF-8 解码（容错替换非法字节）
- ``.epub``：zip 内 xhtml/html，用 BeautifulSoup 取可见正文（忽略 script/style/head）
- ``.pdf``：pypdf 逐页 ``extract_text`` 拼合；无文本层抛 ``ValueError``

所有解析都在内存字节上进行，**绝不访问用户磁盘上的原始文件**。
任何解析异常都转换为清晰的 ``ValueError``，供 API 转成业务错误而非崩溃。
"""
from __future__ import annotations

import io
import warnings
import zipfile
from typing import Dict, List, Optional

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

# 我们刻意使用内置 html.parser 解析 EPUB 的 XML 容器/OPF（避免引入 lxml 依赖），
# 此举会触发「XML 被当作 HTML 解析」的提醒，对简单标签查找无影响，故静默之。
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)


def extract_text(filename: str, data: bytes) -> str:
    """按扩展名提取纯文本。

    :param filename: 原始文件名（仅取扩展名判断格式）
    :param data: 文件字节内容（已在内存中，来自 multipart 上传）
    :return: 提取后的纯文本（已尽量去除多余空行）
    :raises ValueError: 不支持的格式或解析失败
    """
    if not filename:
        raise ValueError("缺少文件名，无法判断格式")
    lower = filename.lower()
    try:
        if lower.endswith(".txt"):
            return _extract_txt(data)
        if lower.endswith(".epub"):
            return _extract_epub(data)
        if lower.endswith(".pdf"):
            return _extract_pdf(data)
    except ValueError:
        # 业务错误直接向上抛
        raise
    except Exception as exc:  # noqa: BLE001 - 未知异常统一收敛为业务错误
        ext = lower.rsplit(".", 1)[-1]
        raise ValueError(f"{ext.upper()} 解析失败：{exc}") from exc
    raise ValueError("不支持的文件格式，仅支持 .txt / .epub / .pdf")


def _extract_txt(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _extract_epub(data: bytes) -> str:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError(f"EPUB 文件损坏或不是有效 zip：{exc}") from exc

    # 优先按 OPF spine 顺序读取，失败则退化为遍历所有 xhtml/html
    entries = _epub_spine_entries(zf) or [
        n for n in zf.namelist() if n.lower().endswith((".xhtml", ".html", ".htm"))
    ]
    if not entries:
        raise ValueError("EPUB 中未找到可读取的 xhtml/html 内容")

    parts: List[str] = []
    for name in entries:
        try:
            raw = zf.read(name)
        except Exception:  # noqa: BLE001
            continue
        text = _html_to_text(raw)
        if text:
            parts.append(text)
    zf.close()

    content = _collapse_blank_lines("\n\n".join(parts)).strip()
    if not content:
        raise ValueError("无法从 EPUB 提取到正文（可能是图片版）")
    return content


def _epub_spine_entries(zf: zipfile.ZipFile) -> List[str]:
    """解析 container.xml -> OPF -> spine，返回内容文件路径列表（按阅读顺序）。

    使用内置 ``html.parser``（无需 lxml 依赖）解析 XML 容器/OPF。
    """
    try:
        container = zf.read("META-INF/container.xml")
    except KeyError:
        return []
    root = BeautifulSoup(container, "html.parser")
    opf_path: Optional[str] = None
    for node in root.find_all("rootfile"):
        opf_path = node.get("full-path")
        if opf_path:
            break
    if not opf_path:
        return []

    try:
        opf = zf.read(opf_path)
    except KeyError:
        return []
    opf_root = BeautifulSoup(opf, "html.parser")

    manifest: Dict[str, str] = {}
    for item in opf_root.find_all("item"):
        item_id = item.get("id")
        href = item.get("href")
        if item_id and href:
            manifest[item_id] = href

    order = [
        manifest[ref.get("idref")]
        for ref in opf_root.find_all("itemref")
        if ref.get("idref") in manifest
    ]
    base = opf_path.rsplit("/", 1)[0] if "/" in opf_path else ""
    resolved: List[str] = []
    names = set(zf.namelist())
    for href in order:
        if not href:
            continue
        path = f"{base}/{href}" if base else href
        if path in names:
            resolved.append(path)
    return resolved


def _html_to_text(raw: bytes) -> str:
    try:
        soup = BeautifulSoup(raw.decode("utf-8", errors="replace"), "html.parser")
    except Exception:  # noqa: BLE001
        try:
            soup = BeautifulSoup(raw, "html.parser")
        except Exception:  # noqa: BLE001
            return ""
    # 忽略不可见 / 脚本内容
    for tag in soup(["script", "style", "head", "meta", "link"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    return _collapse_blank_lines(text)


def _extract_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise ValueError("服务端未安装 pypdf，无法解析 PDF") from exc
    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:
        raise ValueError(f"PDF 解析失败：{exc}") from exc

    parts: List[str] = []
    for page in reader.pages:
        try:
            page_text = page.extract_text() or ""
        except Exception:  # noqa: BLE001
            page_text = ""
        if page_text:
            parts.append(page_text)

    content = _collapse_blank_lines("\n".join(parts)).strip()
    if not content:
        raise ValueError("不支持扫描版（无文本层）PDF")
    return content


def _collapse_blank_lines(text: str) -> str:
    """去除多余空行（连续空行合并为一），并裁掉首尾空行。"""
    out: List[str] = []
    blank = 0
    for ln in text.splitlines():
        stripped = ln.rstrip()
        if stripped.strip() == "":
            blank += 1
            if blank <= 1:
                out.append("")
        else:
            blank = 0
            out.append(stripped)
    while out and out[0].strip() == "":
        out.pop(0)
    while out and out[-1].strip() == "":
        out.pop()
    return "\n".join(out)
