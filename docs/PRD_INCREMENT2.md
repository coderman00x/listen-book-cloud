# 听书宝（listen_book）· 增量 PRD（v1.2 增强）

> 版本：v1.2 增量 ｜ 作者：许清楚（Xu）· 产品经理 ｜ 语言：简体中文
> 范围：仅描述本次**新增/变更**，既有已定内容（导入/分章/基础播放器/删除红线原则）不在本文重复，详见 `PRD.md` / `ARCHITECTURE.md` / `PRD_INCREMENT.md` / `ARCHITECTURE_INCREMENT.md`。

## 1. 增量目标

在既有分章听书能力之上，新增**合并导出整本 mp3**、**断点续听持久化**、**手动书签**三项能力，让用户「整本带走、关了接着听、随手记位置」。

## 2. 用户故事

1. **作为想把书带走离线听的用户**，我想在已完成生成的书上点「导出整本」，得到按章节顺序合并的单个 mp3 下载，这样无需自己拼几十个分章文件。
2. **作为碎片时间听书的用户**，我想关掉 app 或切到别的书后，下次再点开这本书能自动接着上次的位置继续听，这样不用每次手动找章、拖进度。
3. **作为需要回听重点段落的用户**，我想在播放中随手打个书签（记章节+时间点+标题），并在书签列表里点一下就跳回去，这样能快速回到关键处。
4. **作为谨慎用户**，我想无论导出还是存书签，删除书时都只清 app 内的副本与缓存，绝不碰我的原始 txt/epub/pdf，这样用得安心。

## 3. 增量需求池

> 标注：🔧 后端依赖（Python/FastAPI）｜🎨 前端依赖（React/MUI）

### P0 — 核心（缺失则本次增强不可用）

| 编号 | 描述 | 依赖 | 验收标准 |
| --- | --- | --- | --- |
| EXP-001 | 导出入口：书卡片在 `status=done` 时新增「导出整本」按钮（与「播放/删除」并列）；点击触发下载并显示加载态 | 🎨 | 仅已完成书显示该按钮；点击后按钮进入 loading 直至返回文件；非法/未完成书不显示或点不动 |
| EXP-002 | 后端按章顺序合并：读取 `data/audio/<book_id>/<idx>.mp3`（按 `Book.chapters` 的 index 升序），用 ffmpeg 合并为单个 mp3 返回 | 🔧 | 合并结果与章节顺序一致；合并失败（缺章/损坏）返回明确错误而非崩溃；**只读**分章文件、零写入修改 |
| EXP-003 | 导出下载与缓存：合并产物落 `data/export/<book_id>.mp3`，以 `Content-Disposition: attachment` 触发浏览器下载；后续同书请求命中缓存（产物存在且新于所有分章文件、章节数未变）则直接返回，避免重复合并 | 🔧🎨 | 首次导出产生文件并下载成功；二次导出秒回（不重合并）；断网/中断不影响已存分章文件 |
| EXP-004 | 导出不破坏分章与原始：合并读的是 app 内 `data/audio/` 副本、写的是 `data/export/` 新文件；`data/audio/<book_id>/` 与用户原始文件全程不被改动 | 🔧 | 导出前后 `data/audio/<book_id>/` 各章文件字节/mtime 完全一致；`original_path` 指向文件不受影响 |
| RES-001 | 播放进度上报：播放器在 `timeupdate`（节流，约每 5s）、`pause`、卸载时，将当前「章索引 + 章内秒数」上报后端 | 🎨 | 同一本书多次上报后，后端 `last_position` 反映最近位置；节流不造成频繁请求风暴 |
| RES-002 | 断点持久化：后端提供保存/读取位置的端点，写入 `Book.last_position`（含 `chapter_idx`/`position_sec`/`updated_at`），随 `store.save_book` 落 `books.json` | 🔧 | 位置跨 app 重启仍保留（重新打开 app 后该书的 `last_position` 仍在）；与书元数据一致 |
| RES-003 | 恢复交互：点开某书（playBook）时，若该书有 `last_position` 且对应章音频存在，自动将播放器跳到「该章 + 该秒数」并从该位置播放/停在可续听态 | 🎨 | 再次点开已完成书自动定位到上次位置；章不存在或该书未生成时安全回退到第 0 章 0s，不报错 |
| DEL-003 | 删除清理导出：扩展 `DELETE /api/books/{id}`，在清音频目录与文本副本之外，额外递归删除 `data/export/<book_id>/`（及遗留的 `data/export/<book_id>.mp3`） | 🔧 | 删除后 `data/export/` 下该书相关文件被清除；`original_path` 指向的原始文件仍原样存在 |

