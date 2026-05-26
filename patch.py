#!/usr/bin/env python3
"""
Codex API Key 全功能解锁 — 一键补丁引擎
使 API key 模式拥有与 ChatGPT 账号模式完全相同的功能。
支持版本自动发现，当 Codex 更新后文件名 hash 变化时自动定位目标文件。
"""

import os, glob, re, sys, json, shutil, stat, urllib.request
from pathlib import Path

# ================================================================
# 配置
# ================================================================
PLATFORM = None  # "macos" | "windows" — auto-detected
BASE = None       # webview/assets 路径
CODEX_RESOURCES = None
API_BASE_URL = None
API_KEY = None
USER_HOME = os.path.expanduser("~")
CONFIG_PATH = os.path.join(USER_HOME, ".codex", "config.toml")
MODELS_CACHE = os.path.join(USER_HOME, ".codex", "models_cache.json")

results = {"applied": [], "skipped": [], "failed": []}


def detect_platform():
    global PLATFORM, CODEX_RESOURCES, BASE
    if sys.platform == "darwin":
        PLATFORM = "macos"
        CODEX_RESOURCES = "/Applications/Codex.app/Contents/Resources"
    elif sys.platform == "win32":
        PLATFORM = "windows"
        local_app = os.environ.get("LOCALAPPDATA", "")
        # Search common install locations
        candidates = [
            os.path.join(local_app, "Programs", "Codex"),
            os.path.join(local_app, "Codex"),
            os.path.join(local_app, "CodexStandalone"),
            os.path.join(local_app, "CodexPatched"),
            os.path.join(local_app, "OpenAI", "Codex"),
            r"C:\Program Files\Codex",
        ]
        for c in candidates:
            rp = os.path.join(c, "resources")
            if os.path.isdir(rp) and (os.path.isfile(os.path.join(rp, "app.asar")) or os.path.isfile(os.path.join(rp, "app.asar1"))):
                CODEX_RESOURCES = rp
                break
        if not CODEX_RESOURCES:
            # Try to find any Codex installation
            for base in [local_app, os.path.join(local_app, "Programs")]:
                if not os.path.isdir(base):
                    continue
                for root, dirs, files in os.walk(base):
                    if "Codex.exe" in files and "resources" in dirs:
                        rp = os.path.join(root, "resources")
                        if os.path.isfile(os.path.join(rp, "app.asar")):
                            CODEX_RESOURCES = rp
                            break
                    if CODEX_RESOURCES:
                        break
                if CODEX_RESOURCES:
                    break
        if not CODEX_RESOURCES:
            print("[ERROR] 未找到 Codex 安装目录。")
            print("  请确认 Codex 已通过独立安装包安装（非 Microsoft Store 版）。")
            print(f"  已搜索: {', '.join(candidates)}")
            sys.exit(1)
    else:
        print(f"[ERROR] 不支持的操作系统: {sys.platform}")
        sys.exit(1)

    BASE = os.path.join(CODEX_RESOURCES, "app", "webview", "assets")
    if not os.path.isdir(BASE):
        BASE = None  # will be set after asar extraction
    print(f"[INFO] 平台: {PLATFORM}")
    print(f"[INFO] Codex 目录: {CODEX_RESOURCES}")


def load_config():
    """从 config.toml 读取中转站配置"""
    global API_BASE_URL, API_KEY
    if not os.path.exists(CONFIG_PATH):
        return
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("base_url = "):
            API_BASE_URL = line.split('"')[1] if '"' in line else line.split("=")[1].strip().strip('"')
        if line.startswith("experimental_bearer_token = ") or line.startswith("bearer_token = "):
            API_KEY = line.split('"')[1] if '"' in line else line.split("=")[1].strip().strip('"')


