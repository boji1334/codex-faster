#!/usr/bin/env python3
"""Search extracted Codex webview JavaScript assets during patch development."""

import os
import re
import sys


def resources_candidates():
    override = os.environ.get("CODEX_PATH")
    if override:
        p = os.path.abspath(os.path.expanduser(override))
        yield p
        yield os.path.join(p, "resources")
        yield os.path.join(p, "Contents", "Resources")

    home = os.path.expanduser("~")
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA", "")
        program_files = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        for root in [
            os.path.join(local, "Codex-boji"),
            os.path.join(local, "Programs", "Codex"),
            os.path.join(local, "Codex"),
            os.path.join(local, "OpenAI", "Codex"),
            os.path.join(program_files, "Codex"),
        ]:
            yield os.path.join(root, "resources")
    elif sys.platform == "darwin":
        yield "/Applications/Codex.app/Contents/Resources"
        yield os.path.join(home, "Applications", "Codex.app", "Contents", "Resources")
    else:
        yield "/opt/Codex/resources"
        yield "/usr/lib/codex/resources"
        yield "/usr/share/codex/resources"
        yield os.path.join(home, ".local", "share", "Codex", "resources")


def find_assets_dir():
    for resources in resources_candidates():
        assets = os.path.join(resources, "app", "webview", "assets")
        if os.path.isdir(assets):
            return assets
        if os.path.isfile(os.path.join(resources, "app.asar")):
            print(f"[INFO] Found Codex resources: {resources}")
            print("[WARN] app.asar has not been extracted. Run python patch.py first.")
            sys.exit(1)
    print("[ERROR] Could not find extracted Codex webview assets.")
    print("        Set CODEX_PATH to a Codex app/resources directory if needed.")
    sys.exit(1)


def main():
    query = sys.argv[1] if len(sys.argv) > 1 else "gpt-5.5"
    try:
        pattern = re.compile(query, re.IGNORECASE)
    except re.error:
        pattern = re.compile(re.escape(query), re.IGNORECASE)

    assets_dir = find_assets_dir()
    print(f"Scanning assets: {assets_dir}")
    print(f"Query: {query}\n")

    hits = []
    for root, _, files in os.walk(assets_dir):
        for name in files:
            if not name.endswith(".js"):
                continue
            path = os.path.join(root, name)
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except OSError:
                continue
            matches = list(pattern.finditer(content))
            if matches:
                hits.append((path, len(matches)))

    print(f"Files containing query: {len(hits)}")
    for path, count in sorted(hits, key=lambda item: item[1], reverse=True)[:50]:
        print(f"{os.path.relpath(path, assets_dir)}: {count}")


if __name__ == "__main__":
    main()