### P1 — 重要体验

| 编号 | 描述 | 依赖 | 验收标准 |
| --- | --- | --- | --- |
| BMK-001 | 手动书签：播放中可打书签（记录 `chapter_idx` + `position_sec` + `title`），书签列表可展示、可点击跳转、可删除；书签持久化于 `Book.bookmarks` | 🔧🎨 | 打书签后出现在列表；点击跳转对应章+秒；删除后从列表与持久化中移除；书签随书删除一并清理 |
| EXP-005 | 导出并发保护（可选实现）：对同时多书导出做轻量限流/串行化，避免 ffmpeg 多进程抢占 CPU 导致卡顿 | 🔧 | 多书同时导出时仍能完成，不出现 5xx 雪崩；单书导出性能不受明显影响 |

### P2 — 增强项

| 编号 | 描述 | 依赖 | 验收标准 |
| --- | --- | --- | --- |
| RES-004 | 书架续听提示：卡片在有 `last_position` 时显示「续听 ▸ 第 N 章 mm:ss」小标，并提供「继续」一键定位 | 🎨 | 有断点的书卡片直观提示上次位置；点「继续」等同 RES-003 定位 |
| BMK-002 | 书签上限与排序：单书书签设默认上限（建议 200），超限提示并可按时间/章节排序 | 🔧🎨 | 达到上限后新增被拦截并提示；列表按章节顺序或时间排序可读 |

## 4. 对既有红线的重申与强化

- **红线本质不变**：`original_path` 仅记录（v1.1 起仅存文件名 basename），后端任何路径**绝不读/写/删/移动**用户原始 txt/epub/pdf。`EXPORT_DIR`、`AUDIO_DIR`、`BOOKS_DIR` 全部位于 app 自身 `data/` 目录内。
- **app 数据范围显式扩大**：本次后，app 数据 = `data/audio/<book_id>/`（分章 mp3 副本）+ `data/books/<book_id>.txt`（文本副本）+ `data/export/<book_id>.mp3`（整本导出缓存）+ `data/books.json`/`settings.json`（元数据）。**删除操作必须覆盖全部上述项**（在 v1.1 基础上新增 `data/export/`）。
- **合并导出零写原始**：ffmpeg 的输入仅指向 `data/audio/<book_id>/` 副本，输出仅写入 `data/export/`；无论 `-c copy` 还是重编码，都**不回写、不触碰**分章文件与任何用户文件。
- **建议回归断言**：删除相关单测除断言 `original_path` 文件不变外，新增断言 `data/audio/<book_id>/` 各章在「导出整本」前后字节/mtime 完全一致；以及删除后 `data/export/` 对应项已不存在。

## 5. 待确认 / 风险

