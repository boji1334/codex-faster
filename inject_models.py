#!/usr/bin/env python3
"""Refresh Codex models_cache.json from the configured OpenAI-compatible relay."""

import copy
import json
import os
import re
import shutil
import sys
import urllib.request


USER_HOME = os.path.expanduser("~")
CODEX_HOME = os.path.abspath(os.path.expanduser(os.environ.get("CODEX_HOME", os.path.join(USER_HOME, ".codex"))))
MODELS_CACHE = os.path.join(CODEX_HOME, "models_cache.json")
AUTH_JSON = os.path.join(CODEX_HOME, "auth.json")
CONFIG_TOML = os.path.join(CODEX_HOME, "config.toml")


def load_api_config():
    """Read base_url and bearer token from Codex config files."""
    api_key = ""
    api_base = ""

    if os.path.exists(CONFIG_TOML):
        try:
            with open(CONFIG_TOML, "r", encoding="utf-8") as f:
                cfg = f.read()
            urls = re.findall(r'base_url\s*=\s*["\']([^"\']+)["\']', cfg)
            if urls:
                api_base = urls[0].rstrip("/")
            tokens = re.findall(r'(?:experimental_bearer_token|bearer_token)\s*=\s*["\']([^"\']+)["\']', cfg)
            if tokens:
                api_key = tokens[0]
        except Exception as e:
            print(f"[WARN] Failed to read config.toml: {e}")

    if not api_key and os.path.exists(AUTH_JSON):
        try:
            with open(AUTH_JSON, "r", encoding="utf-8") as f:
                auth = json.load(f)
            api_key = auth.get("OPENAI_API_KEY", "")
        except Exception as e:
            print(f"[WARN] Failed to read auth.json: {e}")

    if not api_base:
        print(f"[ERROR] Missing base_url in {CONFIG_TOML}")
        print('  Example: base_url = "https://your-relay.example.com"')
        sys.exit(1)

    if not api_key:
        print(f"[ERROR] Missing bearer token in {CONFIG_TOML} or OPENAI_API_KEY in {AUTH_JSON}")
        print('  Example: bearer_token = "sk-..."')
        sys.exit(1)

    return api_key, api_base


def model_display_name(slug):
    return slug.replace("-", " ").replace("_", " ").title()


def main():
    api_key, api_base = load_api_config()
    print("[INFO] API key loaded; value is hidden.")
    print(f"[INFO] Relay: {api_base}")

    try:
        req = urllib.request.Request(
            f"{api_base}/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            proxy_models = json.loads(resp.read()).get("data", [])
    except Exception as e:
        print(f"[ERROR] Failed to query relay models: {e}")
        sys.exit(1)

    proxy_slugs = {m.get("id") for m in proxy_models if isinstance(m, dict) and m.get("id")}
    print(f"[INFO] Relay models: {len(proxy_slugs)}")

    if not os.path.exists(MODELS_CACHE):
        print(f"[ERROR] Missing models cache: {MODELS_CACHE}")
        print("  Start Codex at least once, then rerun this tool.")
        sys.exit(1)

    try:
        with open(MODELS_CACHE, "r", encoding="utf-8") as f:
            cache = json.load(f)
    except Exception as e:
        print(f"[ERROR] Failed to read models_cache.json: {e}")
        sys.exit(1)

    models = cache.get("models")
    if not isinstance(models, list) or not models:
        print("[ERROR] models_cache.json does not contain a usable models list.")
        sys.exit(1)

    existing = {m.get("slug") or m.get("id") or m.get("model") for m in models if isinstance(m, dict)}
    new_slugs = sorted(proxy_slugs - existing)
    print(f"[INFO] Existing cached models: {len(existing)}")
    print(f"[INFO] Models to add: {len(new_slugs)}")

    if not new_slugs:
        print("[SKIP] All relay models already exist in the cache.")
        return

    template = models[0]
    for slug in new_slugs:
        new_model = copy.deepcopy(template)
        for key, value in list(new_model.items()):
            if isinstance(value, str) and value in existing:
                new_model[key] = slug
        new_model["slug"] = slug
        new_model["id"] = slug
        new_model["model"] = slug
        new_model["display_name"] = model_display_name(slug)
        new_model["displayName"] = new_model["display_name"]
        new_model["description"] = f"Model: {slug}"
        new_model["hidden"] = False
        new_model["visibility"] = "list"
        new_model["supported_in_api"] = True
        models.append(new_model)
        print(f"  + {slug}")

    backup = MODELS_CACHE + ".bak"
    if not os.path.exists(backup):
        shutil.copy2(MODELS_CACHE, backup)
        print(f"[INFO] Backup created: {backup}")

    try:
        with open(MODELS_CACHE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[ERROR] Failed to write models_cache.json: {e}")
        sys.exit(1)

    print(f"[DONE] Total cached models: {len(models)}")


if __name__ == "__main__":
    main()
