# 听书宝 v2.0 云端容器镜像（多阶段构建）
#
# 【目录结构约定，不可改】
#   config.BASE_DIR = backend/ 的父目录 = /app
#   -> 数据目录 /app/data；静态站点 /app/frontend/dist
# 所以后端 .py 必须落在 /app/backend/，前端构建产物必须落在 /app/frontend/dist/，
# 否则 StaticFiles 挂载不到页面、数据目录也会跑偏。
#
# 【为什么用 shell 形式的 CMD】
#   exec 形式不会展开 $PORT，而 Render / Cloud Run 会在运行期注入 $PORT，
#   Compose 也通过 environment 传 PORT；用 sh -c 才能让 ${PORT:-8000} 生效。
#   不用 `python backend/run.py`：它内部注入 sys.path 且端口写死读 LISTENBOOK_PORT。
#
# 【构建源：默认官方源，保证海外平台可移植】
#   默认 USE_CN_MIRROR=0 使用官方 apt / PyPI / npm 源；Render / HF Spaces / Cloud Run
#   拉这些源是本地高速，最可移植。USE_CN_MIRROR=1 仅供国内 VPS / NAS 构建加速
#   （清华 apt/pip + npmmirror npm），只在构建期换源，不影响运行期，也不改变默认行为。
ARG USE_CN_MIRROR=0

# ---------- Stage 1：前端构建 ----------
FROM node:22-alpine AS frontend-build
# 顶层 ARG 必须在每个 stage 内重新声明，才能继承默认值或 --build-arg 的值
ARG USE_CN_MIRROR
WORKDIR /fe
COPY frontend/package*.json ./
# 项目虽含 package-lock.json，仍统一用 npm install（兼容 lock 缺失的分支/精简仓库）
# 默认 0 时不切源，保持官方 npm registry
RUN if [ "$USE_CN_MIRROR" = "1" ]; then npm config set registry https://registry.npmmirror.com; fi \
    && npm install
COPY frontend/ ./
RUN npm run build
# 产物：/fe/dist/

# ---------- Stage 2：运行时 ----------
FROM python:3.11-slim
ARG USE_CN_MIRROR
# ffmpeg：整本 mp3 合并 / 分章打包需要（edge-tts 只产出分片 mp3）
# Debian 12+ bookworm 用 /etc/apt/sources.list.d/debian.sources（deb822），也兼容旧 sources.list；
# 默认 0 时官方源路径保持原样，仅 1 时按文件是否存在做 sed 替换，避免 set -e 报错。
RUN if [ "$USE_CN_MIRROR" = "1" ]; then \
        if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
            sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g; s|security.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources; \
        fi; \
        if [ -f /etc/apt/sources.list ]; then \
            sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g; s|security.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list; \
        fi; \
    fi \
    && apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先只拷依赖清单以复用 Docker 层缓存；backend/venv 已被 .dockerignore 排除
COPY backend/requirements.txt ./backend/
RUN if [ "$USE_CN_MIRROR" = "1" ]; then PIP_INDEX="-i https://pypi.tuna.tsinghua.edu.cn/simple"; else PIP_INDEX=""; fi \
    && pip install --no-cache-dir $PIP_INDEX -r backend/requirements.txt

COPY backend/ ./backend/
COPY --from=frontend-build /fe/dist/ ./frontend/dist/

ENV PORT=8000 LISTENBOOK_DATA_DIR=/app/data PYTHONUNBUFFERED=1
RUN mkdir -p /app/data
EXPOSE 8000

# 仅用 Python 标准库探活，跟随运行期 $PORT；不依赖 curl/wget
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 CMD python -c "import os, sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8000') + '/api/health', timeout=3).status == 200 else 1)"

CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
