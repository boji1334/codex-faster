---
name: patch-codex-apikey-unlock
description: Patch a local Codex desktop installation so API Key mode can use additional desktop features. Includes Windows Store copy-to-Codex-boji, rollback, uninstall, Store sync, and local session index rebuild.
version: 2.0.0
---

# Codex API Key Unlocker

Use this repository to install, repair, roll back, uninstall, or inspect the Codex API Key desktop patch.

## Boundaries

- This is a local patching tool for a user-controlled Codex desktop installation.
- Do not publish API keys, auth files, session files, logs, screenshots with secrets, extracted app files, or patched binaries.
- Do not modify Microsoft Store app files in place. On Windows, Store builds are copied to `%LOCALAPPDATA%\Codex-boji`.
- Do not reintroduce the abandoned HUD/status-bar/plugin feature unless the project explicitly decides to bring it back.

## Common Commands

```bash
python patch.py
python patch.py --rollback
python patch.py --uninstall
python patch.py --sync-store
python patch.py --load-sessions
python patch.py --help
```

Windows launcher:

```bat
patch.bat
uninstall.bat
```

macOS / Linux launcher:

```bash
bash patch.sh
```

## Development Checks

```bash
python -m py_compile patch.py inject_models.py fast_search.py tests/test_patch_platform.py
python -m unittest discover -s tests
python patch.py --help
```

## Notes For Future Changes

- Keep patch patterns idempotent.
- Prefer feature searches over hard-coded hashed bundle names.
- Keep `.bat` and `.sh` launchers ASCII-only.
- Keep deletion paths bounded to generated standalone copies, temporary directories, backups, and shortcuts.
- Update `README.md`, `docs/PROJECT_STRUCTURE.md`, and tests when behavior changes.
