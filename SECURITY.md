# Security

This project modifies a local Codex desktop installation. Review changes before running them.

## Sensitive Data

Never publish:

- `~/.codex/auth.json`
- `~/.codex/config.toml` when it contains tokens
- `~/.codex/session_index.jsonl`
- `~/.codex/sessions/**`
- `~/.codex/archived_sessions/**`
- Access tokens, refresh tokens, API keys, screenshots, or logs containing secrets

## Reporting Issues

For security-sensitive issues, open a private report if GitHub security advisories are enabled. Otherwise, create a minimal public issue that avoids secrets and private account data.

## Runtime Scope

The scripts are intended to operate on:

- A local Codex installation selected by auto-detection or `CODEX_PATH`
- A Codex config directory selected by `CODEX_HOME` or `~/.codex`
- The Windows standalone copy at `%LOCALAPPDATA%\Codex-boji` when using Store conversion

Deletion paths should remain limited to generated standalone copies, generated shortcuts, temporary test directories, and documented backup files.