def find_file(pattern, search_keywords=None):
    """通过 glob 模式查找目标文件，支持文件名 hash 变化"""
    if BASE is None:
        return []
    matches = glob.glob(os.path.join(BASE, pattern))
    if matches:
        return matches
    if search_keywords:
        print(f"  未找到 {pattern}，按特征搜索...")
        for f in glob.glob(os.path.join(BASE, "*.js")):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    c = fh.read(1024 * 100)  # read first 100KB
                if all(kw in c for kw in search_keywords):
                    print(f"  -> 发现目标: {os.path.basename(f)}")
                    return [f]
            except:
                pass
    return []


def apply_patch(filepath, name, find_str=None, replace_str=None, find_regex=None, replace_fn=None):
    """应用单个补丁：优先精确匹配，失败则 regex 降级"""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    basename = os.path.basename(filepath)

    # 检查是否已应用
    if replace_str and replace_str in content:
        results["skipped"].append(f"{basename}: {name}")
        print(f"  [SKIP] {name} — 已应用")
        return content

    # 精确匹配
    if find_str and find_str in content:
        content = content.replace(find_str, replace_str, 1)
        results["applied"].append(f"{basename}: {name}")
        print(f"  [OK]   {name}")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return content

    # Regex 模糊匹配
    if find_regex and replace_fn:
        m = re.search(find_regex, content)
        if m:
            old_text = m.group(0)
            new_text = replace_fn(m)
            if old_text != new_text:
                content = content.replace(old_text, new_text, 1)
                results["applied"].append(f"{basename}: {name} (regex)")
                print(f"  [OK]   {name} (regex匹配)")
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(content)
                return content

    results["failed"].append(f"{basename}: {name}")
    print(f"  [FAIL] {name} — 未找到匹配模式")
    return None


# ================================================================
# 模块 0: use-auth — 会话保持（authMethod 伪装为 chatgpt）
# ================================================================
def patch_module_0_session_persist():
    """修改 use-auth 中的 E(e) 函数，使 API Key 模式也返回 chatgpt authMethod。
    这样所有会话都存储在同一身份下，切换登录方式不会丢失会话。"""
    print("\n[模块 0] 会话保持 — use-auth-*.js")
    files = find_file("use-auth-*.js",
                      search_keywords=["authMethod", "apiKey", "chatgpt"])
    if not files:
        print("  [FAIL] 未找到 use-auth-*.js")
        return

    for filepath in files:
        # 补丁 0: authMethod 伪装 — apiKey 也返回 chatgpt
        # 原始格式（无空格）: case`apiKey`:return`apikey`
        apply_patch(filepath,
            name="会话保持（authMethod伪装）",
            find_str="case`apiKey`:return`apikey`",
            replace_str="case`apiKey`:return`chatgpt`",
            find_regex=r'case\s*`apiKey`\s*:\s*return\s*`apikey`',
            replace_fn=lambda m: "case`apiKey`:return`chatgpt`"
        )


