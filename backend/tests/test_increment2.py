"""听书宝 v1.2 增量验证：合并导出 / 断点续听 / 书签 / 删除清 export。

运行（项目根目录，需先激活 venv）：
    python -m pytest backend/tests/test_increment2.py -v
    # 或： python backend/tests/test_increment2.py

- 不需要持续联网：merge 用 ffmpeg 造两个测试 mp3；端点用 TestClient + 直接落盘 Book，
  绕过 edge-tts 生成队列。
- 重点关注红线：导出只读分章、零改动；删除清 export 且原始（用户）文件不动。
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote

# 将项目根加入 sys.path，使 ``backend`` 包可被绝对导入
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import backend.config as cfg  # noqa: E402
import backend.main as main  # noqa: E402
import backend.merge as merge  # noqa: E402
import backend.store as store  # noqa: E402

# 探测 ffmpeg（与 merge.py 同策略）
_FFMPEG = (
    "/usr/local/bin/ffmpeg" if os.path.exists("/usr/local/bin/ffmpeg") else "ffmpeg"
)


def _make_tmp_env():
    """重定向所有模块内绑定的配置路径到临时目录，避免污染真实 data/。"""
    tmp = Path(tempfile.mkdtemp(prefix="listenbook_test_"))
    audio = tmp / "audio"
    books = tmp / "books"
    export = tmp / "export"
    audio.mkdir()
    books.mkdir()
    export.mkdir()
    books_json = tmp / "books.json"
    settings_json = tmp / "settings.json"
    cfg.DATA_DIR = tmp
    cfg.BOOKS_DIR = books
    cfg.AUDIO_DIR = audio
    cfg.EXPORT_DIR = export
    cfg.BOOKS_JSON = books_json
    cfg.SETTINGS_JSON = settings_json
    for mod in (store, main, merge):
        if hasattr(mod, "DATA_DIR"):
            mod.DATA_DIR = tmp
        if hasattr(mod, "BOOKS_DIR"):
            mod.BOOKS_DIR = books
        if hasattr(mod, "AUDIO_DIR"):
            mod.AUDIO_DIR = audio
        if hasattr(mod, "EXPORT_DIR"):
            mod.EXPORT_DIR = export
        if hasattr(mod, "BOOKS_JSON"):
            mod.BOOKS_JSON = books_json
        if hasattr(mod, "SETTINGS_JSON"):
            mod.SETTINGS_JSON = settings_json
    return tmp, audio, books, export, books_json


def _gen_mp3(path: Path, freq: int, duration: float = 1.0) -> None:
    """用 ffmpeg 造一个测试 mp3（sine 音），校验 ffmpeg 可用。"""
    cmd = [
        _FFMPEG,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency={freq}:duration={duration}",
        str(path),
    ]
    proc = subprocess.run(cmd, timeout=60, capture_output=True)
    assert proc.returncode == 0, f"ffmpeg 造测试 mp3 失败: {proc.stderr.decode()[-300:]}"
    assert path.exists() and path.stat().st_size > 0


@pytest.fixture
def env():
    tmp, audio, books, export, books_json = _make_tmp_env()
    yield {
        "tmp": tmp,
        "audio": audio,
        "books": books,
        "export": export,
        "books_json": books_json,
    }
    shutil.rmtree(tmp, ignore_errors=True)


def _make_done_book(book_id: str, audio_dir: Path, export_dir: Path):
    """造一个 done 书（2 章 mp3 已存在），落盘并返回 Book。"""
    from backend.models import Book, BookStatus, Chapter

    (audio_dir / book_id).mkdir(parents=True, exist_ok=True)
    p0 = audio_dir / book_id / "0.mp3"
    p1 = audio_dir / book_id / "1.mp3"
    _gen_mp3(p0, 440, 1.0)
    _gen_mp3(p1, 660, 1.0)
    book = Book(
        id=book_id,
        title="测试书",
        original_path="test.txt",  # 仅 basename，绝不访问
        status=BookStatus.DONE,
        chapters=[
            Chapter(
                index=0,
                title="第一章",
                audio_rel_path=f"audio/{book_id}/0.mp3",
                duration_sec=1.0,
                size_bytes=p0.stat().st_size,
            ),
            Chapter(
                index=1,
                title="第二章",
                audio_rel_path=f"audio/{book_id}/1.mp3",
                duration_sec=1.0,
                size_bytes=p1.stat().st_size,
            ),
        ],
        chapter_count=2,
        text_rel_path=f"books/{book_id}.txt",
    )
    store.save_book(book)
    return book


# --------------------------- merge_book ---------------------------


def test_merge_basic(env):
    book_id = "bk_merge"
    book = _make_done_book(book_id, env["audio"], env["export"])
    src0 = env["audio"] / book_id / "0.mp3"
    src1 = env["audio"] / book_id / "1.mp3"
    size0_before, mtime0_before = src0.stat().st_size, src0.stat().st_mtime
    size1_before, mtime1_before = src1.stat().st_size, src1.stat().st_mtime
    out = asyncio.run(merge.merge_book(book_id, book.chapters))
    out_path = Path(out)
    assert out_path.exists()
    # 合并产物大小约等于两段之和（copy 直拼，允许少量容器开销）
    total = sum(c.size_bytes or 0 for c in book.chapters)
    assert total > 0
    assert out_path.stat().st_size >= total * 0.8
    # 红线：源分章文件零改动 —— size 与 mtime 合并前后完全一致
    assert src0.stat().st_size == size0_before and src0.stat().st_mtime == mtime0_before
    assert src1.stat().st_size == size1_before and src1.stat().st_mtime == mtime1_before
    assert src0.stat().st_size > 0 and src1.stat().st_size > 0


def test_merge_cache_hit(env):
    book_id = "bk_cache"
    book = _make_done_book(book_id, env["audio"], env["export"])
    first = asyncio.run(merge.merge_book(book_id, book.chapters))
    mtime1 = Path(first).stat().st_mtime
    # 立即再次调用应命中缓存（不重生成，mtime 不变）
    second = asyncio.run(merge.merge_book(book_id, book.chapters))
    assert first == second
    assert Path(second).stat().st_mtime == mtime1


def test_merge_force_regenerate(env):
    book_id = "bk_force"
    book = _make_done_book(book_id, env["audio"], env["export"])
    first = asyncio.run(merge.merge_book(book_id, book.chapters))
    second = asyncio.run(merge.merge_book(book_id, book.chapters, force=True))
    assert Path(second).exists()
    assert first == second


def test_merge_missing_chapter(env):
    book_id = "bk_missing"
    book = _make_done_book(book_id, env["audio"], env["export"])
    (env["audio"] / book_id / "1.mp3").unlink()
    with pytest.raises(ValueError):
        asyncio.run(merge.merge_book(book_id, book.chapters))


# --------------------------- endpoints ---------------------------


def _client():
    return TestClient(main.app)


def test_position_crud(env):
    book_id = "bk_pos"
    _make_done_book(book_id, env["audio"], env["export"])
    c = _client()
    r = c.post(f"/api/books/{book_id}/position", json={"chapter": 1, "time": 30.5})
    assert r.status_code == 200
    assert r.json()["code"] == 0
    assert r.json()["data"]["current_chapter"] == 1
    assert r.json()["data"]["current_time"] == 30.5
    # 持久化确认
    r2 = c.get(f"/api/books/{book_id}")
    assert r2.status_code == 200
    pb = r2.json()["data"]["playback"]
    assert pb["current_chapter"] == 1 and pb["current_time"] == 30.5
    # 越界 chapter 应 422
    r3 = c.post(f"/api/books/{book_id}/position", json={"chapter": 99, "time": 0})
    assert r3.status_code == 422


def test_bookmarks_crud(env):
    book_id = "bk_bmk"
    _make_done_book(book_id, env["audio"], env["export"])
    c = _client()
    r = c.post(
        f"/api/books/{book_id}/bookmarks",
        json={"chapter": 0, "time": 12.3, "label": "重点"},
    )
    assert r.status_code == 200
    bm = r.json()["data"]
    assert bm["chapter"] == 0 and bm["time"] == 12.3 and bm["label"] == "重点"
    assert bm["id"]
    bk_id = bm["id"]
    # 查
    r2 = c.get(f"/api/books/{book_id}/bookmarks")
    assert r2.status_code == 200
    assert len(r2.json()["data"]["bookmarks"]) == 1
    # 删
    r3 = c.delete(f"/api/books/{book_id}/bookmarks/{bk_id}")
    assert r3.status_code == 200 and r3.json()["data"]["deleted"] is True
    r4 = c.get(f"/api/books/{book_id}/bookmarks")
    assert len(r4.json()["data"]["bookmarks"]) == 0
    # 删不存在
    r5 = c.delete(f"/api/books/{book_id}/bookmarks/nope")
    assert r5.status_code == 404


def test_export_done_and_pending(env):
    book_id = "bk_exp"
    _make_done_book(book_id, env["audio"], env["export"])
    c = _client()
    r = c.get(f"/api/books/{book_id}/export")
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/mpeg"
    cd = r.headers.get("content-disposition", "")
    assert "attachment" in cd
    # Starlette 对中文文件名采用 RFC 5987 编码（filename*=utf-8''...），浏览器可正确解码
    assert "测试书.mp3" in unquote(cd)
    assert len(r.content) > 0
    # 缓存命中：再次请求应直接返回已存在文件（200）
    r2 = c.get(f"/api/books/{book_id}/export")
    assert r2.status_code == 200

    # pending 书应 409（未完成）
    from backend.models import Book, BookStatus

    pending = Book(
        id="bk_pending",
        title="未完成",
        original_path="p.txt",
        status=BookStatus.PENDING,
        chapters=[],
    )
    store.save_book(pending)
    rp = c.get("/api/books/bk_pending/export")
    assert rp.status_code == 409


def test_delete_clears_export_keeps_original(env):
    book_id = "bk_del"
    book = _make_done_book(book_id, env["audio"], env["export"])
    # 先导出，产生 export 缓存
    asyncio.run(merge.merge_book(book_id, book.chapters))
    assert (env["export"] / f"{book_id}.mp3").exists()
    # 模拟用户原始文件（位于 tmp 根，app 绝不碰；仅记录 basename）
    original = env["tmp"] / f"user_original_{book_id}.txt"
    original.write_text("用户原始内容，绝不改动")
    book.original_path = original.name
    store.save_book(book)
    c = _client()
    r = c.delete(f"/api/books/{book_id}")
    assert r.status_code == 200
    # export 清掉
    assert not (env["export"] / f"{book_id}.mp3").exists()
    # audio 清掉
    assert not (env["audio"] / book_id).exists()
    # 原始文件原样存在、内容不变（红线）
    assert original.exists()
    assert original.read_text() == "用户原始内容，绝不改动"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
