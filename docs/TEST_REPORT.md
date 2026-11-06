# 听书宝 listen_book · 测试报告（QA：严过关 / Edward）

- 测试对象：`/workspace/listen-book/`（后端 FastAPI + edge-tts；前端 Vite + React + MUI + Tailwind）
- 测试方式：真实运行后端（`uvicorn` 127.0.0.1:8000）+ `requests` 真实 HTTP 调用
- 测试脚本：`/workspace/listen-book/qa_test_suite.py`（可重跑；结果亦存 `docs/qa_results.json`）
- 测试时间：单次运行；测试轮次：第 1 轮（全部核心用例一轮完成，含 1 次确定性 Bug 复现）

---

## 一、测试环境

| 项 | 值 |
| --- | --- |
| OS / Python | Linux / Python 3.11.1 |
| 后端 | venv `.venv`，`pip install -r backend/requirements.txt` + `requests` 成功 |
| 启动 | `uvicorn backend.main:app --host 127.0.0.1 --port 8000`（后台 nohup） |
| `/api/health` | HTTP 200，`{"code":0,"data":{"ok":true},"message":"ok"}` ✅ |
| 原始样本 | `/tmp/origin/三体节选.txt`（1028 字节，中文小说节选） |
| **网络** | **通用外网可达（github/example.com=200）；但 `speech.platform.bing.com`（edge-tts）被拦截（WSS 握手 403/400）→ 真实 TTS 合成在本环境不可达** |

> 红线证据所用的原始文件指纹（全程不变）：
> `sha256 = db408322c39b91cda8a7b828f218f62c64291e64476630b328badc7be222971d`，`size=1028`，`mtime` 三次比对完全一致。

---

## 二、用例清单（状态：PASS / FAIL / BLOCKED / FINDING / INFO / SKIP）

| # | 用例 | 状态 | 关键结果 |
| --- | --- | --- | --- |
| 1 | health 健康检查 | PASS | 200, code=0 |
| 2 | 导入 `files`（真实契约） | PASS | id 已记录，original_path=`三体节选.txt`，status=pending，char_count=360 |
| 3 | 导入 `files[]`（文档口径） | **FINDING** | 发送 `files[]` → HTTP 422「Field required」；实际契约为 `files` |
| 4 | 红线①：导入后原始文件未变 | PASS | 原始 sha256/size/mtime 导入前后一致 |
| 5 | 红线①：副本存在且内容一致 | PASS | `data/books/<id>.txt` 存在，内容与原始逐字节一致 |
| 6 | generate 端点可达 | PASS | POST 返回 code=0, {id,status} |
| 7 | generate 终态流转 | PASS | 联网阻断下终态=failed（后端失败处理正常） |
| 8 | generate 成功产物（mp3/时长/大小/字数） | **BLOCKED** | 真实 edge-tts 被网络阻断(403)，无法产出真实 mp3（**非源码 Bug**） |
| 9 | 音频流 200（合成夹具） | PASS | Content-Type=audio/mpeg，bytes=5000 |
| 10 | 音频 Range 206 | PASS | 206 + `Content-Range: bytes 0-99/5000`，body=100 字节 |
| 11 | retry 端点可达 | PASS | POST 返回 code=0, {id,status} |
| 12 | voices 数量 | PASS | 5 个中文音色（≥5） |
| 13 | settings 读取默认 | PASS | 默认 XiaoxiaoNeural / +0% |
| 14 | settings 保存+持久化 | PASS | PUT→GET 一致；`data/settings.json` 落盘 |
| 15 | delete 端点 | PASS | code=0, {deleted:true} |
| 16 | delete 删除 app 副本 | PASS | `audio/<id>.mp3` 与 `books/<id>.txt` 均已删 |
| 17 | delete 列表立即不含该书 | PASS | 删除后列表不含该书 |
| 18 | delete 沉淀后列表仍不含 | PASS | 等终态后再删，沉淀 3s 不复活 |
| 19 | **红线②：删除后原始文件未变** | PASS | 原始 sha256/size/mtime 删除前后一致 |
| 20 | **delete 在途生成竞态 → 书籍复活** | **FAIL**（源码 Bug） | 导入后立即删除，待在途生成结束后该书被复活（见第五节 Bug#1） |
| 21 | 前端构建 `npm run build` | PASS | 923 modules，2.04s，`dist/index.html` 存在 |
| 22 | 运行态静态托管 `GET /` | PASS | 200 text/html，`<title>听书宝 listen_book</title>` |
| — | 清理 | — | 测试结束 `books.json=[]`，`settings.json` 还原默认，audio/books 空 |

