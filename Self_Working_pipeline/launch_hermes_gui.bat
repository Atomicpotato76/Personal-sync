@echo off
setlocal EnableDelayedExpansion

cd /d "%~dp0"

set "PYTHON_CMD="
set "NEEDS_BOOTSTRAP=0"

where python >nul 2>nul
if %errorlevel%==0 (
    python -c "import typer, pydantic, sqlalchemy, dotenv" >nul 2>nul
    if !errorlevel!==0 set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD (
    where py >nul 2>nul
    if !errorlevel!==0 (
        py -3 -c "import typer, pydantic, sqlalchemy, dotenv" >nul 2>nul
        if !errorlevel!==0 set "PYTHON_CMD=py -3"
    )
)

if not defined PYTHON_CMD (
    where python >nul 2>nul
    if !errorlevel!==0 set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD (
    where py >nul 2>nul
    if !errorlevel!==0 set "PYTHON_CMD=py -3"
)

if not defined PYTHON_CMD (
    echo [Hermes GUI] Python executable was not found.
    echo Install Python 3.10+ and try again.
    pause
    exit /b 1
)

%PYTHON_CMD% -c "import typer, pydantic, sqlalchemy, dotenv" >nul 2>nul
if not %errorlevel%==0 (
    set "NEEDS_BOOTSTRAP=1"
)

if "%NEEDS_BOOTSTRAP%"=="1" (
    echo [Hermes GUI] Installing required Python packages for this project...
    call %PYTHON_CMD% -m pip install -e .
    if not %errorlevel%==0 (
        echo [Hermes GUI] Dependency install failed.
        pause
        exit /b 1
    )
)

if defined HERMES_GUI_DRY_RUN (
    echo [Hermes GUI] Would run: %PYTHON_CMD% -m apps.cli.main gui
    exit /b 0
)

echo [Hermes GUI] Launching dashboard...
call %PYTHON_CMD% -m apps.cli.main gui
set "EXIT_CODE=%errorlevel%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [Hermes GUI] Launch failed with exit code %EXIT_CODE%.
    echo Check API keys and Python environment, then try again.
    pause
)

exit /b %EXIT_CODE%