1. **各章采样率/码率不一致**：edge-tts 同书各章参数一致，理想可用 `ffmpeg -f concat -i list.txt -c copy` 快速无损拼接；但为稳妥，建议后端先 `ffprobe` 校验各章 `sample_rate`/`channels`/`bit_rate` 是否统一——统一则 `-c copy`，否则用 `-filter_complex "[0:a][1:a]...concat=n=N:v=0:a=1[out]"` 重新编码（统一转 48k mono mp3）以避免 header 不一致导致的爆音/播放器拒播。**需定调：默认 copy、异常回退重编码（推荐）还是一律重编码。**
2. **导出文件是否缓存**：当前方案默认**缓存**于 `data/export/<book_id>.mp3` 并用（分章 mtime + 章节数）做失效判断，避免长书重复合并耗时。需确认：缓存目录是否计入「缓存占用展示/一键清理」（原 CAC-001），以及是否允许用户手动清除某书导出缓存。
3. **多书同时导出**：`EXPORT_DIR` 按 `book_id` 隔离，理论上可并发；但 ffmpeg 重编码较吃 CPU。需定调是否引入全局信号量限流（EXP-005），或对超长书改为「后台合并 + 轮询进度」而非同步阻塞请求。
4. **断点续听在未完成生成时的边界**：仅 `status=done` 的书可安全恢复；若书处于 `generating/pending/failed` 或目标章音频尚未生成，`RES-003` 必须**安全回退**到第 0 章 0s，不得报错或乱跳。需确认：跨章恢复时若中间某章缺失（部分生成）如何处理（跳到首个可用章）。
5. **书签数量上限**：默认上限建议 200 条/书（BMK-002），超出拦截并提示；需定调具体数值与是否提供「超出自动淘汰最旧」策略。
6. **进度上报频率与隐私**：`timeupdate` 节流约 5s + 暂停/卸载上报已足够；需确认是否额外在「切章」时即时上报（避免跨章丢失最后一章位置）。

---

## 附：模型与接口变更要点（供架构参考，非用户可见）

### A. 数据模型增量（`backend/models.py`）

- `Book` 新增：
  - `last_position: Optional[dict] = None` → `{chapter_idx:int, position_sec:float, updated_at:str}`，用于断点续听。
  - `bookmarks: List[Bookmark] = Field(default_factory=list)`（新增 `class Bookmark(BaseModel)`：`id`/`chapter_idx`/`position_sec`/`title`/`created_at`）。
- 其余 `Book` 字段完全保留；两字段带默认值，旧 `books.json` 反序列化不报错。

### B. 配置常量增量（`backend/config.py`）

- 新增 `EXPORT_DIR: Path = DATA_DIR / "export"`，并在 `ensure_dirs()` 中 `mkdir(exist_ok=True)`。

### C. REST 端点新增/变更

| 方法 | 路径 | 说明 | 依赖 |
| --- | --- | --- | --- |
| GET | `/api/books/{id}/export` | 按章合并并下载整本 mp3（带 `data/export/` 缓存）；非 done 书返回 4xx | 🔧🎨 |
| POST | `/api/books/{id}/position` | 请求体 `{chapter_idx, position_sec}`，写 `Book.last_position` 并 `save_book` | 🔧 |
| GET | `/api/books/{id}/bookmarks` | 返回 `Book.bookmarks` | 🔧 |
| POST | `/api/books/{id}/bookmarks` | 请求体 `{chapter_idx, position_sec, title}`，追加书签（受上限约束） | 🔧🎨 |
| DELETE | `/api/books/{id}/bookmarks/{bm_id}` | 删除指定书签 | 🔧 |
| DELETE | `/api/books/{id}` | **改**：额外 `rmtree(EXPORT_DIR/<id>)` + 删遗留 `EXPORT_DIR/<id>.mp3` | 🔧 |

### D. 前端增量要点

- `BookCard.jsx`：done 态增「导出整本」按钮（EXP-001）；可选「续听」提示（RES-004，P2）。
- `PlayerDrawer.jsx`：① 上报进度（RES-001）；② 打开书时读取 `playing.last_position` 自动定位（RES-003）；③ 新增书签打点按钮 + 书签列表弹层（BMK-001，P1）。
- `api/client.js`：新增 `exportBook(id)` / `savePosition(id, chapter_idx, position_sec)` / `getBookmarks(id)` / `addBookmark(id, payload)` / `deleteBookmark(id, bmId)`。
- 续听恢复关键实现：在 `loadedmetadata` 后执行「pending seek」= 将 `audio.currentTime` 设为 `last_position.position_sec`，避免元数据未就绪时 seek 失效。