**汇总**：PASS=18，FINDING=1，BLOCKED=1，INFO=1，FAIL=1（源码 Bug）。

---

## 三、关键断言与红线证据

### 红线①（导入后原始文件不被触碰）
- 操作：`POST /api/books/import`，上传 `/tmp/origin/三体节选.txt`。
- 比对（导入前 → 导入后）：
  - sha256：`db408322c39b…` → `db408322c39b…` ✅ 一致
  - size：`1028` → `1028` ✅；mtime：一致 ✅
- 副本：`data/books/<id>.txt` 已创建，且与原始文件逐字节相同（验证 `read_text` 落盘副本逻辑正确）。

### 红线②（删除后原始文件不被触碰）
- 操作：`DELETE /api/books/<id>`（先轮询到生成终态再删，规避竞态）。
- 比对（删除前 → 删除后）：
  - sha256：`db408322c39b…` → `db408322c39b…` ✅ 一致
  - size：`1028` → `1028` ✅；mtime：一致 ✅
- 后端仅删 `data/audio/<id>.mp3` 与 `data/books/<id>.txt` 及元数据，**原始 `/tmp/origin/三体节选.txt` 始终未被读/写/删/移动**。
- **结论：两条红线均守住（PASS）。**

### 音频流与 Range（端点逻辑，因 TTS 联网阻断用 5000B 合成夹具验证）
- `GET /api/books/<id>/audio` → 200，`Content-Type: audio/mpeg`，body=5000B。
- `GET /api/books/<id>/audio` + `Range: bytes=0-99` → 206，`Content-Range: bytes 0-99/5000`，body=100B。
- 端点 200/206/Range 逻辑正确（该逻辑与 TTS 是否联网无关，已验证通过）。

---

## 四、被阻断项说明（非源码 Bug）

- **真实 TTS 生成（用例 8）**：本沙箱可访问通用外网，但 `speech.platform.bing.com`（edge-tts WebSocket）握手被拦截（HTTP 403 / WSS 握手失败）。因此无法产出真实 mp3，**`duration_sec / size_bytes / char_count` 的成功填充路径未能在本环境验证**。
- 已验证的等价结论：generate 端点正确触发入队；后端 `queue.py` 的失败处理路径正常——网络异常时状态正确流转为 `failed` 并写入 `error`（实测 error 含 403 握手失败信息），**无 500 / 无崩溃 / 无进程异常**（uvicorn 日志无 traceback）。
- 建议：在可访问 edge-tts 的网络环境补跑用例 8，验证真实 mp3 产物与元数据填充。

---

## 五、发现的问题与智能路由判定

### 🔴 Bug#1（源码 Bug · 路由：回派工程师 Alex 修复）
**标题**：删除在途生成任务对应的书籍后，该书被「复活」。

**复现步骤**：
1. `POST /api/books/import`（fields=`files`）→ 创建书籍 A，后台生成任务入队（网络失败约 2s）。
2. **立即** `DELETE /api/books/{A}` → 200，列表即时不再含 A，副本文件已删。
3. 等待约 5s，让仍在途的生成任务结束/失败。
4. `GET /api/books` → **A 重新出现**（status=failed）。

**实测证据**（测试套件用例 20）：
```
导入后立即删除：删除瞬间列表含该书=False；在途生成结束后列表含该书=True
-> 已删除书籍被在途生成任务复活(源码Bug)
```

**根因**（后端 `backend/queue.py`）：
`GenerationQueue._process` 在任务开始时 `get_book(book_id)` 取出书籍对象并持有；任务结束（含 `except/finally`）调用 `self._touch_and_save(book)`，而 `_touch_and_save` → `save_book(book)` 会**无条件把该 book 写回 `books.json`**。删除发生在任务运行期间时，`delete_book` 已将其从 `books.json` 移除，但任务结束时仍用旧的 book 对象回写，导致复活（同时会重新生成 0 字节的 `audio/<id>.mp3`）。

**影响**：数据完整性问题——用户删除书籍期间若生成仍在跑，删除后书籍（及空音频文件）会重新出现，与「删除仅清 app 数据、删除即消失」的预期相悖。

**建议修复方向（供工程师参考，QA 未改动业务代码）**：
- 在 `_process` 收尾保存前，重新 `get_book(book_id)` 校验该书仍存在（已被删则不回写）；或
- 维护「已取消/已删除 book_id 集合」，任务启动时登记、delete 时加入，任务结束前检查；或
- `delete_book` 同时标记取消，并让 `_process` 在最终保存前跳过已删除项。

---

