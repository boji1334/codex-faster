#!/bin/bash
# Codex API Key 全功能解锁 v2.0 — macOS / Linux 启动器
# 全部逻辑（关闭进程 / 查找安装 / 备份 / 补丁 / fuse / 签名）都在 patch.py 内完成。
set -e

echo "============================================================"
echo "  Codex API Key 全功能解锁 v2.0"
echo "============================================================"
echo ""

# 检查 Node.js（patch.py 需要 npx 解包 asar 并写 fuse）
if ! command -v npx >/dev/null 2>&1; then
    echo "[ERROR] 未找到 npx，请先安装 Node.js: https://nodejs.org"
    exit 1
fi

# 解析 Python 命令
PYTHON=""
if command -v python3 >/dev/null 2>&1; then
    PYTHON="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON="python"
else
    echo "[ERROR] 未找到 Python 3，请先安装。"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 如需指定非标准安装路径，运行前先: export CODEX_PATH=/path/to/Codex.app
"$PYTHON" "$SCRIPT_DIR/patch.py" "$@"

echo ""
echo "============================================================"
echo "  Codex API Key 全功能解锁 — 完成"
echo "============================================================"
echo ""
echo "  启动 Codex，使用 API key 模式登录即可。"
echo "  如需回滚: $PYTHON \"$SCRIPT_DIR/patch.py\" --rollback"
echo ""
