# 听书宝 v2.0 · Render 逐屏点选指南（纯新手版）

> **这份指南按你在屏幕上真实看到的顺序写**，从上往下照着点即可，不需要懂 Docker、不需要懂后端。
>
> **界面字段名称已动手前核对**（2026 年 11 月，依据 Render 官方文档
> `render.com/docs/web-services`、`render.com/docs/your-first-deploy`、`render.com/docs/docker`）：
> 入口是 Dashboard 的 **+ New → Web Service**，配置页字段叫 **Name / Region / Branch /
> Language / Build Command / Start Command / Root Directory / Compute**，
> **Advanced** 里可设 **Health Check Path** 与环境变量，最后点 **Create Web Service**。
> **若界面改版，以同名标签为准**——找意思一样的那个输入框即可。本文不附截图，也只使用
> 官方文档里出现过的按钮与字段名。

---

## 0. 动手前先认清三件事

1. **别用 `voicebook` 仓库**。你之前部署到 GitHub Pages 的 `voicebook` 是**另一个项目**（零后端 iOS 版），
   跟这个云端版不是一回事。这次必须**新建一个公开 GitHub 仓库**（下面用 `listen-book-cloud` 举例），
   仓库里放的是解压出来的云端版代码。
2. **免费层的现实（不粉饰）**：Render 免费 Web Service **750 小时/月、无需信用卡**；会自动注入 `$PORT`；
   健康检查走 `HEAD /`；**15 分钟没人访问就休眠**（冷启动 30–60 秒）；**没有持久磁盘**，
   重启 / 休眠会清空云端 `data/` 里的书架。
3. **正确用法只有一句**：**云端生成完 → 立刻导出 mp3 到手机**。导出到手机以后，云端休眠、重启、
   书架清空都无所谓，手机里的文件能离线听，**电脑可以关机**。
   反过来，把云端书架当网盘长期存书，一定会丢。

> GitHub Pages / Vercel / 各类云函数**跑不了这个云端版**：没有可写磁盘、有执行时长上限、
> 无法常驻后台生成队列。必须跑在能常驻的容器里（Render 或 HF Spaces）。

---

## 1. 前置：把代码推进一个全新的公开 GitHub 仓库

### 1.1 新建一个公开仓库

打开 github.com → 右上角 **+ → New repository**：

| 你要填的 | 填什么 |
| --- | --- |
| Repository name | `listen-book-cloud`（可自定，但**不要叫 voicebook**） |
| Public / Private | 选 **Public**（Render 免费连公开仓库最省事） |
| Add a README / .gitignore / license | **全部不要勾**（我们要推已有代码，空仓库才不会冲突） |

点 **Create repository**。建好后 GitHub 会显示一个地址，形如
`https://github.com/<你的用户名>/listen-book-cloud.git`，**把它复制下来**（下一步要用）。

### 1.2 解压交付包

把聊天里下载的 **`listen-book-cloud-deploy.zip`** 解压到任意文件夹（例如桌面），
得到一个名为 **`listen-book-cloud`** 的文件夹——**注意文件夹不带 `-deploy`**，
它**已经是 git 仓库、分支为 `main`**，里面有 `Dockerfile`、`render.yaml`、
`backend/`、`frontend/` 等。**不要在这个文件夹里执行 `git init`**，它已经是仓库了。

### 1.3 在哪里敲命令？怎么推？

**终端在哪**：macOS 打开「终端」App；Windows 打开「Git Bash」（装 git 时自带）或 VS Code 的「终端」。
每一行敲完按回车，等它跑完再敲下一行。

在终端里先进入刚解压出来的文件夹（把路径换成你自己的解压位置），然后执行：

```bash
cd ~/Desktop/listen-book-cloud          # 换成你解压出来的文件夹路径
git remote add origin https://github.com/<你的用户名>/listen-book-cloud.git
git push -u origin main
```