### 🟡 Finding#2（文档/契约不一致 · 路由：主理人/PM 决策）
**标题**：导入接口字段名文档写 `files[]`，实现用 `files`。

- `docs/ARCHITECTURE.md` §3.3 与本次测试任务均声明 multipart 字段为 **`files[]`**。
- 实际：后端 `backend/main.py:104` `File(..., alias="files")`；前端 `frontend/src/api/client.js:63` `form.append('files', f)`。二者一致，**真实前后端互通正常**（均用 `files`）。
- 发送 `files[]` → **HTTP 422「Field required」**。

**判定**：功能性无阻断（真实前端与后端契约一致、可正常工作）；属于**规格文档与实现不一致**。建议 PM/主理人决定：要么把 `ARCHITECTURE.md`（及任务描述）统一为 `files`，要么把后端 `alias` 与前端改为 `files[]` 以对齐文档契约。QA 按真实可用契约 `files` 完成功能验证。

---

## 六、前端构建结论
- `cd frontend && npm run build`：**通过**（vite v5.4.21，923 modules transformed，2.04s，产出 `dist/index.html` + `dist/assets/*`）。
- 运行态静态托管验证：`GET /` 返回 200 `text/html`，标题「听书宝 listen_book」，确认后端正确挂载 `frontend/dist`（T12 单命令托管能力成立）。

---

## 七、结论

- **红线测试：✅ PASS**（导入后、删除后，用户原始 `/tmp/origin/三体节选.txt` 均原样存在、sha256/size/mtime 未变；副本机制与删除清理均正确）。
- **功能测试（除联网项）：✅ PASS**（导入、generate 端点与失败处理、音频流/Range 端点逻辑、voices、settings 持久化、delete 清理、retry、前端构建、静态托管均通过）。
- **真实 TTS 生成成功路径：⚠️ BLOCKED**（环境联网阻断 edge-tts，非源码 Bug；失败处理路径已验证正常）。
- **源码质量门禁：❌ FAIL（含 1 个需修复的源码 Bug）**——删除在途生成竞态导致书籍复活（Bug#1，已路由回派工程师）。
- 另有 1 项文档/契约不一致（Finding#2，建议 PM 决策对齐）。

**总体判定（Round 1）：红线守住；但存在 1 个源码 Bug（删除竞态复活），建议修复后复测该用例再放行。**

---

## 八、主理人终验（Round 2 · 真实运行复验）

修复后由主理人执行真实端到端复验（`edge-tts 7.3.1`，`uvicorn 127.0.0.1:8000`，`requests` 真实调用）。

### 修复项 1：edge-tts 版本坑（导致原「真实 TTS 生成」被 BLOCKED 的根因）
- 原 `requirements.txt` 锁定 `edge-tts>=6.1,<7.0` → 实际安装 **6.1.19**，调用微软语音服务 WebSocket 握手返回 **403**（Sec-MS-GEC 校验版本过旧）。
- 修正为 `edge-tts>=7.0`（实测 7.3.1），握手成功，**真实生成 896KB 合法 mp3（MPEG layer III, 48kbps, 24kHz, mono）**。原 BLOCKED 用例 8 现已 **PASS**。

### 修复项 2：删除在途生成竞态复活（Bug#1，源码 Bug）
- `backend/queue.py` 收尾去掉无条件的 `finally: save_book`；改为收尾/失败前先 `get_book(book_id)` 复查：若已删除（`None`）则仅清理孤儿音频 `AUDIO_DIR/<id>.mp3` 与内存进度，**不再回写元数据**。
- 工程师 mock 验证 4 路径（删除在途/正常/失败/失败已删）全 PASS；主理人真实复验「导入后立即 DELETE → 等待生成结束 → 列表不含该书 + 无孤儿文件」PASS。

### 终验结论（16/16 PASS）
| 类别 | 结果 |
| --- | --- |
| 健康检查 / 导入 / 5 中文音色 | PASS |
| **真实 edge-tts 生成**（产出 896KB mp3，status=done） | PASS |
| 音频流 200 + Range 206(~100B) | PASS |
| **红线① 导入后原始文件 sha256/size/mtime 不变** | PASS |
| **红线② 删除后原始文件仍原样存在、sha 不变** | PASS |
| **删除在途生成不复活 + 无孤儿文件** | PASS |
| 删除清理 app 副本（mp3/txt/元数据） | PASS |
| 设置持久化 / 前端构建 / 静态托管 | PASS |

### 文档一致性（Finding#2）
- 已将 `ARCHITECTURE.md` §3.3 的导入字段由 `files[]` 对齐为实际契约 `files`（前后端一致、真实互通正常）。

