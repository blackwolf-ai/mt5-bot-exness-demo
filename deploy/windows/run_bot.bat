@echo off
REM Keeps the bot running forever on Windows: restarts it 10s after any crash or /restart.
cd /d "%~dp0\..\.."
if not exist data mkdir data
if not exist .env (
  echo .env not found. Copy .env.example to .env and fill it in.
  pause
  exit /b 1
)
if not exist .venv\Scripts\python.exe (
  echo Creating virtual environment...
  py -3 -m venv .venv || python -m venv .venv
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\python -m pip install -r requirements.txt
)
:loop
echo [%date% %time%] starting bot>> data\supervisor.log
.venv\Scripts\python -m bot.main
set CODE=%errorlevel%
echo [%date% %time%] bot exited with code %CODE%>> data\supervisor.log
if "%CODE%"=="2" (
  echo Configuration problem - check data\bot.log and your .env
  pause
  exit /b 2
)
timeout /t 10 /nobreak >nul
goto loop
