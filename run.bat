@echo off
setlocal

cd /d "%~dp0"

set "EXIT_CODE=0"
set "PORT=%~1"
if "%PORT%"=="" set "PORT=8501"

if not exist ".venv\Scripts\python.exe" (
  echo Missing virtual environment: .venv
  echo Run first: py -3.12 -m venv .venv
  echo Then run: .venv\Scripts\python.exe -m pip install -r requirements.txt
  set "EXIT_CODE=1"
  goto :done
)

if not exist "logs" mkdir "logs"

".venv\Scripts\python.exe" -m framesentry._port_check "%PORT%"
if errorlevel 2 (
  echo.
  echo Port %PORT% is invalid. Use a number from 1 to 65535.
  set "EXIT_CODE=1"
  goto :done
)
if errorlevel 1 (
  echo.
  echo Port %PORT% is already in use. FrameSentry was not started.
  echo Try another port, for example: run.bat 8503
  echo If an old FrameSentry window is still open, close it and run this file again.
  set "EXIT_CODE=1"
  goto :done
)

echo Starting FrameSentry...
echo URL: http://127.0.0.1:%PORT%
echo Log: logs\streamlit.log
echo.
echo To use another port, run: run.bat 8503
echo Press Ctrl+C to stop the server.
echo.

set "STREAMLIT_SERVER_HEADLESS=true"
set "STREAMLIT_SERVER_SHOW_EMAIL_PROMPT=false"
set "STREAMLIT_BROWSER_GATHER_USAGE_STATS=false"
".venv\Scripts\python.exe" -m streamlit run app.py --server.address 127.0.0.1 --server.port %PORT% 1>>"logs\streamlit.log" 2>&1

set "EXIT_CODE=%ERRORLEVEL%"

:done
echo.
if not "%EXIT_CODE%"=="0" echo FrameSentry exited with code: %EXIT_CODE%
if "%FRAMESENTRY_NO_PAUSE%"=="1" exit /b %EXIT_CODE%
pause
exit /b %EXIT_CODE%
