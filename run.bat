@echo off
setlocal

cd /d "%~dp0"

set "PORT=%~1"
if "%PORT%"=="" set "PORT=8501"

if not exist ".venv\Scripts\python.exe" (
  echo 未找到虚拟环境 .venv。
  echo 请先运行: py -3.12 -m venv .venv
  echo 然后运行: .venv\Scripts\python.exe -m pip install -r requirements.txt
  pause
  exit /b 1
)

if not exist "logs" mkdir "logs"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$listener = Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue; if ($listener) { $listener | Select-Object LocalAddress,LocalPort,OwningProcess | Format-Table -AutoSize; exit 1 }"
if errorlevel 1 (
  echo.
  echo 端口 %PORT% 已被占用，FrameSentry 未启动。
  echo 如果这是另一个 Streamlit 项目，请使用其他端口启动，例如: run.bat 8503
  echo 如果这是旧的 FrameSentry 窗口，请先关闭旧窗口后再运行本脚本。
  pause
  exit /b 1
)

echo 正在启动 FrameSentry 前端...
echo 地址: http://127.0.0.1:%PORT%
echo 日志: logs\streamlit.log
echo.
echo 如需使用其他端口，可运行: run.bat 8503
echo 按 Ctrl+C 可停止服务。
echo.

".venv\Scripts\python.exe" -m streamlit run app.py --server.address 127.0.0.1 --server.port %PORT% 1>>"logs\streamlit.log" 2>>&1

pause
