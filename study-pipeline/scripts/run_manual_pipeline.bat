@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

set "PYTHON_EXE=C:\Users\skyhu\AppData\Local\Programs\Python\Python310\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

echo ==============================================
echo   Obsidian Manual Pipeline Runner
echo ==============================================
echo.
echo 1. Run by note or folder path
echo 2. Run chapter synthesis
echo.
set /p MODE=Select mode [1 or 2]:

if "%MODE%"=="1" goto run_path
if "%MODE%"=="2" goto run_chapter

echo.
echo [ERROR] Invalid mode.
goto end

:run_path
echo.
set /p TARGET_PATH=Enter note file path or folder path:
if "%TARGET_PATH%"=="" (
  echo [ERROR] Path is empty.
  goto end
)

echo.
echo [1/2] Running synthesize.py...
"%PYTHON_EXE%" "%SCRIPT_DIR%synthesize.py" "%TARGET_PATH%"
if errorlevel 1 (
  echo.
  echo [ERROR] synthesize.py failed.
  goto end
)

echo.
echo [2/2] Running generate.py...
"%PYTHON_EXE%" "%SCRIPT_DIR%generate.py" "%TARGET_PATH%"
if errorlevel 1 (
  echo.
  echo [ERROR] generate.py failed.
  goto end
)

echo.
echo Done.
goto end

:run_chapter
echo.
set /p SUBJECT_KEY=Enter subject key (example: organic_chem):
set /p CHAPTER_KEY=Enter chapter key (example: ch4):

if "%SUBJECT_KEY%"=="" (
  echo [ERROR] Subject key is empty.
  goto end
)

if "%CHAPTER_KEY%"=="" (
  echo [ERROR] Chapter key is empty.
  goto end
)

echo.
echo Running synthesize.py --chapter ...
"%PYTHON_EXE%" "%SCRIPT_DIR%synthesize.py" --chapter "%SUBJECT_KEY%" "%CHAPTER_KEY%"
if errorlevel 1 (
  echo.
  echo [ERROR] Chapter synthesis failed.
  goto end
)

echo.
echo Done.

:end
echo.
pause