**最终判定：✅ PASS，可交付。** 红线守住；真实 TTS 生成、删除清理、删除竞态修复、音频播放（含 Range 拖动/倍速）均经真实运行验证通过。

---

## 九、增量功能终验（一键启动 / epub·pdf / 分章听书）

基于 `PRD_INCREMENT.md` 与 `ARCHITECTURE_INCREMENT.md`，由主理人执行真实端到端复验（edge-tts 7.3.1 + 真实 txt/epub/pdf 样本）。

### 复验结果（24/24 PASS，真实 TTS 生成）
| 能力 | 结果 |
| --- | --- |
| txt 双章自动切分 + 按章生成 mp3（真实 TTS，每章 25–44KB） | PASS |
| epub 导入：zip+BeautifulSoup 提取正文、自动配音进书架 | PASS |
| pdf 导入：pypdf 提取文本层、按 `Chapter 1/2` 切 2 章并配音 | PASS |
| 按章音频端点 `/chapters/{idx}/audio` 200 + Range 206(`~100B`)、兼容别名 `/audio` 200、越界章 404 | PASS |
| 播放器章节交互（列表/上章/下章/跳转）前端构建通过 | PASS |
| **红线在 epub/pdf/分章下仍成立**：导入/删除后原始 txt/epub/pdf 的 sha256/size/mtime 不变，删除仅清 app 数据 | PASS |
| 删除在途生成递归清理 `data/audio/<id>/` 且不复活 | PASS |
| **一键启动脚本 `start.sh`**：干净/复用环境均成功拉起服务，`http://localhost:8000` 健康检查 200、前端页面（标题「听书宝 listen_book」）由后端托管 | PASS |
| 单元测试 `backend/tests/test_increment.py` | 12 passed |

### 增量阶段发现并修复的 2 个源码缺陷
1. **章节切分「标题与正文同行」丢失**（backend/chapter.py）：原逻辑假设章首标题独占一行，当提取文本为 `Chapter 1. 正文...`（标题与正文同行，PDF 提取常见）时两章被误判为空→回退单章。修复：将章首行全文计入本章正文。同步更新过时单测断言（现 3 章均保留）。
2. **`run.py` 启动崩溃（遮蔽标准库）**（backend/run.py）：`python backend/run.py` 会把 `backend/` 注入 `sys.path[0]`，导致 `import queue` 被 `backend/queue.py` 遮蔽、uvicorn 启动即退出（exit 1），一键脚本因此失败。修复：启动前从 `sys.path` 移除脚本自身目录，仅保留项目根。

### 最终判定
✅ **增量三项能力全部交付并经验证**：单命令一键启动、epub/pdf 导入、分章听书；红线在全部格式与分章场景下守住。

---

## 十、增量二（v1.2）测试结论 · QA 独立复测

> 测试对象：合并导出整本 mp3（EXP）、断点续听持久化（RES）、手动书签（BMK）、删除清 export（DEL-003）。
> 测试方式：真实运行后端（uvicorn 127.0.0.1:8000）+ `requests` 真实 HTTP 调用；另跑增量单测（`TestClient` + ffmpeg 造章）。
> 测试时间：独立复测轮次 **1 轮**（e2e3 34 项 + 独立回归 32 项 + 单测 20 项 + 前端构建 1 项，全部通过，无需第 2 轮）。
> 网络：edge-tts 7.3.1 真实可达（微软语音服务握手成功），真实生成双章中文 mp3。

### 10.1 测试环境

| 项 | 值 |
| --- | --- |
| OS / Python | Linux / Python 3.11.1（venv `.venv`） |
| 后端 | edge-tts 7.3.1；bs4 / pypdf 6.21.4 已装；ffmpeg `/usr/local/bin/ffmpeg`（N-124111）系统级可用 |
| 启动 | 先 `lsof -ti:8000` 反查并 kill 残留，再 `uvicorn backend.main:app --host 127.0.0.1 --port 8000`（后台） |
| `/api/health` | HTTP 200，`{"code":0,"data":{"ok":true},"message":"ok"}` ✅ |
| 样本 | `/tmp/cn_book.txt`（双章中文）、`/tmp/sample.epub`、`/tmp/sample.pdf`（reportlab 双章） |
| 单测依赖 | venv 安装 `pytest` + `httpx`（requirements.txt 未含，按需补装） |

### 10.2 新增用例清单（状态：PASS / FAIL / SKIP / FINDING）

**A. 端到端真跑（复用并独立重跑 `/tmp/e2e3.py`，34 项，真实 edge-tts）**