# ================================================================
# 模块 1: Fast 模式 — use-is-fast-mode-enabled-*.js
# ================================================================
def patch_module_1_fast_mode():
    print("\n[模块 1] Fast 模式 — use-is-fast-mode-enabled-*.js")
    files = find_file("use-is-fast-mode-enabled-*.js",
                      search_keywords=["authMethod", "canUseFastMode"])
    if not files:
        # Fallback: search permissions-mode-helpers for older versions
        files = find_file("permissions-mode-helpers-*.js",
                          search_keywords=["authMethod", "models.some"])
    if not files:
        print("  [FAIL] 未找到 Fast 模式文件")
        return

    for filepath in files:
        # 补丁 1a: Fast 授权门控 — g(e) 函数
        # 新版 Codex: return!(c?.authMethod!==`chatgpt`||u)
        # 旧版 Codex: return!(r?.authMethod!==`chatgpt`||a)
        apply_patch(filepath,
            name="Fast 授权门控",
            find_str="return!(c?.authMethod!==`chatgpt`||u)",
            replace_str="return true",
            find_regex=r'return!\([a-zA-Z_$]+\?\.authMethod!==`chatgpt`\|\|[a-zA-Z_$]+\)',
            replace_fn=lambda m: "return true"
        )
        # Also try old format
        apply_patch(filepath,
            name="Fast 授权门控 (旧版)",
            find_str="return!(r?.authMethod!==`chatgpt`||a)",
            replace_str="return true",
        )

        # 补丁 1b: Hook 早期返回分支
        # 新版: if(d?.authMethod!==`chatgpt`||g)
        # 旧版: if(i?.authMethod!==`chatgpt`||s)
        apply_patch(filepath,
            name="Fast Hook 早期返回",
            find_str="if(d?.authMethod!==`chatgpt`||g)",
            replace_str="if(false&&d?.authMethod!==`chatgpt`||g)",
            find_regex=r'if\(([a-zA-Z_$]+)\?\.authMethod!==`chatgpt`\|\|([a-zA-Z_$]+)\)\{',
            replace_fn=lambda m: f"if(false&&{m.group(1)}?.authMethod!==`chatgpt`||{m.group(2)}){{"
        )

        # 补丁 1c: 模型可用性检查
        # 新版: b=v?.models.some(m)??!1
        # 旧版: l?.models.some(N)??!1
        apply_patch(filepath,
            name="模型可用性检查",
            find_str="b=v?.models.some(m)??!1",
            replace_str="b=true",
            find_regex=r'[a-zA-Z_$]+\?\.models\.some\([a-zA-Z_$]+\)\?\?!1',
            replace_fn=lambda m: "true"
        )


# ================================================================
# 模块 2: app-main — 插件侧边栏 + i18n
# ================================================================
def patch_module_2_plugins_i18n():
    print("\n[模块 2] 插件侧边栏 + i18n — app-main-*.js")
    files = find_file("app-main-*.js",
                      search_keywords=["pluginsDisabledTooltip", "enable_i18n"])
    if not files:
        print("  [FAIL] 未找到 app-main-*.js")
        return

    for filepath in files:
        # 补丁 2a: 插件侧边栏 — 门控变量 → 0
        # 新版: d?(0,$.jsx)(eo,{tooltipContent:...
        # 旧版: X?(0,$.jsx)(组件,{tooltipContent:...
        apply_patch(filepath,
            name="插件侧边栏解锁",
            find_str=None,
            replace_str=None,
            find_regex=r'([a-zA-Z_$])\?\(0,\$\.jsx\)\([a-zA-Z_$]+,\{tooltipContent:\(0,\$\.jsx\)\([a-zA-Z_$]+,\{id:`sidebarElectron\.pluginsDisabledTooltip`',
            replace_fn=lambda m: m.group(0).replace(m.group(1) + "?", "0?", 1)
        )

        # 补丁 2b: i18n 多语言强制启用
        # Statsig 实验门控在无用户上下文时返回 false
        apply_patch(filepath,
            name="i18n 多语言强制启用",
            find_str=None,
            replace_str=None,
            find_regex=r'([a-zA-Z_$])=\(0,[a-zA-Z_$]+\.useMemo\)\(\(\)=>[a-zA-Z_$]+\?\.get\(`enable_i18n`,!1\),\[[a-zA-Z_$]+\]\)',
            replace_fn=lambda m: f"{m.group(1)}=(0,Q.useMemo)(()=>!0,[n])"
        )


# ================================================================
# 模块 3: check-plugin-availability — 插件连接器
# ================================================================
def patch_module_3_plugin_connector():
    print("\n[模块 3] 插件连接器 — check-plugin-availability-*.js")
    files = find_file("check-plugin-availability-*.js",
                      search_keywords=["connector-unavailable"])
    if not files:
        print("  [FAIL] 未找到 check-plugin-availability-*.js")
        return

    for filepath in files:
        # 补丁 3: 连接器可用性 — false&& 禁用标记
        apply_patch(filepath,
            name="插件连接器解锁",
            find_str="&&(i=`connector-unavailable`)",
            replace_str="&&false&&(i=`connector-unavailable`)",
            find_regex=r'\(([a-zA-Z_$])=`connector-unavailable`\)',
            replace_fn=lambda m: f"false&&({m.group(1)}=`connector-unavailable`)"
        )


