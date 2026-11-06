@echo off
REM 听书宝 listen_book 一键启动脚本（Windows）
REM
REM 行为：
REM   1. 定位项目根目录（脚本所在目录）
REM   2. 若无 .venv 则创建并安装后端依赖
REM   3. 前端：若 frontend\dist 或 frontend\node_modules 不存在则 npm install + build
REM      （已存在则跳过，复用既有产物，二次运行不重复安装/构建）
REM   4. 激活 venv 并在后台启动后端（托管 frontend\dist）
REM   5. 轮询等待 http://localhost:8000 就绪
REM   6. 尝试用默认浏览器打开；若环境无浏览器，仅打印 URL 且不中断
REM
REM 说明：本脚本只在本项目自身的 data\ 目录内读写，绝不触碰用户原始文件。

setlocal
set "ROOT=%~dp0"
cd /d "%ROOT%" || exit /b 1

REM ---- 0. 参数解析（--token xxx → 设置 ACCESS_TOKEN 给后端）----
set "ACCESS_TOKEN_ARG="
:argloop
if "%~1"=="" goto argdone
if /i "%~1"=="--token" (
  set "ACCESS_TOKEN_ARG=%~2"
  shift
  shift
  goto argloop
)
shift
goto argloop
:argdone
if not "%ACCESS_TOKEN_ARG%"=="" (
  set "ACCESS_TOKEN=%ACCESS_TOKEN_ARG%"
)

REM ---- 1. 后端 venv + 依赖 ----
if not exist ".venv" (
  echo ^>^> 创建 Python 虚拟环境 .venv ...
  python -m venv .venv
)

call .venv\Scripts\activate.bat

echo ^>^> 安装后端依赖（backend\requirements.txt）...
pip install -r backend\requirements.txt

REM ---- 2. 前端依赖 + 构建（增量复用） ----
if not exist "frontend\dist" (
  if not exist "frontend\node_modules" (
    echo ^>^> 安装前端依赖并构建 frontend\dist ...
    cd frontend
    call npm install
    call npm run build
    cd ..
  ) else (
    echo ^>^> 检测到 node_modules 已存在，但 dist 缺失，执行构建 ...
    cd frontend
    call npm run build
    cd ..
  )
) else (
  echo ^>^> 检测到 frontend\dist 已存在，跳过前端安装/构建。
)

REM ---- 3. 启动后端（后台） ----
echo ^>^> 启动后端（http://localhost:8000）...
start "listen-book-backend" /min python backend\run.py

REM ---- 4. 等待端口就绪 ----
echo ^>^> 等待服务就绪 ...
set "URL=http://localhost:8000"
set /a "TRIES=0"
:waitloop
curl -s -o nul -m 2 "%URL%/api/health" >nul 2>&1
if %errorlevel%==0 goto opened
set /a "TRIES+=1"
if %TRIES% geq 60 goto opened
timeout /t 1 >nul
goto waitloop

:opened
REM ---- 4.5 打印局域网访问信息（v1.3 增量：手机访问 / 扫码）----
curl -s -m 3 "%URL%/api/network/info" > "%TEMP%\lb_netinfo.json" 2>nul
if exist "%TEMP%\lb_netinfo.json" (
  for /f "delims=" %%a in ('python -c "import sys,json; d=json.load(open(sys.argv[1])); print(d.get('data',{}).get('lan_ip',''))" "%TEMP%\lb_netinfo.json" 2^>nul') do set "LAN_IP=%%a"
  for /f "delims=" %%p in ('python -c "import sys,json; d=json.load(open(sys.argv[1])); print(d.get('data',{}).get('port',''))" "%TEMP%\lb_netinfo.json" 2^>nul') do set "PORT_NUM=%%p"
  for /f "delims=" %%r in ('python -c "import sys,json; d=json.load(open(sys.argv[1])); print(d.get('data',{}).get('access_token_required', False))" "%TEMP%\lb_netinfo.json" 2^>nul') do set "REQ=%%r"
  if not "%LAN_IP%"=="" (
    echo.
    echo ============================================
    echo  手机访问地址：http://%LAN_IP%:%PORT_NUM%
    echo  手机连同一 WiFi 后，扫码或访问此地址即可打开
    echo ============================================
    REM 终端二维码（可选）：优先 qrencode，否则仅打印 URL（不中断）
    where qrencode >nul 2>nul && qrencode -t ANSI "http://%LAN_IP%:%PORT_NUM%" || echo 提示：可安装 qrencode 以在终端打印二维码
    if /i not "%REQ%"=="True" (
      echo ⚠ 未设访问口令，服务对局域网开放，仅在信任 WiFi 下使用。
    )
  )
  del /f /q "%TEMP%\lb_netinfo.json" >nul 2>&1
)

REM ---- 5. 打开浏览器（失败仅打印 URL，不中断） ----
start "" "%URL%" >nul 2>&1 || echo 请手动打开：%URL%
echo ^>^> 听书宝已启动：%URL%

endlocal
