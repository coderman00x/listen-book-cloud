# 听书宝 v2.0 云端部署指南

**一句话目标**：把听书宝部署到公网 HTTPS，云端生成**真 mp3**（可选男声），一键**导出到手机**；手机独立完成导入 / 生成 / 导出，电脑可以随时关机。

---

## 0. 部署前先认清两件事

### 0.1 免费层的现实（不粉饰）

| 平台 | 免费情况（2026） | 关键点 |
| --- | --- | --- |
| **Render** | 免费 Web Service **750 小时/月、无需信用卡** | 连 GitHub 自动识别 `Dockerfile`；注入 `$PORT`；健康检查用 `HEAD /`；**15 分钟无流量休眠**（冷启 30–60s）；**无持久磁盘**；出站 25/465/587 端口被封（本应用不用邮件端口，无影响） |
| **Hugging Face Spaces（Docker SDK）** | 免费 CPU、无需信用卡、公网 HTTPS | 仓库根 `README.md` 需带 YAML frontmatter `sdk: docker` / `app_port: 8000`；长时间空闲休眠 |
| **Google Cloud Run** | 免费额度大，但**需绑卡** | scale-to-zero、无状态，同样不持久 |
| **Fly.io / Railway / Koyeb** | 2026 已无真正免费层或需绑卡 | 不作为主推 |
| **自有 VPS / NAS** | 已有机器即可 | `docker compose up -d`，可挂持久卷、**无休眠** |

**免费层共性：会休眠、数据不持久。** 正确用法是「云端生成完 → **立刻导出 mp3 到手机**」。手机存了文件以后，云端重启 / 休眠把 `data/` 清空也无所谓。反过来，把书架长期存在免费层上一定会丢。

### 0.2 红线（铁律，任何部署方式都不变）

应用**只读写自身 `data/` 目录**；`original_path` 只存上传文件名的 basename 用于展示，**绝不访问 / 修改 / 删除用户原始 txt / epub / pdf**。删除书籍只删云端副本、音频与元数据，你电脑或手机里的原文件毫发无损。容器里 `LISTENBOOK_DATA_DIR=/app/data` 指向的仍是「自身数据目录」，只是换成了挂载卷 / 临时盘，**没有放宽红线**。

### 0.3 环境变量速查

| 变量 | 说明 | 默认 |
| --- | --- | --- |
| `PORT` | 容器内 uvicorn 监听端口；Render / Cloud Run / HF 自动注入 | `8000` |
| `ACCESS_TOKEN` | 访问口令，**公网必填** | 空（不启用） |
| `LISTENBOOK_PUBLIC` | `1` 开启公网模式（隐藏内网 IP、显示公网地址） | `0` |
| `LISTENBOOK_PUBLIC_URL` | 公网 HTTPS 地址，如 `https://xxx.onrender.com` | 空（前端回退当前地址） |
| `LISTENBOOK_DATA_DIR` | app 自身数据目录 | `<项目根>/data`（镜像内 `/app/data`） |
| `LISTENBOOK_HOST` | 监听地址 | `0.0.0.0` |

---

## 1. 路径一：Render（推荐，免费、无需信用卡）

1. 把整个项目推到一个 **GitHub 仓库**（含根目录 `Dockerfile`、`render.yaml`、`backend/`、`frontend/`）。
   `.env`、`data/`、`backend/venv/`、`frontend/node_modules/` 已被忽略/排除，别推上去。
2. 登录 Render → **New → Web Service** → 连接 GitHub 并选中该仓库。
3. Render 会**自动检测根目录 `Dockerfile`**（`runtime: docker`）；若用 Blueprint，直接选仓库里的 `render.yaml` 一键创建。Plan 选 **Free**。
4. 在 **Environment** 里设置环境变量（也可在 Blueprint 创建时填 `sync: false` 的项）：
   - **`ACCESS_TOKEN` = 你自己设的强口令（必填！）** —— 不设的话任何人都能打开你的服务疯狂生成音频、占满磁盘；应用此时会在 `/api/health` 返回 `warning` 提醒你。
   - `LISTENBOOK_PUBLIC` = `1`
   - `LISTENBOOK_PUBLIC_URL` = **你自己的** `https://xxx.onrender.com`（创建后 Render 会给出域名，结尾不要带 `/`）
   - `LISTENBOOK_DATA_DIR` = `/app/data`
   - **不要手动设 `PORT`**：Render 自动注入，Dockerfile 的 `CMD` 已用 `${PORT:-8000}` 接住。
