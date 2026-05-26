#!/bin/bash
set -e

echo "============================================================"
echo "  Codex API Key 全功能解锁 v2.0"
echo "============================================================"
echo ""

# Close Codex
echo "[1/5] 关闭 Codex..."
pkill -x Codex 2>/dev/null || true
sleep 2
echo "      已关闭"
echo ""

# Check prerequisites
echo "[2/5] 检查环境..."
command -v npx >/dev/null 2>&1 || { echo "[ERROR] 未找到 npx，请先安装 Node.js"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "[ERROR] 未找到 python3，请先安装 Python 3"; exit 1; }
echo "      Node.js / Python3 已就绪"
echo ""

# Find Codex
echo "[3/5] 查找 Codex 安装..."
CODEX_RESOURCES="/Applications/Codex.app/Contents/Resources"
if [ ! -f "$CODEX_RESOURCES/app.asar" ]; then
    echo "[ERROR] 未找到 Codex 安装目录: $CODEX_RESOURCES"
    echo "  请确认 Codex 已安装到 /Applications/Codex.app"
    exit 1
fi
echo "      找到: $CODEX_RESOURCES"
echo ""

# Backup (first time only)
if [ ! -f "$CODEX_RESOURCES/app.asar.bak" ]; then
    echo "[4/5] 备份原始文件..."
    cp "$CODEX_RESOURCES/app.asar" "$CODEX_RESOURCES/app.asar.bak"
    echo "      已备份: app.asar.bak"
else
    echo "[4/5] 备份已存在，跳过"
fi
echo ""

# Run patch
echo "[5/5] 执行补丁..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$SCRIPT_DIR/patch.py"
echo ""

# Disable Electron fuses
echo "禁用 Electron 安全熔断器..."
npx @electron/fuses write --app /Applications/Codex.app OnlyLoadAppFromAsar=off 2>/dev/null
npx @electron/fuses write --app /Applications/Codex.app EnableEmbeddedAsarIntegrityValidation=off 2>/dev/null
npx @electron/fuses write --app /Applications/Codex.app GrantFileProtocolExtraPrivileges=off 2>/dev/null
npx @electron/fuses write --app /Applications/Codex.app EnableCookieEncryption=off 2>/dev/null
echo "      完成"

# Re-sign
echo "重新签名..."
codesign --force --deep --sign - /Applications/Codex.app
echo "      完成"

echo ""
echo "============================================================"
echo "  Codex API Key 全功能解锁 — 完成"
echo "============================================================"
echo ""
echo "  启动 Codex，使用 API key 模式登录即可。"
echo "  如需回滚: python3 $SCRIPT_DIR/patch.py --rollback"
echo ""
