"""FastAPI 应用：路由注册、CORS、静态托管、健康检查。

REST 端点严格对齐 docs/ARCHITECTURE.md 第 3.3 节。
统一响应格式：``{"code":0,"data":...,"message":"ok"}``（code==0 成功）。
错误亦转换为相同信封，便于前端统一解析。

原始文件红线：delete 仅删除 app 数据目录内的副本与元数据，
绝不触碰 ``original_path`` 指向的用户原始 txt。
"""
from __future__ import annotations

import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import chapter, extract, netinfo, queue as gen_queue
from .config import (
    ACCESS_TOKEN,
    AUDIO_DIR,
    BASE_DIR,
    BOOKS_DIR,
    DATA_DIR,
    DEFAULT_RATE,
    DEFAULT_VOICE,
    EXPORT_DIR,
    PUBLIC_MODE,
    ensure_dirs,
)
from .models import (
    ApiResponse,
    Book,
    Bookmark,
    BookStatus,
    Chapter,
    PlaybackPosition,
    Settings,
)
from .store import (
    delete_book,
    get_book,
    list_books,
    load_settings,
    save_book,
    save_settings,
)

from .merge import MergeError, build_chapters_zip, merge_book

# ---------------------------------------------------------------------------
# 通用辅助
# ---------------------------------------------------------------------------


def _ok(data=None, message: str = "ok") -> ApiResponse:
    """构造成功响应信封。"""
    return ApiResponse(code=0, data=data, message=message)


def _err(message: str, code: int = 1, http: int = 400) -> HTTPException:
    """构造业务错误（detail 为 {code,message}，供全局异常处理器解析）。"""
    return HTTPException(status_code=http, detail={"code": code, "message": message})


# ---------------------------------------------------------------------------
# 应用初始化
# ---------------------------------------------------------------------------