# ================================================================
# 模块 4: gradient — 品牌视觉
# ================================================================
def patch_module_4_brand():
    print("\n[模块 4] 品牌视觉 — plugin-auth-*.js / gradient-*.js")
    # 先尝试新版 Codex 的 plugin-auth 文件，再尝试旧版 gradient 文件
    files = find_file("plugin-auth-*.js",
                      search_keywords=["return e!==`chatgpt`", "function e(e){return e!==`chatgpt`}"])
    if not files:
        files = find_file("gradient-*.js",
                          search_keywords=["return e!==`chatgpt`", "function e(e){return e!==`chatgpt`}"])
    if not files:
        print("  品牌视觉检查可能已迁移，搜索所有 JS...")
        for f in glob.glob(os.path.join(BASE, "*.js")):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    c = fh.read(1024 * 100)
                if "function e(e){return e!==`chatgpt`}" in c:
                    files = [f]
                    print(f"  -> 发现目标: {os.path.basename(f)}")
                    break
            except:
                pass
        if not files:
            print("  [SKIP] 当前版本无品牌视觉门控，跳过")
            return

    for filepath in files:
        apply_patch(filepath,
            name="品牌视觉统一",
            find_str="function e(e){return e!==`chatgpt`}",
            replace_str="function e(e){return false}",
            find_regex=r'function\s+([a-zA-Z_$]+)\(\1\)\{return\s+\1!==`chatgpt`\}',
            replace_fn=lambda m: f"function {m.group(1)}({m.group(1)}){{return false}}"
        )


# ================================================================
# 模块 5: annotation-comment-editor-card — 语音输入
# ================================================================
def patch_module_5_voice():
    print("\n[模块 5] 语音输入 — annotation-comment-editor-card-*.js")
    files = find_file("annotation-comment-editor-card-*.js",
                      search_keywords=["authMethod===`chatgpt`", "dictation"])
    if not files:
        print("  [FAIL] 未找到 annotation-comment-editor-card-*.js")
        return

    for filepath in files:
        apply_patch(filepath,
            name="语音输入解锁",
            find_str="n&&t.authMethod===`chatgpt`}",
            replace_str="n&&(t.authMethod===`chatgpt`||t.authMethod===`apikey`)}",
            find_regex=r'([a-zA-Z_$]+)&&([a-zA-Z_$]+)\.authMethod===`chatgpt`',
            replace_fn=lambda m: f"{m.group(1)}&&({m.group(2)}.authMethod===`chatgpt`||{m.group(2)}.authMethod===`apikey`)"
        )


# ================================================================
# 模块 6: use-usage-settings-access — 用量设置
# ================================================================
def patch_module_6_usage():
    print("\n[模块 6] 用量设置 — use-usage-settings-access-*.js")
    files = find_file("use-usage-settings-access-*.js",
                      search_keywords=["chatgpt", "usage"])
    if not files:
        print("  [FAIL] 未找到 use-usage-settings-access-*.js")
        return

    for filepath in files:
        apply_patch(filepath,
            name="用量设置解锁",
            find_str="let r=e===`chatgpt`,i=r&&p(t)",
            replace_str="let r=e===`chatgpt`||e===`apikey`,i=r&&p(t)",
            find_regex=r'let\s+([a-zA-Z_$]+)=([a-zA-Z_$]+)===`chatgpt`',
            replace_fn=lambda m: f"let {m.group(1)}={m.group(2)}===`chatgpt`||{m.group(2)}===`apikey`"
        )







