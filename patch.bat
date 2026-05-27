@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ============================================================
echo   Codex API Key 全功能解锁 v2.0
echo ============================================================
echo.

:: Check admin
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARN] 建议以管理员身份运行（右键 - 以管理员身份运行）
    echo.
)

:: Close Codex
echo [1/5] 关闭 Codex...
taskkill /f /im Codex.exe >nul 2>&1
timeout /t 2 /nobreak >nul
echo       已关闭
echo.

:: Check Node.js
echo [2/5] 检查环境...
where npx >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] 未找到 npx，请先安装 Node.js: https://nodejs.org
    pause
    exit /b 1
)
echo       Node.js 已就绪

:: Check Python
where python3 >nul 2>&1
if %errorlevel% neq 0 (
    where python >nul 2>&1
    if %errorlevel% neq 0 (
        echo [ERROR] 未找到 Python，请先安装: https://python.org
        pause
        exit /b 1
    )
    set PYTHON=python
) else (
    set PYTHON=python3
)
echo       Python 已就绪
echo.

:: Find Codex
echo [3/5] 查找 Codex 安装...
set "CODEX_FOUND="
for %%d in (
    "%LOCALAPPDATA%\Programs\Codex"
    "%LOCALAPPDATA%\Codex"
    "%LOCALAPPDATA%\CodexStandalone"
    "%LOCALAPPDATA%\CodexPatched"
    "C:\Program Files\Codex"
    "%LOCALAPPDATA%\OpenAI\Codex"
) do (
    if exist "%%d\resources\app.asar" (
        set "CODEX_FOUND=%%d"
        echo       找到: %%d
        goto :found
    )
)

:: Search deeper
for /r "%LOCALAPPDATA%\Programs" %%f in (Codex.exe) do (
    set "CODEX_DIR=%%~dpf"
    if exist "!CODEX_DIR!resources\app.asar" (
        set "CODEX_FOUND=!CODEX_DIR!"
        echo       找到: !CODEX_DIR!
        goto :found
    )
)

echo [ERROR] 未找到 Codex 安装目录。
echo   请确认 Codex 已通过独立安装包安装（非 Microsoft Store 版）。
echo   下载地址: https://codex.openai.com
pause
exit /b 1

:found
:: Backup (first time only)
if not exist "!CODEX_FOUND!\resources\app.asar.bak" (
    echo [4/5] 备份原始文件...
    copy "!CODEX_FOUND!\resources\app.asar" "!CODEX_FOUND!\resources\app.asar.bak" >nul
    echo       已备份: app.asar.bak
) else (
    echo [4/5] 备份已存在，跳过
)
echo.

:: Run patch
echo [5/5] 执行补丁...
%PYTHON% "%~dp0patch.py"
set "PATCH_RESULT=%errorlevel%"
echo.

:: Disable Electron fuses
if %PATCH_RESULT% equ 0 (
    echo 禁用 Electron 安全熔断器...
    set "CODEX_EXE=!CODEX_FOUND!\Codex.exe"
    if not exist "!CODEX_EXE!" set "CODEX_EXE=!CODEX_FOUND!\codex.exe"

    npx -y @electron/fuses write --app "!CODEX_EXE!" OnlyLoadAppFromAsar=off
    if !errorlevel! neq 0 echo [WARN] fuse OnlyLoadAppFromAsar 设置失败，Codex 可能无法加载修改后的文件，请以管理员身份重试。
    npx -y @electron/fuses write --app "!CODEX_EXE!" EnableEmbeddedAsarIntegrityValidation=off
    if !errorlevel! neq 0 echo [WARN] fuse EnableEmbeddedAsarIntegrityValidation 设置失败，请以管理员身份重试。
    npx -y @electron/fuses write --app "!CODEX_EXE!" GrantFileProtocolExtraPrivileges=off
    if !errorlevel! neq 0 echo [WARN] fuse GrantFileProtocolExtraPrivileges 设置失败。
    npx -y @electron/fuses write --app "!CODEX_EXE!" EnableCookieEncryption=off
    if !errorlevel! neq 0 echo [WARN] fuse EnableCookieEncryption 设置失败。
    echo       完成
)

echo.
echo ============================================================
echo   Codex API Key 全功能解锁 — 完成
echo ============================================================
echo.
echo   启动 Codex，使用 API key 模式登录即可。
echo   如需回滚: %PYTHON% "%~dp0patch.py" --rollback
echo.
pause
