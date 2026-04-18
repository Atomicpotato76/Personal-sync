@echo off
setlocal
chcp 65001 >nul

set "ROOT_DIR=%~dp0"
cd /d "%ROOT_DIR%"

set "VENV_PY=%ROOT_DIR%\.venv\Scripts\python.exe"
set "APP_PATH=%ROOT_DIR%scripts\dashboard\app.py"

if exist "%VENV_PY%" (
    echo [INFO] Using virtual environment Python
    "%VENV_PY%" -m streamlit run "%APP_PATH%"
) else (
    echo [INFO] Using system Python
    python -m streamlit run "%APP_PATH%"
)

if errorlevel 1 (
    echo.
    echo [ERROR] Dashboard failed to start.
    echo [HINT] If needed, install dependencies with:
    echo        pip install -r scripts\requirements.txt
    echo        pip install -r scripts\dashboard\requirements.txt
    echo.
)

echo.
pause
