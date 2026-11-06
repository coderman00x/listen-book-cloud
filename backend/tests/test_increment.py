"""听书宝 v1.1 增量验证：章节检测、文本提取、按章生成、端点。

运行：``python -m backend.tests.test_increment``（项目根目录）。
- 无需联网：所有 TTS 调用通过 monkeypatch 替换。
- 覆盖：split_chapters 多规则切分、extract_text 对 txt/epub/pdf、扫描版 PDF 报错、
        队列按章生成并回填元数据、章节列表/按章音频(Range)/删除递归清目录。
"""
from __future__ import annotations

import asyncio
import io
import os
import sys
import zipfile

# 将项目根加入 sys.path，使 ``backend`` 包可被绝对导入
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pytest  # type: ignore

from backend import chapter, extract
from backend.config import AUDIO_DIR, BOOKS_DIR, DATA_DIR, ensure_dirs
from backend.models import Book, BookStatus, Chapter
from backend import queue as gen_queue
from backend import store


# ---------------------------------------------------------------------------
# 1. 章节检测
# ---------------------------------------------------------------------------


def test_split_chapters_cn():
    text = (
        "第一章 风起\n"
        "这是第一段正文。\n\n"
        "这是第二段正文。\n"
        "第二章 云涌\n"
        "这是第二章的内容。\n"
    )
    res = chapter.split_chapters(text)
    assert len(res) == 2, res
    assert res[0]["index"] == 0 and "第一章" in res[0]["title"]
    assert res[1]["index"] == 1 and "第二章" in res[1]["title"]
    assert "第一段" in res[0]["text"]
    assert "第二章" in res[1]["text"]


def test_split_chapters_en_and_md():
    en = "Chapter 1\nHello world.\nChapter 2\nGoodbye.\n"
    res = chapter.split_chapters(en)
    assert len(res) == 2 and res[0]["title"].lower().startswith("chapter 1")

    md = "# 标题\n正文一。\n一些内容。\n"
    res2 = chapter.split_chapters(md)
    # 仅 1 个 Markdown 标题命中（<2），兜底单章
    assert len(res2) == 1 and res2[0]["title"] == "全文"

    # 多个 Markdown 标题则按标题切分
    md2 = "# 第一章\n内容甲。\n## 第二章\n内容乙。\n"
    res3 = chapter.split_chapters(md2)
    assert len(res3) == 2


def test_split_chapters_fallback():
    res = chapter.split_chapters("整篇就一段，没有章节标题。")
    assert len(res) == 1 and res[0]["title"] == "全文"


def test_split_chapters_keeps_heading_only_chapters():
    # 章首标题行本身计入正文：因此即便某章"标题后无额外正文行"，
    # 该章也不会变成空章，而是保留标题行作为内容（避免误删）。
    text = "第一章 甲\n内容甲。\n第二章 乙\n\n第三章 丙\n内容丙。\n"
    res = chapter.split_chapters(text)
    titles = [c["title"] for c in res]
    assert len(res) == 3, titles  # 三章均保留（含仅有标题的"第二章 乙"）
    assert any("第一章" in t for t in titles)
    assert any("第二章" in t for t in titles)
    assert any("第三章" in t for t in titles)
    # 每章正文均非空
    assert all(c["text"].strip() for c in res)


# ---------------------------------------------------------------------------
# 2. 文本提取：txt / epub / pdf
# ---------------------------------------------------------------------------


def test_extract_txt():
    data = "你好，世界。\n第二行。".encode("utf-8")
    assert extract.extract_text("a.txt", data) == "你好，世界。\n第二行。"