| # | 用例 | 状态 | 关键结果 |
| --- | --- | --- | --- |
| A1 | 导入双章 txt（code0 / pending / chapter_count=2） | PASS | 真实分章 2 章 |
| A2 | 轮询生成至 done（真实 TTS） | PASS | status=done，两章 mp3 各 >1KB |
| A3 | 断点续听 `POST /position` | PASS | 返回 current_chapter=1 / current_time=30.0 |
| A4 | 断点持久化（重读 Book） | PASS | playback.chapter=1 / time=30.0 落盘 |
| A5 | 整本导出 `GET /export` 200 | PASS | Content-Type=audio/mpeg，Content-Disposition=attachment |
| A6 | 整本大小≈两章之和 | PASS | export=173325B，两章 sum=173088B（差 237B 容器开销，<0.3%） |
| A7 | 导出后源分章零改动 | PASS | 分章 0/1 的 size 与 mtime 导出前后完全一致 |
| A8 | 导出产物落盘 `data/export/<id>.mp3` | PASS | 文件存在 |
| A9 | 书签增/查/删 | PASS | 新增 code0 → 列表 1 条 → 删除后 0 条 |
| A10 | 导入+导出后原始文件红线 | PASS | sha256/size/mtime 不变 |
| A11 | 删除清 export+audio+列表 | PASS | export 消失、audio 目录消失、列表不含该书 |
| A12 | 删除后原始文件红线 | PASS | sha256/size/mtime 不变，原始文件依旧存在 |

**B. 独立全量回归（v1.1 不退化，32 项，自写脚本）**

| # | 用例 | 状态 | 关键结果 |
| --- | --- | --- | --- |
| B1 | epub 提取（后端 `extract_text`）含第一/二章正文 | PASS | 「第一章 风起」「第二章 云涌」均在 |
| B2 | epub 提取文本分章数=2 | PASS | split_chapters → 2 章 |
| B3 | pdf 提取（后端 `extract_text`）含 Chapter 1/2 | PASS | 两章标识均在 |
| B4 | pdf 提取文本分章数=2 | PASS | split_chapters → 2 章 |
| B5 | epub HTTP 导入→真实生成 done | PASS | format=epub，chapter_count=2 |
| B6 | pdf HTTP 导入→真实生成 done | PASS | format=pdf，chapter_count=2 |
| B7 | 按章音频 Range 206（epub/pdf） | PASS | 206 + 100B body |
| B8 | 别名 `/audio` 200（epub/pdf） | PASS | 200 |
| B9 | 越界章 404（epub/pdf） | PASS | 404 |
| B10 | **删除 epub 书红线** | PASS | 删除后原始 `/tmp/sample.epub` sha/size/mtime 不变 |
| B11 | **删除 pdf 书红线** | PASS | 删除后原始 `/tmp/sample.pdf` sha/size/mtime 不变 |

**C. 单测 + 前端构建**

| # | 用例 | 状态 | 关键结果 |
| --- | --- | --- | --- |
| C1 | `backend.tests.test_increment`（v1.1） | PASS | 12 passed |
| C2 | `backend.tests.test_increment2`（v1.2） | PASS | 8 passed（merge 基础/缓存/force/缺章、position、bookmarks、export done+pending、delete 清 export 守红线） |
| C3 | 前端 `npm run build` | PASS | 933 modules，2.02s，`dist/index.html` + `dist/assets/*` 产出 |
| C4 | 前端新功能接线确认 | PASS | `client.js` 含 exportBookUrl/postPosition/listBookmarks/addBookmark/deleteBookmark；`BookCard` 含「导出整本」；`PlayerDrawer` 含 playback 恢复/进度上报/书签 CRUD |

**汇总**：独立断言共 **34 + 32 + 20(单测) = 86 项全部通过** + 前端构建通过。**无 FAIL，无源码 Bug 路由。**

### 10.3 关键断言证据

- **整本合并大小**：真实双章导出 `173325 B` ≈ 两章分章之和 `173088 B`（偏差 237B，<0.3%，属 mp3 容器头开销，`-c copy` 直拼无重编码损失）。
- **合并零写原始/分章**：导出前后 `data/audio/<id>/0.mp3`、`1.mp3` 的 `st_size` 与 `st_mtime` 逐项比对**完全一致**（A7）；`merge.py` 仅读 audio 副本、仅写 `data/export/<id>.mp3`（tmp+`os.replace` 原子落盘）。
- **断点持久化**：`POST /position {chapter:1,time:30.0}` → 重读 `Book.playback` 仍为 `{current_chapter:1,current_time:30.0}`（A3/A4），随 `books.json` 原子落盘。
- **书签**：增→查（1 条）→删→查（0 条）全链路正确（A9 / C2 `test_bookmarks_crud`）。
- **删除清 export + 红线**：删除后 `data/export/<id>.mp3` 消失、`data/audio/<id>/` 消失、列表不含该书；而 `original_path` 指向的原始 txt/epub/pdf 的 sha256/size/mtime **全程不变**（A10–A12、B10–B11）。

