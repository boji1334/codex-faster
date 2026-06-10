#!/usr/bin/env bash
# Codex API Key Unlocker v2.0 - macOS / Linux launcher
# This file is ASCII-only so it works across terminal encodings.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PATCH_ARGS=("$@")
ACTION="${1:-}"

echo "============================================================"
echo "  Codex API Key Unlocker v2.0"
echo "============================================================"
echo ""

if [[ "$ACTION" != "--rollback" && "$ACTION" != "--load-sessions" && "$ACTION" != "--help" && "$ACTION" != "-h" && "$ACTION" != "/?" ]]; then
    if ! command -v npx >/dev/null 2>&1; then
        echo "[ERROR] npx not found. Please install Node.js: https://nodejs.org"
        exit 1
    fi
fi

PYTHON=""
if command -v python3 >/dev/null 2>&1; then
    PYTHON="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON="python"
else
    echo "[ERROR] Python 3 not found. Please install Python: https://python.org"
    exit 1
fi

set +e
"$PYTHON" "$SCRIPT_DIR/patch.py" "${PATCH_ARGS[@]}"
RESULT=$?
set -e

echo ""
echo "============================================================"
if [[ $RESULT -eq 0 ]]; then
    case "$ACTION" in
        --rollback)
            echo "  Done. Patch has been rolled back."
            ;;
        --load-sessions)
            echo "  Done. Local session index has been rebuilt."
            ;;
        --sync-store)
            echo "  Done. Store Codex has been synced to Codex-boji."
            ;;
        --help|-h|"/?")
            echo "  Help displayed."
            ;;
        *)
            echo "  Done. Launch Codex and log in with API key mode."
            echo "  Rollback: $PYTHON \"$SCRIPT_DIR/patch.py\" --rollback"
            echo "  Load sessions: $PYTHON \"$SCRIPT_DIR/patch.py\" --load-sessions"
            ;;
    esac
else
    echo "  The patch hit a problem. Please check the log above."
fi
echo "============================================================"
exit "$RESULT"
