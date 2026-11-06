#!/usr/bin/env bash
# 听书宝 listen_book 一键启动脚本（Linux / macOS）
#
# 行为：
#   1. 定位项目根目录（脚本所在目录）
#   2. 若无 .venv 则创建并安装后端依赖
#   3. 前端：若 frontend/dist 或 frontend/node_modules 不存在则 npm install + build
#      （已存在则跳过，复用既有产物，二次运行不重复安装/构建）
#   4. 激活 venv 并用 nohup 后台启动后端（托管 frontend/dist）
#   5. 轮询等待 http://localhost:8000 就绪
#   6. 尝试用默认浏览器打开；若环境无浏览器，仅打印 URL 且不中断
#
# 说明：本脚本只在本项目自身的 data/ 目录内读写，绝不触碰用户原始文件。

set -u

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 1

# ---- 0. 参数解析（--token xxx → 导出 ACCESS_TOKEN 给后端）----
ACCESS_TOKEN_ARG=""
while [ $# -gt 0 ]; do
  case "$1" in
    --token)
      ACCESS_TOKEN_ARG="${2:-}"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done
if [ -n "$ACCESS_TOKEN_ARG" ]; then
  export ACCESS_TOKEN="$ACCESS_TOKEN_ARG"
fi

# ---- 1. 后端 venv + 依赖 ----
if [ ! -d ".venv" ]; then
  echo ">> 创建 Python 虚拟环境 .venv ..."
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo ">> 安装后端依赖（backend/requirements.txt）..."
pip install -r backend/requirements.txt

# ---- 2. 前端依赖 + 构建（增量复用） ----
if [ ! -d "frontend/dist" ] || [ ! -d "frontend/node_modules" ]; then
  echo ">> 安装前端依赖并构建 frontend/dist ..."
  ( cd frontend && npm install && npm run build )
else
  echo ">> 检测到 frontend/dist 与 node_modules 已存在，跳过前端安装/构建。"
fi

# ---- 2.5 ffmpeg 软探测（仅告警，不阻断启动）----
# 导出整本依赖 ffmpeg；缺失时仅提示，基础听书不受影响。
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "⚠️ 未检测到 ffmpeg，合并导出整本功能将不可用，请用包管理器安装 ffmpeg"
fi

# ---- 3. 启动后端（后台） ----
echo ">> 启动后端（http://localhost:8000）..."
nohup python backend/run.py > /tmp/listen-book.log 2>&1 &
SERVER_PID=$!

# 优雅退出：终止后端
cleanup() {
  echo ""
  echo ">> 接收到退出信号，正在停止后端 (PID=$SERVER_PID) ..."
  kill "$SERVER_PID" 2>/dev/null || true
}
trap cleanup INT TERM

# ---- 4. 等待端口就绪 ----
echo ">> 等待服务就绪 ..."
URL="http://localhost:8000"
for _ in $(seq 1 60); do
  if curl -s -o /dev/null -m 2 "$URL/api/health"; then
    break
  fi
  sleep 1
done

# ---- 4.5 打印局域网访问信息（v1.3 增量：手机访问 / 扫码）----
NET_INFO=$(curl -s -m 3 "$URL/api/network/info" 2>/dev/null)
if [ -n "$NET_INFO" ]; then
  LAN_IP=$(printf '%s' "$NET_INFO" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('lan_ip',''))" 2>/dev/null)
  PORT_NUM=$(printf '%s' "$NET_INFO" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('port',''))" 2>/dev/null)
  REQ=$(printf '%s' "$NET_INFO" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('access_token_required', False))" 2>/dev/null)
  ACCESS_URL="http://${LAN_IP}:${PORT_NUM}"
  echo ""
  echo "============================================"
  echo " 手机访问地址：$ACCESS_URL"
  echo " 手机连同一 WiFi 后，扫码或访问此地址即可打开"
  echo "============================================"
  # 终端二维码（可选）：优先 qrencode；否则 venv 内 python -m qrcode；均无则仅打印 URL（不中断）
  if command -v qrencode >/dev/null 2>&1; then
    qrencode -t ANSI "$ACCESS_URL" 2>/dev/null || true
  elif python3 -c "import qrcode" >/dev/null 2>&1; then
    python3 -m qrcode "$ACCESS_URL" 2>/dev/null || true
  fi
  # 无口令告警
  if [ "$REQ" != "True" ]; then
    echo "⚠ 未设访问口令，服务对局域网开放，仅在信任 WiFi 下使用。"
  fi
fi

# ---- 5. 打开浏览器（失败仅打印 URL，不中断） ----
if command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$URL" >/dev/null 2>&1 || echo "已在后台启动，请手动打开：$URL"
elif command -v open >/dev/null 2>&1; then
  open "$URL" >/dev/null 2>&1 || echo "已在后台启动，请手动打开：$URL"
elif command -v start >/dev/null 2>&1; then
  start "$URL" >/dev/null 2>&1 || echo "已在后台启动，请手动打开：$URL"
else
  echo "未检测到可用浏览器，请手动打开：$URL"
fi

echo ">> 听书宝已启动：$URL  （日志：/tmp/listen-book.log）"

# 前台等待后端进程，保持脚本存活
wait "$SERVER_PID"