- 第一条 `cd` 是**进入文件夹**；第二、三条才是推送。
- `<你的用户名>` 换成 1.1 里 GitHub 地址中的用户名。
- 你已经装好并授权过 git / gh，所以这里不需要再登录；若提示输入账号密码，用 GitHub 的
  用户名 + Personal Access Token（不是登录密码）。
- 推完回到 GitHub 仓库页面刷新，能看到 `Dockerfile`、`backend/`、`frontend/` 就成功了。

> ⚠️ **本步常见坑**：把命令敲在 `/workspace/listen-book` 这个**主项目文件夹**里会失败——
> 那不是 git 仓库，也不要给它 `git init`。命令一定要在**解压出来的那个文件夹**里执行。
> 另外**不要把 `.env`（含口令）、`data/`、`backend/venv/`、`frontend/node_modules/` 推上去**；
> 交付包已经排除了它们，别手动往仓库里加。

---

## 2. 逐屏点选（① → ⑨）

### ① 打开 render.com，用 GitHub 账号登录

浏览器打开 **render.com** → 点 **Get Started / Sign in** → 选 **GitHub** 图标用 GitHub 账号登录。
**不用重新注册、不用填信用卡**。首次会问你是否授权 Render 读取 GitHub 仓库，点同意（Authorize）。
登录后落到 **Dashboard**（控制台首页）。

> ⚠️ **本屏常见坑**：用邮箱注册也能用，但后面还要单独连 GitHub，多一步；**直接用 GitHub 登录最省事**。
> 若界面改版，以同名标签为准。

### ② Dashboard 点 **+ New → Web Service**

Dashboard 右上角点 **+ New**（官方文档也写作 **New +**）→ 下拉里选 **Web Service**。

> ⚠️ **本屏常见坑**：不要选 **Static Site**（静态站点，跑不了后端），也不要选
> **PostgreSQL / Key Value**（那是数据库）。必须选 **Web Service**。

### ③ 连接仓库（Connect repository）

- 在 **Connect a repository / Source** 处选 **Git Provider → GitHub**；若还没连账号，
  点 **Connect / Configure account** 授权 GitHub。
- 在仓库列表里找到并选中 **① 前置里新建的 `listen-book-cloud`**（**不是 voicebook**），点 **Connect**。
- 如果列表里一时找不到，点 **Configure account / refresh** 刷新授权范围后再找。

> ⚠️ **本屏常见坑**：选错仓库（`voicebook`）会导致构建出来的不是这个云端版。
> 认准仓库名 `listen-book-cloud` 再点 **Connect**。若界面改版，以同名标签为准。

### ④ 配置页：逐字段对照填（**最重要的一屏**）

点完 Connect 会展开**服务创建表单**。按下表逐项核对，**没提到的保持默认**：

| 字段标签 | 你该填 / 选什么 | 为什么 |
| --- | --- | --- |
| **Name** | 自定，例如 `listen-book-cloud` | **决定公网域名**：`https://<Name>.onrender.com`；名字被占用时 Render 会加后缀 |
| **Region** | 选离你近的区域 | 访问更快；**edge-tts 若报 403，可回来换区**（见 ⑨） |
| **Branch** | `main` | 交付包分支就是 `main` |
| **Language**（有的界面显示 Runtime / Environment） | **Docker** | 仓库根目录有 `Dockerfile`，**检测到后会自动选 Docker**；没自动选就手动选 **Docker** |
| **Root Directory** | **留空** | `Dockerfile` 就在仓库根目录，不是 monorepo |
| **Build Command** | **留空，不要手填** | 选了 Docker 后由 `Dockerfile` 决定，Render 官方说明构建命令不可定制 |
| **Start Command** | **留空，不要手填** | 由 `Dockerfile` 里的 `CMD` 启动（`uvicorn ... --port ${PORT:-8000}`）；Docker 模式下覆盖启动命令的字段在 Advanced 里叫 **Docker Command**，**本次不要动它** |
| **Compute / Plan**（实例规格） | **Free** | 免费、无需信用卡；750 小时/月 |

