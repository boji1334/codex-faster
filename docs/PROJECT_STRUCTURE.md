# Project Structure

```text
codex-faster/
├─ patch.py
├─ patch.bat
├─ uninstall.bat
├─ patch.sh
├─ inject_models.py
├─ fast_search.py
├─ tests/
│  └─ test_patch_platform.py
├─ docs/
│  └─ PROJECT_STRUCTURE.md
├─ README.md
├─ CONTRIBUTING.md
├─ SECURITY.md
├─ LICENSE
├─ .gitignore
├─ .gitattributes
└─ .editorconfig
```

## Main Runtime

`patch.py` is the core engine. It handles:

- Platform and installation detection.
- Optional Windows Store copy to `%LOCALAPPDATA%\Codex-boji`.
- ASAR extraction, original backup, patched repack, and launch-structure audit.
- Webview JavaScript patch application.
- Legacy status-bar experiment cleanup.
- Model cache injection from a configured relay.
- `config.toml` feature patching.
- Local session index repair.
- Electron fuse updates and macOS signing.
- Rollback and Windows standalone uninstall.

## Launchers

`patch.bat` is the Windows interactive launcher. It is intentionally ASCII-only because `cmd.exe` parses batch files using the system code page before `chcp` takes effect.

`uninstall.bat` is a Windows convenience launcher for removing the patched standalone copy.

`patch.sh` is the macOS / Linux launcher. It is ASCII-only and uses LF line endings.

## Helper Tools

`inject_models.py` can be used independently to refresh `models_cache.json`.

`fast_search.py` searches extracted Codex webview assets during patch development.

## Tests

`tests/test_patch_platform.py` covers path detection, Windows Store handling, Windows `npx` invocation, idempotent patch behavior, legacy status-bar cleanup, and app package audit helpers.

## Ignored Local Artifacts

The following should not be committed:

- `codex-extract/`
- `__pycache__/`
- `__MACOSX/`
- `.codex/`
- `*.bak`, `*.tmp`, logs
- `.asar`, `.exe`, `.dmg`, `.zip`
- Extracted Codex app files
- Any user config, auth, session, cache, or secret data

## Configuration Overrides

Use `CODEX_PATH` to target a non-standard Codex install.

Use `CODEX_HOME` to target a non-standard Codex config directory. It defaults to `~/.codex`.