### 10.4 与 v1.1 回归结论

- txt 分章生成（e2e3 A1–A2）、epub/pdf 提取与导入（B1–B6）、按章音频流 + Range 206（B7–B9）、删除递归清目录且原始文件不动（B10–B11）**全部通过**，确认 v1.1 能力在 v1.2 下**无退化**。
- 单测 `test_increment`（12）与 `test_increment2`（8）全绿，覆盖章节切分、提取、按章生成、端点、合并、断点、书签、删除清 export。

### 10.5 发现项（非源码功能 Bug）

**🟡 FINDING#3（规格偏离 · 供主理人/PM 决策，不路由工程师）**
- 标题：书签 200 上限行为偏离 PRD/架构措辞。
- PRD `BMK-002` 与 `ARCHITECTURE_INCREMENT2.md` §4.2 写明「超限返回错误（如 code=4001）」。实际 `backend/main.py:add_bookmark` 为「追加后超出则静默截断保留最新 200 条」，**不返回错误**；前端 `PlayerDrawer.jsx:223` 有 `bookmarks.length >= BOOKMARK_LIMIT` 拦截，UI 侧已阻止超额新增。
- 判定：**功能不破坏**（上限事实上被守住，无数据溢出/崩溃）；仅为后端返回语义与文档措辞不一致。建议二选一：把后端改为超限返回 4001 错误，或把 PRD/架构措辞修正为「静默保留最新 200」。QA 未改动业务代码。

### 10.6 最终判定

✅ **PASS（v1.2 全部交付并经验证）**
- 新增三项能力（合并导出整本、断点续听持久化、手动书签）+ 删除清 export 扩展，**真实 edge-tts 端到端 34/34 + 独立回归 32/32 + 单测 20/20 全通过**。
- **红线守住**：导入/导出/删除各阶段，用户原始 txt/epub/pdf 的 sha256/size/mtime 均不變；合并只读分章副本、零写入；删除覆盖 audio/books/export 数据且绝不触碰原始文件。
- 全量回归确认 v1.1 能力不退化；前端构建通过，新功能已接线。
- 仅 1 项规格偏离（FINDING#3，低优先级，建议 PM 决策对齐措辞），无源码 Bug 需回派。

---

## 十一、增量三（v1.3 局域网/手机访问）测试结论 · QA 独立复测

> 测试对象：v1.3 新增能力（后端绑定 0.0.0.0 + 网络访问信息端点 + 二维码 + 可选访问口令）。
> 测试方式：真实运行后端（uvicorn 绑定 0.0.0.0）+ `requests` 真实 HTTP 调用；前端 `npm run build`；`start.sh` 受控 dry-run。
> 测试轮次：**第 1 轮（16 核心 + 18 回归 + 20 单测 + 前端构建 + start.sh 全部通过，无需第 2 轮）**。
> 网络：edge-tts 7.3.1 真实可达（微软语音服务握手成功），真实生成双章中文 mp3。

### 11.1 测试环境

| 项 | 值 |
| --- | --- |
| OS / Python | Linux / Python 3.11.1（venv `.venv`） |
| 后端 | edge-tts 7.3.1；`requests`/`pytest`/`httpx` 已装；ffmpeg 系统级可用 |
| 启动（核心） | `LISTENBOOK_PORT=8022 ACCESS_TOKEN=secret nohup python backend/run.py`（后台） |
| 启动（口令关闭） | `LISTENBOOK_PORT=8023 ACCESS_TOKEN= nohup python backend/run.py` |
| 启动（LAN_IP 兜底） | `LISTENBOOK_PORT=8024 LISTENBOOK_LAN_IP=10.0.0.99 ACCESS_TOKEN=secret nohup python backend/run.py` |
| `/api/health` | 三实例均 HTTP 200 ✅ |
| 监听确认 | `ss -ltnp` 显示 `0.0.0.0:8022`（非 127.0.0.1） |
| 测试脚本 | `/tmp/qa_lan_test.py`（核心 16 项）、`/tmp/qa_regress.py`（回归 18 项，真实 edge-tts） |

