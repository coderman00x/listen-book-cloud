---
title: 听书宝 · 云端听书
emoji: 🎧
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 8000
---

# 听书宝（Hugging Face Spaces / Docker SDK 模板）

> **使用方法**：把本文件的**全部内容**复制到 Space 仓库**根目录的 `README.md`**
> （覆盖原有 README）。`sdk: docker` 让 HF 用仓库根的 `Dockerfile` 构建，
> `app_port: 8000` 与镜像内 `PORT=8000` 保持一致，HF 会自动提供公网 HTTPS。

## 部署前必做

1. 新建 Space 时选 **Docker** SDK，并把整个项目（含根目录 `Dockerfile`、
   `backend/`、`frontend/`）推到该 Space 仓库。
2. 在 Space 的 **Settings → Repository secrets** 里添加：
   - `ACCESS_TOKEN`：必填，公网访问口令。不设则任何人都能调用你的服务生成音频。
   - `LISTENBOOK_PUBLIC`：设为 `1`，让「手机访问」面板显示公网地址而非容器内网 IP。
   - `LISTENBOOK_PUBLIC_URL`：可留空，前端会回退到当前页面地址；
     也可填 `https://<你的用户名>-<space名>.hf.space`。
3. 等待构建完成后打开 Space 的公网 HTTPS 地址，输入访问口令即可使用。

## 使用与限制

- 手机浏览器打开 Space 地址 → 导入 txt/epub/pdf → 等生成完成 →
  点「导出 ▾」下载整本 mp3 或分章 zip → iPhone 点「分享 → 存储到文件」→ 离线听。
- 免费 CPU Space 长时间空闲会休眠；**云端数据不持久**，重启后书架可能清空，
  所以生成完请**立刻导出 mp3 到手机**，手机里存好的文件不受影响。
- edge-tts 需要出站访问微软语音服务；若某些云厂商 IP 段被限流返回 403，
  请重试或更换部署区域 / 平台。
- 完整说明见仓库内 `DEPLOY.md`。