ensure_dirs()
app = FastAPI(title="听书宝 listen_book", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def _http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    """将 HTTPException 统一转化为 {code,data,message} 信封。"""
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail and "message" in detail:
        code = int(detail["code"])
        message = str(detail["message"])
    else:
        code = exc.status_code
        message = str(detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": code, "data": None, "message": message},
    )


# ---------------------------------------------------------------------------
# 访问口令中间件（v1.3 增量）
# ---------------------------------------------------------------------------

# 免 token 白名单（setup 流程依赖：手机须先拿到可访问 URL 才能输入口令）
_TOKEN_WHITELIST = frozenset({"/api/health", "/api/network/info"})


@app.middleware("http")
async def access_token_guard(request: Request, call_next):
    """轻量访问口令保护：启用 ``ACCESS_TOKEN`` 时，除白名单外的所有 ``/api/*`` 须携带正确 token。

    双通道：Header ``X-Access-Token`` 或 查询 ``?token=`` 任一匹配即放行。
    静态资源（站点根 ``/``、``/assets/*`` 等）不校验，保证页面可加载。
    返回结构与 ``_http_exception_handler`` 一致（``{code,data,message}``），便于前端统一解析。
    """
    path = request.url.path
    # 非 /api 路径（静态站点）不校验，否则页面打不开
    if not path.startswith("/api"):
        return await call_next(request)
    # 白名单端点免校验（健康检查 / 网络信息）
    if path in _TOKEN_WHITELIST:
        return await call_next(request)
    # 未启用口令：全部放行（局域网全开）
    if not ACCESS_TOKEN:
        return await call_next(request)
    provided = request.headers.get("X-Access-Token") or request.query_params.get("token")
    if provided != ACCESS_TOKEN:
        return JSONResponse(
            status_code=401,
            content={"code": 401, "data": None, "message": "需要访问口令"},
        )
    return await call_next(request)


# ---------------------------------------------------------------------------
# 健康检查
# ---------------------------------------------------------------------------


@app.get("/api/health")
async def health() -> ApiResponse:
    """健康检查（免 token 白名单；Docker/Render 探活端点）。

    v2.0：公网模式且未设 ACCESS_TOKEN 时附带 ``warning`` 提示，
    但**不抛异常、不拒绝启动**，保证任何配置下服务都能拉起。
    非公网模式响应与旧版完全一致（只有 ok 字段）。
    """
    data: dict = {"ok": True}
    if PUBLIC_MODE and not ACCESS_TOKEN:
        data["warning"] = (
            "公网模式未设置 ACCESS_TOKEN，服务当前无口令保护，"
            "请立即在平台环境变量配置"
        )
    return _ok(data)


@app.head("/")
async def head_root() -> Response:
    """显式保证 ``HEAD /`` 返回 200（Render 等平台用 HEAD 探活）。

    注册在末尾 ``app.mount("/")`` **之前**：Starlette 按注册顺序匹配，
    HEAD 命中本路由，GET / 继续落到 StaticFiles，不覆盖挂载的 GET 行为。
    即使 frontend/dist 未挂载（纯 API 运行）探活也能成功。
    """
    return Response(status_code=200)


# ---------------------------------------------------------------------------
# 网络访问信息（v1.3 增量，白名单免 token）
# ---------------------------------------------------------------------------


@app.get("/api/network/info")
async def network_info() -> ApiResponse:
    """返回局域网访问信息（白名单、免 token）。

    仅暴露局域网 IP + 端口（与网络扫描可得信息等价，无敏感性），供前端
    「手机访问」面板渲染二维码；获取 URL 后才能进入输入口令流程，故免 token。
    """
    return _ok(netinfo.get_network_info())


# ---------------------------------------------------------------------------
# 书籍导入 / 列表 / 详情
# ---------------------------------------------------------------------------


@app.post("/api/books/import")
async def import_books(files: list[UploadFile] = File(..., alias="files")) -> ApiResponse:
    """导入多个 txt/epub/pdf（仅读取内容），登记元数据并自动入队生成。

    仅取上传文件名的 basename 记录到 original_path 用于展示/溯源，
    绝不访问用户原始文件的绝对路径；解析失败/不支持格式仅跳过该文件，不影响其他文件。
    """
    if not files:
        raise _err("未接收到任何文件")

    settings = load_settings()
    created: list[Book] = []
    skipped: list[str] = []
    for upload in files:
        if not upload.filename:
            continue
        raw = await upload.read()
        # 仅取 basename：不保留、不访问用户原始路径
        original_name = os.path.basename(upload.filename)
        ext = original_name.lower().rsplit(".", 1)[-1] if "." in original_name else ""
        if ext not in ("txt", "epub", "pdf"):
            skipped.append(f"{original_name}（不支持的格式）")
            continue
        try:
            text = extract.extract_text(original_name, raw)
        except ValueError as exc:
            skipped.append(f"{original_name}（{exc}）")
            continue

        book_id = uuid.uuid4().hex
        # 分章检测（返回 [{index,title,text}]）
        split = chapter.split_chapters(text)
        chapters = [
            Chapter(
                index=int(c["index"]),  # type: ignore[arg-type]
                title=str(c["title"]),
                audio_rel_path=f"audio/{book_id}/{int(c['index'])}.mp3",  # type: ignore[arg-type]
            )
            for c in split
        ]
        # 单章兜底标题「全文」用书名替换，展示更友好
        if len(chapters) == 1 and chapters[0].title == "全文":
            chapters[0].title = Path(original_name).stem

        book = Book(
            id=book_id,
            title=Path(original_name).stem,
            original_path=original_name,
            status=BookStatus.PENDING,
            voice=settings.default_voice or DEFAULT_VOICE,
            rate=settings.default_rate or DEFAULT_RATE,
            char_count=len(text),
            format=ext,
            chapters=chapters,
            chapter_count=len(chapters),
            text_rel_path=f"books/{book_id}.txt",
            audio_rel_path="",  # 新书不再写 deprecated 字段，唯一音频来源是 chapters
        )
        # 落盘 app 自己的文本副本，便于重新生成（不影响原始文件）
        (BOOKS_DIR / f"{book_id}.txt").write_text(text, encoding="utf-8")
        save_book(book)
        created.append(book)
        # 异步触发后台生成（仅入队，不阻塞响应）
        await gen_queue.queue.enqueue(book_id)

    message = "ok"
    if skipped:
        message = (
            f"已导入 {len(created)} 本；跳过 {len(skipped)} 个文件："
            + "；".join(skipped)
        )
    return _ok({"books": [b.model_dump(mode="json") for b in created]}, message=message)


@app.get("/api/books")
async def get_books() -> ApiResponse:
    books = [b.model_dump(mode="json") for b in list_books()]
    return _ok({"books": books})


@app.get("/api/books/{book_id}")
async def get_book_detail(book_id: str) -> ApiResponse:
    book = get_book(book_id)
    if book is None:
        raise _err("书籍不存在", http=404)
    return _ok(book.model_dump(mode="json"))


# ---------------------------------------------------------------------------
# 断点续听 / 书签 / 整本导出（v1.2 增量）
# ---------------------------------------------------------------------------


@app.post("/api/books/{book_id}/position")
async def update_position(book_id: str, request: Request) -> ApiResponse:
    """上报/更新断点续听位置（章节 + 章内秒数）。书不存在返回 404。

    位置仅记录「最近一次」，单进程原子写；越界 chapter 拒绝（422）。
    """
    book = get_book(book_id)
    if book is None:
        raise _err("书籍不存在", http=404)
    raw: dict = {}
    try:
        raw = await request.json() or {}
    except Exception:  # noqa: BLE001 - 无 body 时按默认处理
        raw = {}
    try:
        chapter = int(raw.get("chapter", 0))
        position_time = float(raw.get("time", 0.0))
    except (TypeError, ValueError):
        raise _err("参数错误：chapter/time 必须为数字", http=422)
    if chapter < 0 or chapter >= len(book.chapters):
        raise _err(
            f"章节越界：{chapter} 不在 0..{max(len(book.chapters) - 1, 0)}",
            http=422,
        )
    book.playback = PlaybackPosition(current_chapter=chapter, current_time=position_time)
    save_book(book)
    return _ok(book.playback.model_dump(mode="json"))


@app.get("/api/books/{book_id}/export")
async def export_book(
    book_id: str, force: bool = False, mode: str = "single"
) -> Response:
    """导出下载（整本 mp3 或 分章 zip）。

    - ``mode="single"``（默认）：合并整本 mp3，audio/mpeg + attachment；
    - ``mode="chapters"`` / ``mode="zip"``：分章 zip 打包，application/zip + attachment；
    - 书不存在 404；未完成 / 无章节 409；缺章 ValueError -> 409，其它异常 -> 500。
    """
    book = get_book(book_id)
    if book is None:
        raise _err("书籍不存在", http=404)
    if book.status != BookStatus.DONE:
        raise _err("该书尚未生成完成，无法导出", http=409)
    if not book.chapters:
        raise _err("该书没有任何章节，无法导出", http=409)

    # ---- 分章 zip 模式 ----
    if mode in ("chapters", "zip"):
        try:
            zip_bytes = await build_chapters_zip(book_id, book.chapters)
        except ValueError as exc:
            # 缺章 / 空文件等可预期异常 -> 409
            raise _err(str(exc), http=409)
        except Exception as exc:  # noqa: BLE001
            # 打包过程其它意外 -> 500
            raise _err(f"分章打包失败：{exc}", http=500)
        ascii_name = "book-chapters.zip"  # ascii 回退名（无中文，杜绝乱码）
        disp_name = f"{book.title or 'book'}-分章.zip"
        headers = {
            "Content-Disposition": (
                f'attachment; filename="{ascii_name}"; '
                f"filename*=UTF-8''{quote(disp_name)}"
            )
        }
        return Response(
            content=zip_bytes, media_type="application/zip", headers=headers
        )

    # ---- 整本 mp3 模式（默认，保持原行为）----
    try:
        out_path = await merge_book(book_id, book.chapters, force=bool(force))
    except ValueError as exc:
        # 缺章等可预期异常 -> 409（生成中/数据不完整）
        raise _err(str(exc), http=409)
    except MergeError as exc:
        # ffmpeg 失败 / 超时 -> 500
        raise _err(f"合并失败：{exc}", http=500)
    if not os.path.exists(out_path):
        raise _err("导出文件生成失败", http=500)
    filename = f"{book.title or 'book'}.mp3"
    return FileResponse(out_path, media_type="audio/mpeg", filename=filename)


@app.post("/api/books/{book_id}/bookmarks")
async def add_bookmark(book_id: str, request: Request) -> ApiResponse:
    """新增手动书签（chapter/time/label）。

    受 200 上限约束：超出则截断最早的（保留最新 200 条）；书不存在 404；越界 422。
    """
    book = get_book(book_id)
    if book is None:
        raise _err("书籍不存在", http=404)
    raw: dict = {}
    try:
        raw = await request.json() or {}
    except Exception:  # noqa: BLE001
        raw = {}
    try:
        chapter = int(raw.get("chapter", 0))
        bm_time = float(raw.get("time", 0.0))
    except (TypeError, ValueError):
        raise _err("参数错误：chapter/time 必须为数字", http=422)
    if chapter < 0 or chapter >= len(book.chapters):
        raise _err(
            f"章节越界：{chapter} 不在 0..{max(len(book.chapters) - 1, 0)}",
            http=422,
        )
    label = str(raw.get("label", "") or "")
    bookmark = Bookmark(
        id=uuid.uuid4().hex,
        chapter=chapter,
        time=bm_time,
        label=label,
        created_at=time.time(),
    )
    book.bookmarks.append(bookmark)
    if len(book.bookmarks) > 200:
        book.bookmarks = book.bookmarks[-200:]  # 截断最早的，保留最新 200 条
    save_book(book)
    return _ok(bookmark.model_dump(mode="json"))


@app.get("/api/books/{book_id}/bookmarks")
async def list_bookmarks(book_id: str) -> ApiResponse:
    """返回该书全部书签（按存储顺序）。"""
    book = get_book(book_id)
    if book is None:
        raise _err("书籍不存在", http=404)
    return _ok({"bookmarks": [b.model_dump(mode="json") for b in book.bookmarks]})


@app.delete("/api/books/{book_id}/bookmarks/{bk_id}")
async def delete_bookmark(book_id: str, bk_id: str) -> ApiResponse:
    """删除指定书签。书签不存在返回 404。"""
    book = get_book(book_id)
    if book is None:
        raise _err("书籍不存在", http=404)
    before = len(book.bookmarks)
    book.bookmarks = [b for b in book.bookmarks if b.id != bk_id]
    if len(book.bookmarks) == before:
        raise _err("书签不存在", http=404)
    save_book(book)
    return _ok({"deleted": True})


# ---------------------------------------------------------------------------
# 生成进度 / 触发 / 重试
# ---------------------------------------------------------------------------


@app.get("/api/books/{book_id}/progress")
async def get_progress(book_id: str) -> ApiResponse:
    """轮询生成进度（实时百分比）。"""
    return _ok(gen_queue.queue.get_progress(book_id))


@app.post("/api/books/{book_id}/generate")
async def generate_book(book_id: str, request: Request) -> ApiResponse:
    """触发生成（可覆盖音色/语速）。"""
    book = get_book(book_id)
    if book is None:
        raise _err("书籍不存在", http=404)

    body: dict = {}
    try:
        body = await request.json() or {}
    except Exception:  # noqa: BLE001 - 无 body 时按默认处理
        body = {}

    voice = body.get("voice") or book.voice
    rate = body.get("rate") or book.rate
    book.voice = voice
    book.rate = rate
    book.status = BookStatus.PENDING
    book.error = None
    book.progress = 0
    save_book(book)
    await gen_queue.queue.enqueue(book_id)
    return _ok({"id": book_id, "status": book.status.value})


@app.post("/api/books/{book_id}/retry")
async def retry_book(book_id: str) -> ApiResponse:
    """失败重试：重置状态并重新入队。"""
    book = get_book(book_id)
    if book is None:
        raise _err("书籍不存在", http=404)
    book.status = BookStatus.PENDING
    book.error = None
    book.progress = 0
    save_book(book)
    await gen_queue.queue.enqueue(book_id)
    return _ok({"id": book_id, "status": book.status.value})


# ---------------------------------------------------------------------------
# 删除（仅 app 数据）
# ---------------------------------------------------------------------------


@app.delete("/api/books/{book_id}")
async def delete_book_route(book_id: str) -> ApiResponse:
    """删除书籍（仅清 app 数据：按章音频目录 + 文本副本 + 元数据）。

    **绝不**读取/修改/删除/移动用户原始文件（original_path 红线）。
    按章音频存于 ``data/audio/<book_id>/``，整目录递归删除；
    同时兼容清理 v1.0 遗留的单文件 ``data/audio/<book_id>.mp3``。
    """
    audio_book_dir = AUDIO_DIR / book_id
    if audio_book_dir.exists():
        shutil.rmtree(audio_book_dir, ignore_errors=True)  # 递归清理整章目录
    legacy_audio = AUDIO_DIR / f"{book_id}.mp3"
    if legacy_audio.exists():
        legacy_audio.unlink()
    txt_path = BOOKS_DIR / f"{book_id}.txt"
    if txt_path.exists():
        txt_path.unlink()
    # 清理整本导出缓存（v1.2 新增；红线：仅清 app 自身 data/export，绝不碰原始文件）
    export_file = EXPORT_DIR / f"{book_id}.mp3"
    if export_file.exists():
        export_file.unlink()
    export_dir = EXPORT_DIR / book_id  # 兼容 <book_id>/ 目录形态
    if export_dir.exists():
        shutil.rmtree(export_dir, ignore_errors=True)
    delete_book(book_id)  # 仅删元数据
    return _ok({"deleted": True})


# ---------------------------------------------------------------------------
# 章节列表 / 按章音频流（支持 Range，供播放器拖动/seek）
# ---------------------------------------------------------------------------


@app.get("/api/books/{book_id}/chapters")
async def get_chapters(book_id: str) -> ApiResponse:
    """返回章节列表（index/title/audio_rel_path/duration_sec/size_bytes）。"""
    book = get_book(book_id)
    if book is None:
        raise _err("书籍不存在", http=404)
    chapters = [c.model_dump(mode="json") for c in book.chapters]
    return _ok({"chapters": chapters})


def _resolve_chapter_audio(book: Book, idx: int) -> Optional[Path]:
    """解析某章音频文件绝对路径；章不存在或无文件返回 None。

    新数据路径为 ``data/audio/<book_id>/<idx>.mp3``；
    旧数据迁移后 audio_rel_path 为 ``audio/<id>.mp3``，同样可经 DATA_DIR 解析。
    """
    if idx < 0 or idx >= len(book.chapters):
        return None
    rel = book.chapters[idx].audio_rel_path
    if not rel:
        return None
    path = DATA_DIR / rel
    return path if path.exists() else None


def _stream_audio(audio_path: Path, request: Request) -> Response:
    """按需读取音频文件并以支持 Range 的 audio/mpeg 流返回。"""
    size = audio_path.stat().st_size
    range_header = request.headers.get("range")
    if range_header:
        match = re.match(r"bytes=(\d*)-(\d*)", range_header)
        if match:
            start_s, end_s = match.group(1), match.group(2)
            start = int(start_s) if start_s else 0
            end = int(end_s) if end_s else size - 1
            end = min(end, size - 1)
            if start > end:
                return Response(
                    status_code=416,
                    headers={"Content-Range": f"bytes */{size}"},
                )
            with open(audio_path, "rb") as handle:
                handle.seek(start)
                data = handle.read(end - start + 1)
            headers = {
                "Content-Range": f"bytes {start}-{end}/{size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(len(data)),
                "Content-Type": "audio/mpeg",
            }
            return Response(content=data, status_code=206, headers=headers)

    with open(audio_path, "rb") as handle:
        data = handle.read()
    return Response(
        content=data,
        media_type="audio/mpeg",
        headers={"Accept-Ranges": "bytes", "Content-Length": str(size)},
    )


@app.get("/api/books/{book_id}/chapters/{idx}/audio")
async def get_chapter_audio(book_id: str, idx: int, request: Request) -> Response:
    """按章音频流（支持 Range）。章不存在或音频未生成返回 404。"""
    book = get_book(book_id)
    if book is None:
        raise _err("书籍不存在", http=404)
    audio_path = _resolve_chapter_audio(book, idx)
    if audio_path is None:
        raise _err("该章音频尚未生成或不存在", http=404)
    return _stream_audio(audio_path, request)


@app.get("/api/books/{book_id}/audio")
async def get_audio(book_id: str, request: Request) -> Response:
    """兼容别名：返回第 0 章音频（存在则 200，否则 404）。

    保留给旧前端 / 旧数据；新前端一律走按章端点。
    """
    book = get_book(book_id)
    if book is None:
        raise _err("书籍不存在", http=404)
    audio_path = _resolve_chapter_audio(book, 0)
    if audio_path is None:
        raise _err("音频尚未生成", http=404)
    return _stream_audio(audio_path, request)


# ---------------------------------------------------------------------------
# 音色 / 设置
# ---------------------------------------------------------------------------


@app.get("/api/voices")
async def get_voices() -> ApiResponse:
    from .tts import list_voices

    return _ok({"voices": list_voices()})


@app.get("/api/settings")
async def get_settings() -> ApiResponse:
    return _ok(load_settings().model_dump(mode="json"))


@app.put("/api/settings")
async def put_settings(request: Request) -> ApiResponse:
    raw: dict = {}
    try:
        raw = await request.json() or {}
    except Exception:  # noqa: BLE001
        raw = {}
    try:
        settings = Settings(**raw)
    except Exception as exc:  # noqa: BLE001
        raise _err(f"参数错误: {exc}", http=422)
    save_settings(settings)
    return _ok(settings.model_dump(mode="json"))


# ---------------------------------------------------------------------------
# 静态托管（运行态：仅当 frontend/dist 存在时挂载为站点根）
# ---------------------------------------------------------------------------

DIST_DIR = BASE_DIR / "frontend" / "dist"
if DIST_DIR.exists():
    app.mount("/", StaticFiles(directory=str(DIST_DIR), html=True), name="static")