def fetch_user_models():
    """动态获取用户中转站模型列表，如果失败则返回默认经典模型列表"""
    global API_BASE_URL, API_KEY
    
    # 尝试从 auth.json 读取 API Key
    auth_json_path = os.path.join(USER_HOME, ".codex", "auth.json")
    if os.path.exists(auth_json_path):
        try:
            with open(auth_json_path, "r", encoding="utf-8") as f:
                auth_data = json.load(f)
            if "OPENAI_API_KEY" in auth_data:
                API_KEY = auth_data["OPENAI_API_KEY"]
        except Exception as e:
            print(f"  [WARN] 读取 auth.json 失败: {e}")

    # 尝试从 config.toml 解析自定义 Provider 里的 base_url
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg_content = f.read()
            urls = re.findall(r'base_url\s*=\s*["\']([^"\']+)["\']', cfg_content)
            if urls:
                API_BASE_URL = urls[0]
        except Exception as e:
            print(f"  [WARN] 解析 config.toml base_url 失败: {e}")

    # 默认兜底的高保真常见模型列表
    default_backup = [
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
        "o1-preview",
        "o1-mini",
        "o3-mini",
        "gpt-4o-realtime-preview"
    ]

    if not API_BASE_URL or not API_KEY:
        print("  [INFO] 未检测到中转站或 API 密钥，将注入官方经典候选模型")
        return default_backup

    print(f"  [INFO] 正在从您的中转站拉取可用模型: {API_BASE_URL}")
    try:
        req = urllib.request.Request(
            f"{API_BASE_URL.rstrip('/')}/v1/models",
            headers={"Authorization": f"Bearer {API_KEY}"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read()).get("data", [])
        
        # 排除已有的 6 个内置官方核心模型，提取真正需要额外注入的新模型
        existing_builtins = {"gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex", "gpt-5.2", "codex-auto-review"}
        user_slugs = [m["id"] for m in data if m.get("id") and m["id"] not in existing_builtins]
        
        if user_slugs:
            print(f"  [OK] 成功动态获取到 {len(user_slugs)} 个您的专属模型！")
            return user_slugs
        else:
            print("  [INFO] 中转站没有额外的新模型，注入经典候选模型")
            return default_backup
    except Exception as e:
        print(f"  [WARN] 无法从网络拉取模型，将降级注入经典模型列表: {e}")
        return default_backup


# ================================================================
# 模块 7: 前端模型克隆注入 — model-queries-*.js
# ================================================================
def patch_module_7_frontend_models():
    print("\n[模块 7] 前端模型克隆注入 — model-queries-*.js")
    files = find_file("model-queries-*.js",
                      search_keywords=["select:({data:r})", "gpt-5.5"])
    if not files:
        print("  [FAIL] 未找到 model-queries-*.js")
        return

    models_to_inject = fetch_user_models()
    js_array_str = json.dumps(models_to_inject)

    find_str = 'select:({data:r})=>{let i=[],a=new Set(e),o=null;return r.forEach(e=>{if(d?a.has(e.model):!e.hidden){let n=t===`copilot`?[e.supportedReasoningEfforts.find(e=>e.reasoningEffort===`medium`)??{reasoningEffort:`medium`,description:`medium effort`}]:[...e.supportedReasoningEfforts];i.push({...e,supportedReasoningEfforts:n}),e.isDefault&&(o=e)}}),o??=i.find(e=>e.model===n)??null,{models:i,defaultModel:o}}'
    
    replace_str = f'select:({{data:r}})=>{{let i=[];r.forEach(e=>{{i.push({{...e,hidden:false,supportedReasoningEfforts:[...e.supportedReasoningEfforts]}})}});let extraModels={js_array_str};let template=i[0];if(template){{extraModels.forEach(m=>{{if(!i.some(exist=>exist.model===m)){{let newModel={{...template}};for(let key in newModel){{if(typeof newModel[key]==="string"){{if(newModel[key]===template.model||newModel[key]===template.slug){{newModel[key]=m}}else if(newModel[key]===template.displayName||newModel[key]===template.display_name||newModel[key]===`GPT-5.5`){{newModel[key]=m.replace(/-/g," ").replace(/\\b\\w/g,c=>c.toUpperCase())}}}};newModel.model=m;newModel.slug=m;newModel.display_name=m.replace(/-/g," ").replace(/\\b\\w/g,c=>c.toUpperCase());newModel.displayName=newModel.display_name;newModel.isDefault=false;i.push(newModel)}})}});return {{models:i,defaultModel:i.find(e=>e.model===n)||i[0]||null}}'

    # 超强鲁棒性正则模糊匹配，防止未来混淆变量名发生改变
    find_regex = r'select\s*:\s*\(\{\s*data\s*:\s*([a-zA-Z_$]+)\s*\}\)\s*=>\s*\{.*?defaultModel\s*:\s*[a-zA-Z_$]+\s*\}\}'
    
    def replace_fn(m):
        data_var = m.group(1)
        return f'select:({{data:{data_var}}})=>{{let i=[];{data_var}.forEach(e=>{{i.push({{...e,hidden:false,supportedReasoningEfforts:[...e.supportedReasoningEfforts]}})}});let extraModels={js_array_str};let template=i[0];if(template){{extraModels.forEach(m=>{{if(!i.some(exist=>exist.model===m)){{let newModel={{...template}};for(let key in newModel){{if(typeof newModel[key]==="string"){{if(newModel[key]===template.model||newModel[key]===template.slug){{newModel[key]=m}}else if(newModel[key]===template.displayName||newModel[key]===template.display_name||newModel[key]===`GPT-5.5`){{newModel[key]=m.replace(/-/g," ").replace(/\\b\\w/g,c=>c.toUpperCase())}}}};newModel.model=m;newModel.slug=m;newModel.display_name=m.replace(/-/g," ").replace(/\\b\\w/g,c=>c.toUpperCase());newModel.displayName=newModel.display_name;newModel.isDefault=false;i.push(newModel)}})}});return {{models:i,defaultModel:i.find(e=>e.model===n)||i[0]||null}}'

    for filepath in files:
        basename = os.path.basename(filepath)
        # 精准幂等性检查
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        if "extraModels" in content:
            results["skipped"].append(f"{basename}: 前端动态模型克隆注入")
            print(f"  [SKIP] 前端动态模型克隆注入 — 已应用")
            continue

        apply_patch(filepath,
            name="前端动态模型克隆注入",
            find_str=find_str,
            replace_str=replace_str,
            find_regex=find_regex,
            replace_fn=replace_fn
        )


# ================================================================
# 模型注入: 从中转站拉取模型列表，注入 models_cache.json
# ================================================================
def inject_models():
    """从中转站 /v1/models 拉取模型，补充到 Codex 模型列表"""
    print("\n[模块 7] 模型下拉注入")

    if not API_BASE_URL or not API_KEY:
        print("  [SKIP] 未检测到中转站配置，跳过模型注入")
        print("  (启动 Codex 后手动配置 API Key 再重跑脚本即可)")
        return

    print(f"  中转站: {API_BASE_URL}")

    # 获取中转站可用模型
    try:
        req = urllib.request.Request(
            f"{API_BASE_URL.rstrip('/')}/v1/models",
            headers={"Authorization": f"Bearer {API_KEY}"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            proxy_models = json.loads(resp.read()).get("data", [])
        proxy_slugs = {m["id"] for m in proxy_models}
        print(f"  中转站模型: {len(proxy_slugs)} 个")
    except Exception as e:
        print(f"  [WARN] 无法获取中转站模型: {e}")
        print("  将使用本地缓存的模型列表")
        return

    # 读取现有模型缓存
    if not os.path.exists(MODELS_CACHE):
        print("  [WARN] models_cache.json 不存在，跳过")
        return

    with open(MODELS_CACHE, "r", encoding="utf-8") as f:
        cache = json.load(f)

    existing_slugs = {m["slug"] for m in cache.get("models", [])}
    new_models = proxy_slugs - existing_slugs

    if not new_models:
        print(f"  所有 {len(existing_slugs)} 个模型已在列表中，无需注入")
        return

    print(f"  新增模型: {len(new_models)} 个")
    for slug in sorted(new_models):
        print(f"    + {slug}")

    # 为每个新模型创建定义（基于现有模型模板）
    existing_models = cache.get("models", [])
    if not existing_models:
        print("  [WARN] 无现有模型定义，无法生成新模型")
        return

    template = existing_models[0]  # 用第一个模型做模板

    for slug in sorted(new_models):
        new_model = json.loads(json.dumps(template))  # deep copy
        new_model["slug"] = slug
        new_model["display_name"] = slug.replace("-", " ").title()
        new_model["description"] = f"Custom model: {slug}"
        new_model["visibility"] = "list"
        new_model["supported_in_api"] = True
        new_model["additional_speed_tiers"] = []
        new_model["service_tiers"] = []
        cache["models"].append(new_model)

    # 排序：priority 升序
    cache["models"].sort(key=lambda m: m.get("priority", 99))

    # 备份原始文件
    bak = MODELS_CACHE + ".bak"
    if not os.path.exists(bak):
        shutil.copy2(MODELS_CACHE, bak)

    # 写入
    with open(MODELS_CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

    # 锁文件防覆盖
    os.chmod(MODELS_CACHE, stat.S_IREAD | stat.S_IWRITE)

    print(f"  模型总数: {len(cache['models'])} 个")
    print(f"  已备份: {bak}")


# ================================================================
# 补全 config.toml features
# ================================================================
def patch_config():
    """补全 features 配置"""
    print("\n[模块 8] 补全 config.toml")
    if not os.path.exists(CONFIG_PATH):
        print("  [SKIP] config.toml 不存在")
        return

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    # 检查是否已有 [features]
    if "[features]" not in content:
        content += "\n[features]\n"

    features_to_add = {
        "enable_fast": "true",
        "enable_speed_128k": "true",
        "enable_pro": "true",
        "enable_o3_pro": "true",
        "enable_deep_research": "true",
        "enable_codex_cloud": "true",
    }

    updated = False
    for key, val in features_to_add.items():
        if f"{key} = " not in content and f"{key}=" not in content:
            content = content.replace("[features]", f"[features]\n{key} = {val}")
            print(f"  + {key} = {val}")
            updated = True

    if not updated:
        print("  [SKIP] features 已配置完整")
        return

    # 备份
    bak = CONFIG_PATH + ".bak"
    if not os.path.exists(bak):
        shutil.copy2(CONFIG_PATH, bak)

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  已备份: {bak}")


# ================================================================
# 汇总报告
# ================================================================
def print_report():
    print("\n" + "=" * 60)
    print("  补丁报告")
    print("=" * 60)
    total = len(results["applied"]) + len(results["skipped"]) + len(results["failed"])
    print(f"  总计: {total} 个补丁")
    print(f"  成功: {len(results['applied'])} 个")
    print(f"  跳过: {len(results['skipped'])} 个（已应用）")
    print(f"  失败: {len(results['failed'])} 个")

    if results["applied"]:
        print("\n  已应用:")
        for r in results["applied"]:
            print(f"    + {r}")
    if results["skipped"]:
        print("\n  已跳过:")
        for r in results["skipped"]:
            print(f"    - {r}")
    if results["failed"]:
        print("\n  失败:")
        for r in results["failed"]:
            print(f"    ! {r}")


# ================================================================
# 主流程
# ================================================================
def main():
    global BASE, CODEX_RESOURCES

    print("=" * 60)
    print("  Codex API Key 全功能解锁 v2.0")
    print("=" * 60)

    detect_platform()
    load_config()

    # 检查 asar 状态
    asar_path = os.path.join(CODEX_RESOURCES, "app.asar")
    asar1_path = os.path.join(CODEX_RESOURCES, "app.asar1")
    app_dir = os.path.join(CODEX_RESOURCES, "app")

    # app.asar1 存在 = 已经打过补丁，可以直接跳到补丁步骤
    if not os.path.exists(asar_path) and not os.path.exists(asar1_path):
        print(f"\n[ERROR] 未找到 app.asar 或 app.asar1: {CODEX_RESOURCES}")
        print("  请确认 Codex 已正确安装。")
        sys.exit(1)

    # 如果还没提取过
    if not os.path.isdir(app_dir) or not os.path.exists(os.path.join(app_dir, "webview")):
        if not os.path.exists(asar_path):
            print(f"\n[ERROR] app.asar 不存在且 app/ 未就绪，无法继续。")
            sys.exit(1)
        print("\n[准备] 提取 app.asar...")
        import subprocess
        result = subprocess.run(
            ["npx", "@electron/asar", "e", asar_path, app_dir],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            print(f"[ERROR] 提取失败:\n{result.stderr}")
            sys.exit(1)
        print("  提取完成")

    # 重命名 asar（如果还存在）
    if os.path.exists(asar_path) and not os.path.exists(asar1_path):
        os.rename(asar_path, asar1_path)
        print("  已重命名 app.asar -> app.asar1")
    elif os.path.exists(asar1_path):
        print("  app.asar1 已存在，跳过重命名")

    # 设置全局路径
    BASE = os.path.join(app_dir, "webview", "assets")
    if not os.path.isdir(BASE):
        print(f"[ERROR] webview/assets 不存在: {BASE}")
        sys.exit(1)

    # 备份原始 asar（仅首次）
    asar_bak = os.path.join(CODEX_RESOURCES, "app.asar.bak")
    if os.path.exists(asar1_path) and not os.path.exists(asar_bak):
        shutil.copy2(asar1_path, asar_bak)
        print(f"  已备份: {asar_bak}")

    # 执行补丁
    patch_module_0_session_persist()
    patch_module_1_fast_mode()
    patch_module_2_plugins_i18n()
    patch_module_3_plugin_connector()
    patch_module_4_brand()
    patch_module_5_voice()
    patch_module_6_usage()
    patch_module_7_frontend_models()

    # 模型注入
    inject_models()

    # 配置补全
    patch_config()

    # 报告
    print_report()

    if results["failed"] and not results["applied"] and not results["skipped"]:
        print("\n[ERROR] 所有补丁均失败！可能是全新版本，请提交 Issue。")
        sys.exit(1)

    print(f"\n  Codex 全功能解锁完成。启动 Codex 使用 API key 模式登录即可。")
    print(f"  如需回滚，运行: python3 patch.py --rollback\n")


def rollback():
    """回滚补丁"""
    detect_platform()
    asar1_path = os.path.join(CODEX_RESOURCES, "app.asar1")
    asar_path = os.path.join(CODEX_RESOURCES, "app.asar")
    app_dir = os.path.join(CODEX_RESOURCES, "app")
    asar_bak = os.path.join(CODEX_RESOURCES, "app.asar.bak")

    print("回滚补丁...")
    if os.path.isdir(app_dir):
        shutil.rmtree(app_dir)
        print("  已删除 app/ 目录")
    if os.path.exists(asar1_path):
        os.rename(asar1_path, asar_path)
        print("  已恢复 app.asar")
    if os.path.exists(asar_bak):
        print(f"  原始备份保留: {asar_bak}")
    # 恢复 config
    config_bak = CONFIG_PATH + ".bak"
    if os.path.exists(config_bak):
        shutil.copy2(config_bak, CONFIG_PATH)
        print("  已恢复 config.toml")
    # 恢复模型缓存
    models_bak = MODELS_CACHE + ".bak"
    if os.path.exists(models_bak):
        shutil.copy2(models_bak, MODELS_CACHE)
        os.chmod(MODELS_CACHE, stat.S_IREAD | stat.S_IWRITE)
        print("  已恢复 models_cache.json")
    print("回滚完成。")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--rollback":
        rollback()
    else:
        main()
