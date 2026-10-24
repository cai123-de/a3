@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title 财务管理系统 FIN SUITE
cd /d "%~dp0"

set "PORT=8021"
if defined FS_PORT set "PORT=%FS_PORT%"
set "URL=http://127.0.0.1:%PORT%"
set "ENTRY=%URL%/?demo=chenjing#overview"
set "CHECK_ONLY=0"
set "NOBROWSER=0"
if /i "%~1"=="--check" set "CHECK_ONLY=1"
if /i "%~2"=="--check" set "CHECK_ONLY=1"
if /i "%~1"=="--no-browser" set "NOBROWSER=1"
if /i "%~2"=="--no-browser" set "NOBROWSER=1"

echo.
echo  ==========================================================
echo    财务管理系统  FIN SUITE
echo    管理会计口径的经营分析平台
echo  ==========================================================
echo.

rem ---------- 1) 服务是否已在运行 ----------
netstat -ano -p tcp | findstr /c:":%PORT%" | findstr /i "LISTENING" >nul 2>nul
if not errorlevel 1 (
    echo  [运行中] 检测到 %PORT% 端口已有服务在运行
    if "%CHECK_ONLY%"=="1" (
        echo  [检查] 环境检测完成
        exit /b 0
    )
    echo  [打开]   浏览器将打开 %ENTRY%
    start "" "%ENTRY%"
    timeout /t 3 >nul
    exit /b 0
)

rem ---------- 2) 定位 Python 解释器 ----------
set "PY="
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY if exist "%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe" set "PY=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
if not defined PY (
    for %%P in (python.exe) do if not defined PY set "PY=%%~$PATH:P"
)
if not defined PY (
    echo  [错误] 未找到 Python 解释器
    echo         请安装 Python 3.13+ 后重试，或在项目目录下创建 .venv 虚拟环境
    echo.
    pause
    exit /b 1
)
"%PY%" -c "import sys;print(sys.version.split()[0])" >"%TEMP%\fs_pyver.txt" 2>nul
set "PYVER=unknown"
set /p PYVER=<"%TEMP%\fs_pyver.txt"
echo  [环境] Python %PYVER%
echo  [路径] %PY%

rem ---------- 3) 依赖检查 ----------
"%PY%" -c "import fastapi,uvicorn,psycopg2,pydantic" >nul 2>nul
if errorlevel 1 (
    echo  [依赖] 缺少运行依赖，正在安装 requirements.txt ...
    "%PY%" -m pip install -r "%~dp0requirements.txt"
    if errorlevel 1 (
        echo.
        echo  [错误] 依赖安装失败，请手动执行：
        echo         "%PY%" -m pip install -r requirements.txt
        echo.
        pause
        exit /b 1
    )
) else (
    echo  [依赖] fastapi / uvicorn / psycopg2 / pydantic 已就绪
)

rem ---------- 4) 数据库自检 ----------
"%PY%" "%~dp0manage.py" check >"%TEMP%\fs_check.log" 2>&1
if errorlevel 1 (
    echo  [警告] 数据库自检未通过，常见原因：
    echo         - PostgreSQL 服务未启动
    echo         - 实例三库未导入业务数据（先运行 导入实例三.py）
    echo         - 应用表未初始化（先运行 manage.py init）
    echo  ---------- 自检输出 ----------
    type "%TEMP%\fs_check.log"
    echo  --------------------------------
    echo.
) else (
    echo  [数据库] 连接正常，业务表与分析视图就绪
)

if "%CHECK_ONLY%"=="1" (
    echo.
    echo  [检查] 环境检测完成（未启动服务）
    exit /b 0
)

rem ---------- 5) 启动服务并打开浏览器 ----------
echo.
echo  [启动] %URL%
if "%NOBROWSER%"=="0" (
    echo  [提示] 浏览器将在 4 秒后自动打开；关闭本窗口即停止服务
) else (
    echo  [提示] 已跳过自动打开浏览器；关闭本窗口即停止服务
)
echo.

if "%NOBROWSER%"=="0" start "" /b powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 4; Start-Process '%ENTRY%'"

"%PY%" "%~dp0run.py" --port %PORT%

echo.
echo  [已停止] 服务已退出。按任意键关闭窗口。
pause >nul