5. 点 **Create Web Service**，等镜像构建（首次约几分钟）。健康检查走 `/api/health`，Render 的 `HEAD /` 探活也由应用显式保证 200。
6. 打开公网 HTTPS 地址 → 首次进入会要求**输入访问口令**（口令存在浏览器 localStorage，后续自动携带）。
7. 免费实例 15 分钟没人访问就休眠，下次打开**等 30–60 秒**冷启动。

> 出站邮件端口 25/465/587 被封对本应用没有影响；但 **edge-tts 需要出站访问微软语音服务**，见 §6。

---

## 2. 路径二：Hugging Face Spaces（Docker SDK）

1. 新建 Space，SDK 选 **Docker**，硬件选免费 CPU。
2. 把项目推到该 Space 仓库；并把 **`deploy/hf-space-README.md` 的内容复制到仓库根目录 `README.md`**（覆盖原文件）。该文件 frontmatter 必须是：
   ```yaml
   ---
   title: 听书宝 · 云端听书
   sdk: docker
   app_port: 8000
   ---
   ```
   `app_port: 8000` 要和镜像内 `PORT=8000` 一致，HF 会自动给公网 HTTPS。
3. 在 **Settings → Repository secrets** 里添加 `ACCESS_TOKEN`（必填）；建议同时加 `LISTENBOOK_PUBLIC=1`，可选 `LISTENBOOK_PUBLIC_URL`。
4. 等构建完成 → 打开 Space 公网地址 → 输入口令 → 使用。
5. 免费 Space 长时间空闲也会休眠、数据不持久，同样请「生成完立刻导出到手机」。

---

## 3. 路径三：自有 VPS / NAS（持久、无休眠）

```bash
cd listen-book
cp .env.example .env
# 编辑 .env：至少填 ACCESS_TOKEN；建议 LISTENBOOK_PUBLIC=1 + LISTENBOOK_PUBLIC_URL
docker compose up -d --build
docker compose logs -f          # 看构建/启动日志
docker compose ps              # 等 healthcheck 变成 healthy
```

- 默认 `http://<你的IP>:8000`；`./data` 挂到容器 `/app/data`，**重启不丢书架**。
- 想换宿主端口：在 `.env` 里改 `HOST_PORT`（容器内 `PORT` 会同步跟随）。
- 前面套 Nginx / Caddy 反代即可上 HTTPS；也可直接用 Caddy 自动证书。
- 升级：`git pull && docker compose up -d --build`（卷数据保留）。
- 校验 compose 语法：`docker compose config`（不需要 daemon）。

### 国内网络构建加速（可选，仅国内 VPS / NAS）

国内机器直连官方源（`deb.debian.org` / PyPI / npmjs）可能极慢甚至超时。若 `docker compose up -d --build` 卡在 `apt-get` / `pip install` / `npm install`，在 `.env` 里设 `USE_CN_MIRROR=1` 后重新构建：

```bash
docker compose up -d --build
```

这**只在构建期**把 apt / pip 切到清华镜像、npm 切到 npmmirror，**不影响运行期**，产出的镜像内容与默认构建一致；默认值 `0` 保持官方源不变。**Render / HF Spaces / Cloud Run 等海外平台拉官方源本就是本地高速，请勿开启。** 也可临时单独验证：`docker build --build-arg USE_CN_MIRROR=1 -t listen-book:cn .`。

---

## 4. 手机怎么用（关键：导出后电脑可关）