### 11.2 新增用例清单（v1.3 专属）

**A. 局域网 / 口令核心（端口 8022，ACCESS_TOKEN=secret，16 项）**

| # | 用例 | 状态 | 关键结果 |
| --- | --- | --- | --- |
| A1 | `/api/network/info` 免 token 200 | PASS | code=0，含 data |
| A2 | info 含 `access_url`（http:// 前缀） | PASS | `http://172.24.0.22:8022` |
| A3 | info `access_token_required=true` | PASS | `true` |
| A4 | info 含 `lan_ip`/`port`（port=8022） | PASS | lan_ip=172.24.0.22, port=8022 |
| A5 | `lan_ip` 非回环 | PASS | `172.24.0.22`（非 127/0） |
| A6 | `/api/books` 无 token → 401（body 含 code/message） | PASS | 401, code=401, msg="需要访问口令" |
| A7 | `/api/books?token=secret` → 200 | PASS | 200 |
| A8 | `/api/books` Header `X-Access-Token:secret` → 200 | PASS | 200 |
| A9 | 错误 token → 401 | PASS | 401 |
| A10 | 静态根 `/` → 200（不被中间件拦截） | PASS | 200, text/html |
| A11 | `/api/health` 免 token → 200 | PASS | 200 |
| A12 | 章节音频 `?token=` → 404（网关放行，非 401） | PASS | 404（非 401 拦截） |
| A13 | 章节音频 Header token → 404（放行） | PASS | 404 |
| A14 | 整本导出 `?token=` → 404（放行） | PASS | 404 |
| A15 | 章节音频无 token → 401 | PASS | 401 |
| A16 | 监听 `0.0.0.0:8022`（非 127.0.0.1） | PASS | `ss` 显示 `0.0.0.0:8022` |

**B. 边界场景（2 项）**

| # | 用例 | 状态 | 关键结果 |
| --- | --- | --- | --- |
| B1 | 口令关闭（8023，ACCESS_TOKEN=空）：`/api/books` 无 token → 200 | PASS | 200（全开） |
| B2 | `LISTENBOOK_LAN_IP=10.0.0.99` 兜底：info 返回该 IP | PASS | lan_ip=10.0.0.99, access_url=http://10.0.0.99:8024 |

**C. 全量回归（v1.1/v1.2 不退化，真实 edge-tts，18 项）**

| # | 用例 | 状态 | 关键结果 |
| --- | --- | --- | --- |
| C1 | 导入双章 txt（code0 / chapter_count=2） | PASS | 真实分章 2 章 |
| C2 | `original_path` 仅 basename（不存绝对路径） | PASS | `回归样本.txt` |
| C3 | 轮询生成至 done（真实 TTS） | PASS | status=done |
| C4 | **红线①**：导入后原始文件 sha/size/mtime 不变 | PASS | 一致 |
| C5 | 断点 `POST /position` | PASS | code=0 |
| C6 | 断点持久化（重读 Book） | PASS | chapter=1, time=30.5 落盘 |
| C7 | 书签增 | PASS | code=0 |
| C8 | 书签查（1 条） | PASS | count=1 |
| C9 | 书签删（后 0 条） | PASS | count=0 |
| C10 | 整本导出 200 audio/mpeg | PASS | 200, audio/mpeg |
| C11 | 导出大小≈两章之和（<1%） | PASS | export=71949 B, sum=71712 B |
| C12 | 导出后源分章零改动（size+mtime） | PASS | 一致 |
| C13 | 删除后列表不含该书 | PASS | 排除 |
| C14 | 删除清 `audio/<id>/` 目录 | PASS | 已删 |
| C15 | 删除清 `books/<id>.txt` | PASS | 已删 |
| C16 | 删除清 `export/<id>.mp3` | PASS | 已删 |
| C17 | **红线②**：删除后原始文件仍原样存在 | PASS | sha/size/mtime 一致 |
| C18 | 既有能力无退化（导入/生成/导出/断点/书签/删除） | PASS | 全链通过 |

**D. 单测 + 前端构建 + start.sh**

| # | 用例 | 状态 | 关键结果 |
| --- | --- | --- | --- |
| D1 | `backend.tests.test_increment`（v1.1） | PASS | 12 passed |
| D2 | `backend.tests.test_increment2`（v1.2） | PASS | 8 passed |
| D3 | 前端 `npm install && npm run build` | PASS | 1011 modules，2.93s，`dist/*` 产出（含新依赖 `qrcode`） |
| D4 | `bash -n start.sh` 语法检查 | PASS | 通过 |
| D5 | `start.sh --token secret` dry-run 打印局域网 URL | PASS | 打印 `手机访问地址：http://172.24.0.22:8000`；含二维码/告警逻辑（`--token` 解析、有 token 不告警、无 token 告警、二维码优先 qrencode 否则 venv `python -m qrcode` 否则仅打印 URL 降级） |

