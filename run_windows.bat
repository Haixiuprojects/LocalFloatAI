@echo off
setlocal
cd /d "%~dp0"

if not exist .venv (
  echo Creating virtual environment...
  py -3 -m venv .venv
  if errorlevel 1 (
    echo Python 3.11 or newer is required. Install it from python.org and retry.
    pause
    exit /b 1
  )
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if not exist models mkdir models
if not exist config.json copy /Y config.example.json config.json >nul

echo.
echo Copy a .gguf model into the models folder if you have not done so.
echo Starting LocalFloatAI...
python app\main.py
pause