> 若仓库根目录还有 `render.yaml`，Render 可能提示按 **Blueprint** 一键创建；
> 两条路建出来的服务配置一致，**任选其一即可**。若用 Blueprint，下面的环境变量里
> `ACCESS_TOKEN`、`LISTENBOOK_PUBLIC_URL` 会要求你手动填（对应 `sync: false`）。
>
> ⚠️ **本屏常见坑**：**手填 Build / Start Command 是最常见的配置错误**——填了 `npm install`
> 或 `uvicorn ...` 反而覆盖 Dockerfile 的正确行为。**这两个框留空**。
> 构建日志里若出现 `apt-get` / `pip install` / `npm install` 很慢甚至超时，是免费层偶发
> 抖动，**重试部署（Manual Deploy → Deploy latest commit）即可**；`USE_CN_MIRROR=1` 只给
> **国内自建 VPS / NAS** 构建加速用，**Render 是海外平台，不要开**。
> 若界面改版，以同名标签为准。

### ⑤ Advanced → Health Check Path

展开 **Advanced**（高级设置），找到 **Health Check Path**，填：

```
/api/health
```

> ⚠️ **本屏常见坑**：不要填 `/` 或 `/health`。后端健康检查端点是 `/api/health`；
> 应用同时显式保证 `HEAD /` 返回 200，供 Render 探活。填错会一直显示部署不健康。

### ⑥ Environment Variables：逐键添加

在 **Environment Variables**（有的版本在 Advanced 里）点 **Add Environment Variable**，
按下面第 3 节的表格**一行一个 Key** 加完。**`PORT` 不要加**。

> ⚠️ **本屏常见坑**：`ACCESS_TOKEN` 是**口令**，只在 Render 这个界面里填，
> **绝对不要写进 `.env` 文件推到 GitHub**（公开仓库谁都看得见）。
> 变量名区分大小写，照表复制粘贴最稳。若界面改版，以同名标签为准。

### ⑦ 点 **Create Web Service**，看构建日志

拉到表单底部点 **Create Web Service**。页面跳到该服务的 **Deploys / Events**，
开始滚构建日志（`npm install` → `docker build` → `apt-get install ffmpeg` → 启动）。

- **首次构建约 5–10 分钟**，免费层可能更久，别关页面、别重复点创建。
- 日志里出现 `Application is live` 之类字样、服务状态变成绿色 **Live** 就成功了。

> ⚠️ **本屏常见坑**：
> - 构建卡在 `apt-get` / `pip` / `npm`：**免费层偶发慢或超时，重试部署**即可，不是代码问题。
> - 刚显示 Live 就打开页面却 **502**：服务还在冷启动，**等 30–60 秒再刷新**。
> - 日志里若反复失败且提示端口，检查是否**误填了 `PORT` 或 `Start Command`**（回 ④ ⑥ 清空）。

### ⑧ 拿到真实域名，回填 `LISTENBOOK_PUBLIC_URL`

在服务页面顶部找到 Render 给的公网地址，形如 `https://<Name>.onrender.com`（若 Name 被占用，
后面会多一段随机字符，**以页面显示的为准**）。

- 打开 `https://<真实域名>/api/health`，应返回一段 JSON，含 `"code":0`。
- 若真实域名和你在 ⑥ 里预填的不一样：回到 **Environment**（环境变量）页，把
  `LISTENBOOK_PUBLIC_URL` 改成真实地址（结尾**不要带 `/`**），保存后 Render 会**自动触发一次重部署**，
  等它重新变 Live。

> ⚠️ **本屏常见坑**：地址结尾**不要加斜杠**，代码会自动去掉，但填错容易看不出问题；
> 改完环境变量一定要等重部署完成再验证。若界面改版，以同名标签为准。

### ⑨ 手机验证（这一步走完，电脑就能关）