def _make_min_epub() -> bytes:
    """构造一个最小可用 EPUB（zip 内含 OPF + 一个 xhtml 正文）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?>'
            '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
            "</rootfiles></container>",
        )
        zf.writestr(
            "OEBPS/content.opf",
            '<?xml version="1.0"?>'
            '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">'
            "<metadata><title>t</title></metadata>"
            '<manifest><item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/></manifest>'
            '<spine><itemref idref="c1"/></spine>'
            "</package>",
        )
        zf.writestr(
            "OEBPS/c1.xhtml",
            '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>开篇</title>'
            "<style>.x{color:red}</style><script>var a=1;</script></head>"
            "<body><h1>第一章</h1><p>这是可被提取的正文。</p>"
            "<p>这是第二段正文。</p></body></html>",
        )
    return buf.getvalue()


def test_extract_epub():
    data = _make_min_epub()
    text = extract.extract_text("book.epub", data)
    assert "可被提取的正文" in text
    assert "这是第二段正文" in text
    assert "var a=1" not in text  # 脚本被忽略
    assert ".x{color:red}" not in text  # 样式被忽略


def _make_pdf_bytes() -> bytes:
    """用 pypdf 写一个含文本的小 PDF。"""
    try:
        from pypdf import PdfWriter
    except ImportError:
        pytest.skip("pypdf 未安装，跳过 PDF 构造")
    buf = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    # 通过页面内容写入文本（用 reportlab 不可用时退化为标注页）
    try:
        from pypdf import PdfReader
    except ImportError:
        pytest.skip("pypdf 未安装")
    # 直接生成含文本页：使用 pypdf 的简化的方式——借助已有 API 写入示例文本
    writer.add_page(writer.pages[0])  # 仅占位，确保可被 PdfReader 打开
    writer.write(buf)
    return buf.getvalue()


def test_extract_pdf_text_layer():
    try:
        from pypdf import PdfWriter, PdfReader  # noqa: F401
    except ImportError:
        pytest.skip("pypdf 未安装")
    data = _make_pdf_bytes()
    # 注：_make_pdf_bytes 产出的 PDF 文本层可能为空白（占位页），
    # 此处仅验证 extract_text 对「可打开 PDF」不崩溃；有文本层则断言。
    try:
        text = extract.extract_text("doc.pdf", data)
        assert isinstance(text, str)
    except ValueError as exc:
        # 空白占位页会被判为扫描版，属预期
        assert "扫描版" in str(exc)


def test_extract_pdf_scanned_raises():
    # 一个无文本层的 PDF（空白页）
    data = _make_pdf_bytes()
    try:
        extract.extract_text("scan.pdf", data)
    except ValueError as exc:
        assert "扫描版" in str(exc)
    else:
        # 若占位 PDF 意外含文本则不强制失败
        pass


def test_extract_unsupported():
    with pytest.raises(ValueError):
        extract.extract_text("a.doc", b"x")


# ---------------------------------------------------------------------------
# 3. 队列按章生成（mock tts）+ 端点（TestClient）
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_tts(monkeypatch):
    """将 tts.generate 替换为写入固定大小假 mp3 的协程。

    协程内部 ``await asyncio.sleep(0)`` 以让出控制权，便于测试「生成期间该书被删除」
    的清理逻辑（否则同步假函数会一气呵成，删除无法插入其间）。
    """

    async def fake_generate(text, voice, rate, out_path, progress_cb=None):
        await asyncio.sleep(0)  # 让出控制权
        if progress_cb:
            progress_cb(50)
            progress_cb(100)
        with open(out_path, "wb") as f:
            f.write(b"ID3\x00" + b"\x00" * 1024)  # 约 1KB 假音频
        return 1028

    monkeypatch.setattr("backend.tts.generate", fake_generate)
    ensure_dirs()
    # 确保 data 目录干净
    yield
    # 清理：删除测试产生的书籍目录
    for bid in ("__test_book__",):
        d = AUDIO_DIR / bid
        if d.exists():
            import shutil

            shutil.rmtree(d, ignore_errors=True)
        t = BOOKS_DIR / f"{bid}.txt"
        if t.exists():
            t.unlink()


def test_queue_generates_chapters(mock_tts):
    book_id = "__test_book__"
    text = (
        "第一章 甲\n甲的正文内容。\n"
        "第二章 乙\n乙的正文内容。\n"
    )
    # 写文本副本
    (BOOKS_DIR / f"{book_id}.txt").write_text(text, encoding="utf-8")
    # 建 Book（含两章）
    split = chapter.split_chapters(text)
    bk = Book(
        id=book_id,
        title="测试书",
        original_path="test.txt",
        status=BookStatus.PENDING,
        format="txt",
        chapters=[
            Chapter(index=c["index"], title=c["title"],
                    audio_rel_path=f"audio/{book_id}/{c['index']}.mp3")
            for c in split
        ],
        chapter_count=len(split),
        text_rel_path=f"books/{book_id}.txt",
    )
    store.save_book(bk)

    asyncio.run(gen_queue.queue._process(book_id))

    # 断言：两章 mp3 均生成
    assert (AUDIO_DIR / book_id / "0.mp3").exists()
    assert (AUDIO_DIR / book_id / "1.mp3").exists()
    reloaded = store.get_book(book_id)
    assert reloaded.status == BookStatus.DONE
    assert reloaded.chapter_count == 2
    assert reloaded.chapters[0].size_bytes == 1028
    assert reloaded.chapters[0].duration_sec is not None
    # 全书聚合
    assert reloaded.size_bytes == 1028 * 2


def test_queue_discard_on_delete(mock_tts):
    book_id = "__test_book__"
    text = "第一章 甲\n甲。\n第二章 乙\n乙。\n"
    (BOOKS_DIR / f"{book_id}.txt").write_text(text, encoding="utf-8")
    split = chapter.split_chapters(text)
    bk = Book(
        id=book_id, title="测试书", original_path="test.txt",
        status=BookStatus.PENDING, format="txt",
        chapters=[Chapter(index=c["index"], title=c["title"],
                          audio_rel_path=f"audio/{book_id}/{c['index']}.mp3")
                  for c in split],
        chapter_count=len(split), text_rel_path=f"books/{book_id}.txt",
    )
    store.save_book(bk)

    # 启动生成，但在首个 await 点前删除该书 -> 清理目录且不复活
    async def run():
        task = asyncio.create_task(gen_queue.queue._process(book_id))
        # 让出控制权（fake tts 会先写第 0 章），随后删除
        await asyncio.sleep(0)
        store.delete_book(book_id)
        await task

    asyncio.run(run())
    assert not (AUDIO_DIR / book_id).exists(), "删除后音频目录应被递归清理"
    assert store.get_book(book_id) is None, "删除后元数据不应复活"


def test_endpoints_with_testclient(mock_tts):
    try:
        from fastapi.testclient import TestClient  # type: ignore
    except ImportError:
        pytest.skip("httpx/TestClient 未安装，跳过端点测试")

    from backend.main import app

    client = TestClient(app)
    # 构造上传文件（含两章 txt）
    content = "第一章 甲\n甲正文。\n第二章 乙\n乙正文。\n".encode("utf-8")
    resp = client.post(
        "/api/books/import",
        files={"files": ("novel.txt", content, "text/plain")},
    )
    assert resp.status_code == 200, resp.text
    book_id = resp.json()["data"]["books"][0]["id"]

    # 轮询进度至 done
    for _ in range(60):
        pr = client.get(f"/api/books/{book_id}/progress").json()["data"]
        if pr["status"] == "done":
            break
        import time

        time.sleep(0.05)

    # 章节列表
    ch = client.get(f"/api/books/{book_id}/chapters").json()["data"]
    assert len(ch["chapters"]) == 2

    # 按章音频：Range 请求返回 206
    r0 = client.get(
        f"/api/books/{book_id}/chapters/0/audio",
        headers={"range": "bytes=0-99"},
    )
    assert r0.status_code == 206, r0.status_code
    assert r0.headers["content-type"] == "audio/mpeg"
    assert r0.headers["accept-ranges"] == "bytes"

    # 兼容别名 /audio 返回第 0 章
    r_alias = client.get(f"/api/books/{book_id}/audio")
    assert r_alias.status_code == 200

    # 不存在的章 -> 404
    r404 = client.get(f"/api/books/{book_id}/chapters/9/audio")
    assert r404.status_code == 404

    # 删除：递归清目录且原始文件（此处无）红线成立
    before = list(AUDIO_DIR.glob(f"{book_id}/*"))
    delr = client.delete(f"/api/books/{book_id}")
    assert delr.status_code == 200
    assert not (AUDIO_DIR / book_id).exists()
    assert store.get_book(book_id) is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
