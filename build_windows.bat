@echo off
setlocal
cd /d "%~dp0"

if not exist .venv (
  py -3 -m venv .venv
  if errorlevel 1 (
    echo Could not create the virtual environment.
    pause
    exit /b 1
  )
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if not exist models mkdir models
if not exist config.json copy /Y config.example.json config.json >nul

python -m PyInstaller --clean --noconfirm build\LocalFloatAI.spec
if errorlevel 1 (
  echo Build failed. Review the error above.
  pause
  exit /b 1
)

xcopy /E /I /Y models dist\LocalFloatAI\models >nul
copy /Y config.example.json dist\LocalFloatAI\config.example.json >nul
if exist README.md copy /Y README.md dist\LocalFloatAI\README.md >nul

echo.
echo Build complete: dist\LocalFloatAI\LocalFloatAI.exe
echo Put your .gguf file under dist\LocalFloatAI\models\
pause