1. iPhone 用 **Safari**（Android 用 Chrome）打开 `https://<真实域名>`。
2. 首次会要求**输入访问口令**，填 ⑥ 里设的 `ACCESS_TOKEN`（存在浏览器里，之后自动带上）。
3. 点「**＋导入**」选一本**小 txt**，等状态变成「**已完成**」。
4. 点书上的「**导出 ▾**」→ 选「**整本 mp3**」或「**分章 zip**」→ iPhone 点
   「**分享 → 存储到「文件」**」存到「文件」App → 离线听。**导出完成后电脑可以关机**。

> ⚠️ **本屏常见坑**：
> - **页面能开、接口却 401**：口令没输或输错了 → 在「手机访问」面板重新输入并保存。
> - **生成失败 / 403**：edge-tts 需要出站访问微软语音服务，**云平台 IP 段可能被 403 限流** →
>   重试、稍后再试，或回 ④ 换 **Region**（或改用 `DEPLOY.md` 里的 HF Spaces 路线）。
>   这是外部服务限制，不是应用坏了。
> - **15 分钟没人访问就休眠**：下次打开等 30–60 秒冷启动；**生成完立刻导出 mp3 到手机**，
>   别让页面长时间后台挂着不管。
> - **重启后书架空了**：免费层**没有持久磁盘**，属正常现象，重新导入即可；
>   **已经导出到手机的 mp3 不受影响**。

---

## 3. 环境变量逐键表（⑥ 照抄这张表）

| Key | Value | 必填 | 说明 |
| --- | --- | --- | --- |
| `ACCESS_TOKEN` | 自己设的强口令，例如 `Lb@2026Book` | ✅ | 公网必填；手机首次打开要输入；**不要写进 `.env` 推到 GitHub** |
| `LISTENBOOK_PUBLIC` | `1` | ✅ | 开启公网模式（隐藏容器内网 IP，改显示公网地址） |
| `LISTENBOOK_PUBLIC_URL` | `https://<Name>.onrender.com` | ✅ | 按 ⑧ 部署后拿到的**真实域名**回填，结尾不带 `/` |
| `LISTENBOOK_DATA_DIR` | `/app/data` | 可选 | 镜像内默认已是 `/app/data`，填不填都一样 |
| `PORT` | **留空不填** | — | Render 自动注入；手填反而可能与平台值冲突 |

> 这几个名字都对应后端真实读取的环境变量：`PORT` / `LISTENBOOK_DATA_DIR` /
> `LISTENBOOK_PUBLIC` / `LISTENBOOK_PUBLIC_URL` / `ACCESS_TOKEN`（见 `backend/config.py`），
> `PORT` 与 `LISTENBOOK_DATA_DIR` 也在 `Dockerfile` 的 `ENV` 里兜了默认值。
> 构建期换源用的 `USE_CN_MIRROR` 只在 `.env.example` / `Dockerfile` 里给国内自建机器准备，
> **Render 上不要设置**。

---

## 4. 部署后自检清单（全部打勾才算成功）

- [ ] `https://<域名>/api/health` 返回 200，且 JSON 里 `"code":0`（未设口令时还会带 `warning`，说明该补 `ACCESS_TOKEN`）。
- [ ] `https://<域名>/api/network/info` 显示 `"mode":"public"`，**不出现容器内网 IP**。
- [ ] 「设置 → 默认音色」下拉里能选到「**云扬（男声）／云希（男声）**」。
- [ ] 导入一本小 txt → 状态变「**已完成**」→「**导出 ▾**」→ 能下载**整本 mp3** 或**分章 zip**。
- [ ] iPhone 点「**分享 → 存储到文件**」→ 在「文件」App 里能**离线播放**。
- [ ] 导出完成后**电脑关机**，手机仍能离线听（说明流程真正走通）。

---

**红线（铁律）**：后端只读写自身 `data/` 目录，`original_path` 只存上传文件名的 basename 用于展示，
**绝不访问 / 修改 / 删除你电脑或手机里的原始 txt / epub / pdf**；删除书籍只删云端副本、音频与元数据。
完整备选路径（HF Spaces / 自有 VPS / 故障排查）见 `DEPLOY.md`。
