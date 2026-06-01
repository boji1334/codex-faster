@echo off
REM ============================================================
REM  Codex API Key Unlocker v2.0 - Windows launcher
REM  NOTE: This file is intentionally ASCII-only. A .bat with
REM  non-ASCII (Chinese) text breaks on machines whose OEM code
REM  page differs, because cmd.exe parses the file using the
REM  system code page before chcp takes effect. All Chinese
REM  messages live in patch.py, which controls its own UTF-8 output.
REM ============================================================
setlocal enabledelayedexpansion

REM Make the console UTF-8 so patch.py's Chinese output renders correctly.
chcp 65001 >nul 2>&1
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

echo ============================================================
echo   Codex API Key Unlocker v2.0
echo ============================================================
echo.

REM Suggest (not require) admin so Electron fuses can be written.
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [HINT] If the patch does not take effect, re-run as Administrator.
    echo.
)

REM Check Node.js (patch.py needs npx to unpack asar and write fuses).
where npx >nul 2>&1
if %errorlevel% neq 0 (
    where npx.cmd >nul 2>&1
    if !errorlevel! neq 0 (
        echo [ERROR] npx not found. Please install Node.js: https://nodejs.org
        pause
        exit /b 1
    )
)

REM Resolve a Python command (python / python3 / py).
set "PYTHON="
where python >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON=python"
) else (
    where python3 >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON=python3"
    ) else (
        where py >nul 2>&1
        if !errorlevel! equ 0 set "PYTHON=py"
    )
)
if "!PYTHON!"=="" (
    echo [ERROR] Python not found. Please install: https://python.org
    pause
    exit /b 1
)

REM All logic (kill process / locate install / backup / patch / fuses)
REM lives in patch.py and is cross-platform.
REM To target a non-standard install: set CODEX_PATH=Your\Codex\Dir
!PYTHON! "%~dp0patch.py" %*
set "PATCH_RESULT=!errorlevel!"

echo.
echo ============================================================
if !PATCH_RESULT! equ 0 (
    echo   Done. Launch Codex and log in with API key mode.
    echo   Rollback: !PYTHON! "%~dp0patch.py" --rollback
) else (
    echo   The patch hit a problem. Please check the log above.
)
echo ============================================================
echo.
pause
