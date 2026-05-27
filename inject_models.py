#!/usr/bin/env python3
"""
从中转站拉取模型列表并注入 models_cache.json
用法: python inject_models.py
需要先在 ~/.codex/config.toml 中配置 base_url 和 bearer_token（或在 auth.json 配置 OPENAI_API_KEY）
"""
import json, shutil, urllib.request, os, re, sys

USER_HOME = os.path.expanduser("~")
MODELS_CACHE = os.path.join(USER_HOME, ".codex", "models_cache.json")
AUTH_JSON = os.path.join(USER_HOME, ".codex", "auth.json")
CONFIG_TOML = os.path.join(USER_HOME, ".codex", "config.toml")


def load_api_config():
    """从 config.toml 或 auth.json 读取 API Key 和 base_url，均不存在则报错退出"""
    api_key = ""
    api_base = ""

    # 1. 尝试从 config.toml 读取 base_url 和 bearer_token
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
            print(f"[WARN] 读取 config.toml 失败: {e}")

    # 2. 从 auth.json 读取 API Key（优先级低于 config.toml 的 bearer_token）
    if not api_key and os.path.exists(AUTH_JSON):
        try:
            with open(AUTH_JSON, "r", encoding="utf-8") as f:
                auth = json.load(f)
            api_key = auth.get("OPENAI_API_KEY", "")
        except Exception as e:
            print(f"[WARN] 读取 auth.json 失败: {e}")

    if not api_base:
        print("[ERROR] 未找到 base_url 配置。")
        print("  请在 ~/.codex/config.toml 中添加:")
        print('    base_url = "https://你的中转站地址"')
        sys.exit(1)

    if not api_key:
        print("[ERROR] 未找到 API Key 配置。")
        print("  请在 ~/.codex/config.toml 中添加:")
        print('    bearer_token = "sk-..."')
        print("  或在 ~/.codex/auth.json 中设置 OPENAI_API_KEY。")
        sys.exit(1)

    return api_key, api_base


def main():
    api_key, api_base = load_api_config()

    print(f"[INFO] API Key: {api_key[:8]}...{api_key[-4:] if len(api_key) > 12 else ''}")
    print(f"[INFO] 中转站: {api_base}")

    # 拉取中转站模型
    try:
        req = urllib.request.Request(
            f"{api_base}/v1/models",
            headers={"Authorization": f"Bearer {api_key}"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            proxy_models = json.loads(resp.read()).get("data", [])
    except Exception as e:
        print(f"[ERROR] 无法连接到中转站: {e}")
        print(f"  请检查 base_url 是否正确，以及网络是否可用。")
        sys.exit(1)

    proxy_slugs = {m["id"] for m in proxy_models if m.get("id")}
    print(f"[INFO] 中转站模型总数: {len(proxy_slugs)} 个")

    # 读取现有缓存
    if not os.path.exists(MODELS_CACHE):
        print(f"[ERROR] 未找到 models_cache.json: {MODELS_CACHE}")
        print("  请先启动 Codex 至少一次，让它生成缓存文件。")
        sys.exit(1)

    try:
        with open(MODELS_CACHE, "r", encoding="utf-8") as f:
            cache = json.load(f)
    except Exception as e:
        print(f"[ERROR] 读取 models_cache.json 失败: {e}")
        sys.exit(1)

    existing_slugs = {m["slug"] for m in cache.get("models", [])}
    print(f"[INFO] 缓存现有模型: {len(existing_slugs)} 个")
    print(f"[INFO] 现有模型: {sorted(existing_slugs)}")

    new_slugs = proxy_slugs - existing_slugs
    print(f"[INFO] 待新增: {len(new_slugs)} 个")

    if not new_slugs:
        print("[SKIP] 所有模型已在缓存中，无需注入")
        return

    if not cache.get("models"):
        print("[ERROR] 缓存中没有现有模型定义，无法生成模板。")
        sys.exit(1)

    # 用第一个模型作为模板
    template = json.loads(json.dumps(cache["models"][0]))

    for slug in sorted(new_slugs):
        new_model = json.loads(json.dumps(template))
        new_model["slug"] = slug
        new_model["display_name"] = slug.replace("-", " ").title()
        new_model["description"] = f"Model: {slug}"
        new_model["visibility"] = "list"
        new_model["supported_in_api"] = True
        new_model["additional_speed_tiers"] = []
        new_model["service_tiers"] = []
        cache["models"].append(new_model)
        print(f"  + {slug}")

    # 备份
    bak = MODELS_CACHE + ".bak"
    if not os.path.exists(bak):
        shutil.copy2(MODELS_CACHE, bak)
        print(f"[INFO] 已备份: {bak}")

    # 写入
    try:
        with open(MODELS_CACHE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[ERROR] 写入 models_cache.json 失败: {e}")
        print("  请以管理员身份运行，或检查文件权限。")
        sys.exit(1)

    print(f"\n[完成] 模型总数: {len(cache['models'])} 个")
    print("重启 Codex 即可看到所有模型！")


if __name__ == "__main__":
    main()
