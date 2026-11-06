"""v1.4 导出到手机工作流回归测试（HTTP 级，针对已在 127.0.0.1:8000 运行的服务）。

用例：
  T1 整本导出：single 模式返回合法 mp3
  T2 分章 zip：chapters 模式返回 zip，条目命名规范且无路径穿越
  T3 模式回退：非法 mode 回退为整本 mp3
  T4 缺章 409：临时移走 1.mp3 期望 409，还原后恢复 200
  T5 未完成/不存在：不存在 id -> 404
"""
from __future__ import annotations

import io
import json
import os
import re
import subprocess
import tempfile
import urllib.request
import urllib.error
import zipfile
from pathlib import Path

import pytest

# 项目根（config.DATA_DIR = <root>/data）
ROOT = Path(__file__).resolve().parent.parent.parent
BOOKS_JSON = ROOT / "data" / "books.json"
AUDIO_DIR = ROOT / "data" / "audio"

BASE_URL = os.environ.get("EXPORT_TEST_BASE", "http://127.0.0.1:8000")
FFPROBE = "/usr/local/bin/ffprobe"

# zip 条目命名规范：两位序号 + 空格 + 任意字符 + .mp3
NAME_RE = re.compile(r"^\d{2} .*\.mp3$")


def _http_get(path: str):
    """GET 返回 (status, headers, body_bytes)；error 时 status 为 None。"""
    url = f"{BASE_URL}{path}"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            # 保留 HTTPMessage：其 .get() 大小写不敏感，避免 dict() 转小写后漏匹配
            return resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read()


def _pick_done_book() -> dict:
    books = json.loads(BOOKS_JSON.read_text(encoding="utf-8"))
    for b in books:
        if b.get("status") == "done" and len(b.get("chapters") or []) >= 2:
            return b
    pytest.skip("data/books.json 中没有 status==done 且章节>=2 的书")


def _is_valid_mp3(path: Path) -> bool:
    """用 ffprobe 确认是 mp3 流。"""
    try:
        out = subprocess.run(
            [FFPROBE, "-v", "error", "-show_entries",
             "stream=codec_name", "-of",
             "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, timeout=30,
        )
        return out.returncode == 0 and "mp3" in out.stdout.decode().split()
    except (OSError, subprocess.SubprocessError):
        return False


# 共享 fixture：选取 done 书
@pytest.fixture(scope="module")
def book():
    return _pick_done_book()


def test_t1_single_export(book):
    """T1 整本导出：200 + audio/mpeg + attachment + 合法 mp3。"""
    status, headers, body = _http_get(f"/api/books/{book['id']}/export")
    assert status == 200, f"期望 200，实际 {status}"
    assert "audio/mpeg" in headers.get("Content-Type", ""), \
        f"Content-Type 非 audio/mpeg: {headers.get('Content-Type')}"
    assert "attachment" in headers.get("Content-Disposition", ""), \
        "缺少 Content-Disposition: attachment"
    assert len(body) > 0
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tf:
        tf.write(body)
        tmp = Path(tf.name)
    try:
        assert _is_valid_mp3(tmp), "响应体不是合法 mp3（ffprobe 校验失败）"
    finally:
        tmp.unlink(missing_ok=True)


def test_t2_chapters_zip(book):
    """T2 分章 zip：200 + application/zip + 条目命名规范/无穿越/均为 mp3。"""
    status, headers, body = _http_get(
        f"/api/books/{book['id']}/export?mode=chapters")
    assert status == 200, f"期望 200，实际 {status}"
    assert "application/zip" in headers.get("Content-Type", ""), \
        f"Content-Type 非 application/zip: {headers.get('Content-Type')}"
    assert "attachment" in headers.get("Content-Disposition", "")

    zf = zipfile.ZipFile(io.BytesIO(body))
    names = zf.namelist()
    # 数量 == 章节数
    assert len(names) == len(book["chapters"]), \
        f"zip 条目数 {len(names)} != 章节数 {len(book['chapters'])}"
    # 命名规范
    for n in names:
        assert NAME_RE.match(n), f"条目名不符合 ^\\d{{2}} .*\\.mp3$ : {n!r}"
    # 无路径穿越（绝对或相对）
    for n in names:
        assert "/" not in n and "\\" not in n, f"条目含路径分隔符: {n!r}"
    # 按 01/02.. 升序
    assert names == sorted(names), f"条目未按 01.. 升序: {names}"
    # 逐条目 ffprobe 确认 mp3
    with tempfile.TemporaryDirectory() as d:
        for n in names:
            p = Path(d) / n
            p.write_bytes(zf.read(n))
            assert _is_valid_mp3(p), f"zip 条目非合法 mp3: {n!r}"


def test_t3_mode_fallback(book):
    """T3 非法 mode 回退为整本 mp3：200 + audio/mpeg。"""
    status, headers, body = _http_get(
        f"/api/books/{book['id']}/export?mode=foobar")
    assert status == 200, f"期望 200，实际 {status}"
    assert "audio/mpeg" in headers.get("Content-Type", ""), \
        f"非法 mode 未回退为 mp3: {headers.get('Content-Type')}"
    assert len(body) > 0


def test_t4_missing_chapter_409(book):
    """T4 缺章 409：临时移走 1.mp3 期望 409，还原后恢复 200。"""
    target = AUDIO_DIR / book["id"] / "1.mp3"
    if not target.exists():
        pytest.skip(f"缺少 {target}，无法构造缺章场景")
    backup = target.with_suffix(".mp3.moved")
    try:
        target.rename(backup)
        # 缺章 -> 409
        status, _, _ = _http_get(
            f"/api/books/{book['id']}/export?mode=chapters")
        assert status == 409, f"缺章期望 409，实际 {status}"
    finally:
        # 务必还原
        if backup.exists():
            backup.rename(target)
    assert target.exists(), "测试未还原 1.mp3"
    # 还原后再请求应恢复 200
    status, _, _ = _http_get(
        f"/api/books/{book['id']}/export?mode=chapters")
    assert status == 200, f"还原后期望 200，实际 {status}"


def test_t5_nonexistent_book_404():
    """T5 不存在的 id -> 404（覆盖未完成/不存在分支）。"""
    fake = "00000000000000000000000000000000"
    status, _, _ = _http_get(f"/api/books/{fake}/export")
    assert status == 404, f"不存在 id 期望 404，实际 {status}"