1. iPhone 用 **Safari**（Android 用 Chrome）打开公网 HTTPS 地址，输入**访问口令**。
2. 点「**＋导入**」，选手机里的 txt / epub / pdf。
3. **等生成完成**（状态变「已完成」）。生成全程在**云端**进行，手机不需要电脑、不需要同一 WiFi，**电脑此时可以关机**。
4. 点书上的「**导出 ▾**」→ 选「**整本 mp3**」或「**分章 zip**」。
5. iPhone 若**自动播放**而不是下载，点右上角「**分享 → 存储到「文件」**」，存到「文件」App。
6. 之后用「文件」App 或任意播放器**离线听**；**导出完成后电脑与云端都不再需要**。
7. 免费层会休眠、重启后云端书架可能清空，但**已导出到手机的 mp3 不受影响**。

---

## 5. 男声怎么选

「设置 → 默认音色」下拉已按性别分组：**女声**（晓晓 / 晓伊 / 晓辰）、**男声**（**云扬（男声）/ 云希（男声）**）。选好保存后，**新导入的书**生效（已生成的书可用「重新生成」换音色）。云扬偏新闻播报、云希偏年轻自然，按喜好挑。

---

## 6. 免费层限制与为什么有些平台跑不了

- **休眠冷启**：15 分钟无流量即休眠，再次访问需等 30–60 秒；生成任务进行中别让页面长时间后台挂着不管。
- **无持久磁盘**：`data/` 在重启 / 休眠 / 重新部署后清空 → **生成完立刻导出 mp3 到手机**，别把云端书架当网盘。
- **edge-tts 依赖出站公网访问微软语音服务**：部分云厂商 IP 段可能被限流返回 **403** → 重试、稍后再试，或**换区域 / 换平台**（如 Render ↔ HF Spaces）；这是外部服务限制，不是应用代码缺陷。
- **GitHub Pages / Vercel / 各类云函数跑不了**：① 它们是静态托管或短时无状态函数，**没有可写持久磁盘**，音频落不了盘；② 有严格**执行时长上限**（几秒~几十秒），而整本 TTS 生成是分钟级**后台队列常驻任务**；③ 无法常驻 uvicorn 进程与提供 Range 音频流。本应用是「有状态 + 长任务 + 需要 ffmpeg」的单体服务，必须用**能常驻的容器**（Render / HF Spaces / Cloud Run / VPS）。

---

## 7. HTTPS 与口令安全

- **HTTPS 由平台提供**（Render / HF Spaces / Cloud Run 自动签发），不用自己配证书；VPS 方案用 Caddy / Nginx 自行反代。
- 口令是**轻量防护**：前端把它存于浏览器 `localStorage`（明文），并通过 `X-Access-Token` 头或 `?token=` 传递，**不是强安全机制**，别当加密或账号体系用；请设一个不重复使用的随机串。口令只拦 `/api/*`，`/api/health` 与 `/api/network/info` 为白名单以便探活和展示。

---

## 8. 故障排查

| 现象 | 原因 / 处理 |
| --- | --- |
| 生成卡住、失败或 403 | edge-tts 出站被限流 → **重试 / 换区域 / 换平台**；查看平台日志 |
| 导出 404 / 409 | 书**尚未生成完成**，或某章音频缺失 → 等「已完成」再导出，必要时「重试」重新生成 |
| 忘记口令 | 到平台**环境变量**里查看 / 重设 `ACCESS_TOKEN`，重设后重启服务，手机端清掉旧口令重新输入 |
| 首次打开很慢 / 502 | 免费层冷启动 → **等 30–60 秒**再刷新 |
| 页面能开但接口 401 | 口令不对或未保存 → 在「手机访问」面板重新输入并保存 |
| 手机显示一串内网 IP | 忘了设 `LISTENBOOK_PUBLIC=1` → 补上后重启；公网模式不会暴露容器内网 IP |
| 重启后书没了 | 免费层无持久磁盘（预期行为）→ 重新导入；已导出的 mp3 仍在手机里 |

---

## 9. 红线声明（再次）

本应用**只读写自身 `data/`**（容器内 `/app/data`），`original_path` 仅保存上传文件的 basename 用于展示，**绝不访问 / 修改 / 删除用户原始 txt / epub / pdf**。删除操作只删云端副本、生成的音频与元数据。云端部署不改变这一约束。
