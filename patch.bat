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
set "SELF_ELEVATED=0"
if /I "%~1"=="--elevated" (
    set "SELF_ELEVATED=1"
    shift /1
)

echo ============================================================
echo   Codex API Key Unlocker v2.0
echo ============================================================
echo.

set "PATCH_ARGS=%*"
if "%~1"=="" (
    echo Select an action:
    echo   [1] Install / patch Codex
    echo   [2] Uninstall patched Codex
    echo   [3] Rollback patch only
    echo   [4] Load local sessions
    echo   [5] Sync Store update to Codex-boji
    echo   [6] Exit
    echo.
    choice /c 123456 /n /m "Enter choice [1-6]: "
    if !errorlevel! equ 6 exit /b 0
    if !errorlevel! equ 5 set "PATCH_ARGS=--sync-store"
    if !errorlevel! equ 4 set "PATCH_ARGS=--load-sessions"
    if !errorlevel! equ 3 set "PATCH_ARGS=--rollback"
    if !errorlevel! equ 2 set "PATCH_ARGS=--uninstall"
    if !errorlevel! equ 1 set "PATCH_ARGS="
    echo.
)

REM Suggest (not require) admin so Electron fuses can be written.
net session >nul 2>&1
set "IS_ADMIN=0"
if %errorlevel% equ 0 set "IS_ADMIN=1"
if "!IS_ADMIN!"=="0" if /I not "!PATCH_ARGS!"=="--help" if /I not "!PATCH_ARGS!"=="-h" if /I not "!PATCH_ARGS!"=="/?" (
    if "!PATCH_ARGS!"=="" (
        if not exist "%LOCALAPPDATA%\Codex-boji\resources" if not exist "%LOCALAPPDATA%\CodexStandalone\resources" (
            if "!SELF_ELEVATED!"=="0" (
                echo [INFO] Store installations require Administrator access on first patch.
                echo [INFO] Requesting Administrator permission...
                powershell -NoProfile -ExecutionPolicy Bypass -Command "$bat = '%~f0'; Start-Process -FilePath $bat -ArgumentList '--elevated' -Verb RunAs -WindowStyle Normal"
                if !errorlevel! equ 0 exit /b 0
                echo [ERROR] Administrator elevation was cancelled or failed.
                pause
                exit /b 1
            )
        )
    )
    if /I "!PATCH_ARGS!"=="--sync-store" (
        if "!SELF_ELEVATED!"=="0" (
            echo [INFO] Syncing from Store requires Administrator access.
            echo [INFO] Requesting Administrator permission...
            powershell -NoProfile -ExecutionPolicy Bypass -Command "$bat = '%~f0'; Start-Process -FilePath $bat -ArgumentList @('--elevated','--sync-store') -Verb RunAs -WindowStyle Normal"
            if !errorlevel! equ 0 exit /b 0
            echo [ERROR] Administrator elevation was cancelled or failed.
            pause
            exit /b 1
        )
    )
    echo [HINT] If the patch does not take effect, re-run as Administrator.
    echo.
)

REM Check Node.js only for install/patch. Other actions can run without it.
if /I not "!PATCH_ARGS!"=="--uninstall" if /I not "!PATCH_ARGS!"=="--rollback" if /I not "!PATCH_ARGS!"=="--sync-store" if /I not "!PATCH_ARGS!"=="--load-sessions" if /I not "!PATCH_ARGS!"=="--help" if /I not "!PATCH_ARGS!"=="-h" if /I not "!PATCH_ARGS!"=="/?" (
    where npx >nul 2>&1
    if !errorlevel! neq 0 (
        where npx.cmd >nul 2>&1
        if !errorlevel! neq 0 (
            echo [ERROR] npx not found. Please install Node.js: https://nodejs.org
            pause
            exit /b 1
        )
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
!PYTHON! "%~dp0patch.py" !PATCH_ARGS!
set "PATCH_RESULT=!errorlevel!"

echo.
echo ============================================================
if !PATCH_RESULT! equ 0 (
    if "!PATCH_ARGS!"=="--uninstall" (
        echo   Done. Patched Codex has been removed.
    ) else if "!PATCH_ARGS!"=="--rollback" (
        echo   Done. Patch has been rolled back.
    ) else if "!PATCH_ARGS!"=="--load-sessions" (
        echo   Done. Local session index has been rebuilt.
    ) else if "!PATCH_ARGS!"=="--sync-store" (
        echo   Done. Store Codex has been synced to Codex-boji.
    ) else if "!PATCH_ARGS!"=="--help" (
        echo   Help displayed.
    ) else if "!PATCH_ARGS!"=="-h" (
        echo   Help displayed.
    ) else if "!PATCH_ARGS!"=="/?" (
        echo   Help displayed.
    ) else (
        echo   Done. Launch Codex and log in with API key mode.
        echo   Rollback: !PYTHON! "%~dp0patch.py" --rollback
        echo   Uninstall: !PYTHON! "%~dp0patch.py" --uninstall
        echo   Sync Store: !PYTHON! "%~dp0patch.py" --sync-store
        echo   Load sessions: !PYTHON! "%~dp0patch.py" --load-sessions
    )
) else (
    echo   The patch hit a problem. Please check the log above.
)
echo ============================================================
echo.
pause
