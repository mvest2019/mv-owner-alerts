@echo off
REM Double-click this. Checks Python, installs pymongo if missing, builds the page if it is
REM absent, starts the local server and opens the browser. Leave this window open; closing it
REM stops the server. The VPN must be up first - ping 10.20.30.1 is the test.
setlocal
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

where python >nul 2>nul
if errorlevel 1 (
  echo Python is not on PATH. Install Python 3.9+ from python.org and re-run this file.
  pause
  exit /b 1
)

python -c "import pymongo" >nul 2>nul
if errorlevel 1 (
  echo Installing pymongo...
  python -m pip install --quiet pymongo
)

if not exist "public\alerts.html" (
  echo Building the alerts page from the owner artifact...
  python tools\build_alerts.py
  if errorlevel 1 (
    echo Build failed - see the messages above.
    pause
    exit /b 1
  )
)

echo.
echo Mineral View - owner Alerts. Close this window to stop the server.
echo.
python server.py
pause
