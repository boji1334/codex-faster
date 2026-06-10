@echo off
REM ============================================================
REM  Codex API Key Unlocker v2.0 - Windows uninstall launcher
REM  ASCII-only batch file. Chinese output lives in patch.py.
REM ============================================================
setlocal enabledelayedexpansion

chcp 65001 >nul 2>&1
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

echo ============================================================
echo   Codex Patched Uninstall
echo ============================================================
echo.

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

!PYTHON! "%~dp0patch.py" --uninstall
set "UNINSTALL_RESULT=!errorlevel!"

echo.
echo ============================================================
if !UNINSTALL_RESULT! equ 0 (
    echo   Done. Patched Codex has been removed.
) else (
    echo   Uninstall hit a problem. Please check the log above.
)
echo ============================================================
echo.
pause