**汇总**：核心 16 + 边界 2 + 回归 18 + 单测 20 + 前端构建 1 + start.sh 2 = **59 项全部通过**。无 FAIL，无源码 Bug 路由。

### 11.3 关键断言证据

- **0.0.0.0 监听**：`ss -ltnp | grep 8022` → `LISTEN ... 0.0.0.0:8022 ... users:(("python",pid=196973,...))`；本机 `http://localhost:8022` 与 `http://127.0.0.1:8022` 同端口均可访问（同源托管验证通过）。
- **network/info 免 token**：无 `X-Access-Token`/无 `?token=` 直接 200，`data={lan_ip,port,access_url,access_token_required}`，结构与信封 `{code:0,data,message}` 一致。
- **口令双通道**：`/api/books` 经 `?token=secret` 与 Header `X-Access-Token:secret` 均 200；错误/缺失 → 401（信封 `{code:401,data:null,message:"需要访问口令"}`）。
- **媒体流放行**：带 token 的章节音频 `/chapters/{idx}/audio` 与整本导出 `/export`（不存在的 book id）返回 **404 而非 401**，证明网关对受保护媒体/下载路径的双通道 token 校验已放行（未触发 401 拦截）；无 token 的媒体则返回 401。
- **口令关闭**：`ACCESS_TOKEN=` 空时 `/api/books` 无 token 直接 200（全开），与架构「空口令即跳过校验」一致。
- **LAN_IP 兜底**：`LISTENBOOK_LAN_IP=10.0.0.99` 时 info 直接采用该值，证明多网卡/NAT 场景可用 env 人工指定。
- **前端构建**：`npm run build` 1011 modules 转为生产包，`dist/index.html` + `dist/assets/*` 产出，依赖新增 `qrcode@^1.5.3` 已安装并打包（终端二维码与面板渲染依赖满足）。
- **start.sh 语法/逻辑**：`bash -n` 通过；`--token` 参数解析→`export ACCESS_TOKEN`；启动后 `curl /api/network/info` 取 lan_ip/port 打印「手机访问地址」；含终端二维码（qrencode/venv qrcode 降级）与无口令告警逻辑。

### 11.4 全量回归结论（v1.1/v1.2 不退化）

- 真实 edge-tts 双章生成、按章音频端点、合并导出整本（大小≈两章之和、源分章零改动）、断点续听持久化、书签 CRUD、删除清 app 数据（audio/books/export）**全部通过**。
- **红线守住**：导入后、删除后，用户原始 `/tmp/origin/回归样本.txt` 的 sha256/size/mtime **全程不变**；合并只读分章副本、零写入；删除覆盖 app 数据目录且绝不触碰原始文件。
- 既有单测 `test_increment`（12）+ `test_increment2`（8）全绿，覆盖章节切分/提取/按章生成/端点/合并/断点/书签/删除清 export。

### 11.5 发现项（非源码 Bug）

无新增源码缺陷，无规格偏离（v1.3 实现与 `PRD_INCREMENT3.md`/`ARCHITECTURE_INCREMENT3.md` 一致：白名单 `/api/health`+`/api/network/info`、双通道 token、0.0.0.0 默认绑定、`ACCESS_TOKEN` 为空关闭、前端 `client.js` 自动注入与 `NetworkInfo.jsx` 二维码+口令、`start.sh --token` 均符合设计）。

### 11.6 最终判定

✅ **PASS（v1.3 全部交付并经验证）**
- 局域网/手机访问三项核心能力（0.0.0.0 绑定、网络访问信息端点、可选访问口令 + 双通道校验）真实运行 **16/16 + 边界 2/2 全通过**；监听确认为 `0.0.0.0`；`network/info` 免 token；口令双通道（Header/Query）与媒体流放行均验证；口令关闭场景与 `LISTENBOOK_LAN_IP` 兜底均正确。
- **红线守住**：导入/导出/删除各阶段，用户原始文件 sha256/size/mtime 均不变；删除仅清 app 数据目录。
- 全量回归 18/18 通过，确认 v1.1/v1.2 能力无退化；既有单测 20/20 全绿；前端构建通过（含 `qrcode`）；`start.sh` 语法与局域网 URL/二维码/告警逻辑齐备。
- **无源码 Bug 需回派，无规格偏离**。可交付。
