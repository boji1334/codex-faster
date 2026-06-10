# Contributing

Thanks for helping improve this project.

## Development Setup

Requirements:

- Python 3.9+
- Node.js with `npx`
- Codex desktop app installed locally

Useful commands:

```bash
python -m py_compile patch.py inject_models.py fast_search.py
python patch.py --help
python patch.py --load-sessions
```

On Windows:

```batch
patch.bat
```

On macOS / Linux:

```bash
bash patch.sh --help
```

## Project Boundaries

- Keep machine-specific paths out of source code.
- Prefer environment variables such as `CODEX_PATH` and `CODEX_HOME` for overrides.
- Do not commit extracted Codex app files, `.asar` files, caches, logs, backups, or local session data.
- Do not commit API keys, access tokens, refresh tokens, auth files, or screenshots containing secrets.
- Keep batch/shell launchers ASCII-only to avoid terminal encoding issues.

## Pull Requests

Before opening a PR:

1. Run Python syntax checks.
2. Verify `patch.py --help`.
3. If touching Windows launchers, verify `patch.bat --help`.
4. If touching session indexing, test with a temporary `CODEX_HOME`.
5. Update README when behavior or user-facing commands change.

## Compatibility Notes

Codex desktop internals can change between releases. Patches should be:

- Idempotent.
- Pattern based where practical.
- Conservative about filesystem deletion.
- Explicit about backup files before writes.
