---
name: patch-codex-apikey-unlock
description: |
  Patch Codex App (macOS/Windows) - API Key 模式全功能解锁。
  使 API key 模式拥有与 ChatGPT 账号模式完全相同的功能，包括：
  Fast/Speed 模式、Plugins 插件、语音输入、用量设置、多语言 i18n、品牌视觉。
  支持版本自动发现，当 Codex 更新后文件名 hash 变化时自动定位目标文件。
version: 2.0.0
---

# Patch Codex App - API Key 模式全功能解锁

## 方案概述

放弃 ChatGPT 账号登录模式，使用 API key 模式并解锁全部功能。
无需配置代理、无需处理 OAuth 路由，只需一次补丁即可获得完整体验。

### 解锁功能清单

| # | 功能 | 原始限制 | 补丁方式 |
|---|------|----------|----------|
| 1 | Fast/Speed 模式授权 | `authMethod !== 'chatgpt'` 时隐藏 | 强制返回 `true` |
| 2 | Fast 模式 Hook 分支 | Hook 提前退出阻止渲染 | `false&&` 禁用条件 |
| 3 | 模型可用性检查 | relay API 缺少 `additionalSpeedTiers` 字段 | 强制返回 `true` |
| 4 | Plugins 侧边栏 | 非 chatgpt 模式禁用 | 门控变量 → `0` |
| 5 | 插件连接器可用性 | API key 模式标记为 `connector-unavailable` | `false&&` 禁用 |
| 6 | 品牌视觉统一 | API key 用户显示不同品牌 | 强制返回 `false` |
| 7 | 语音输入/听写 | 仅 chatgpt 模式 | 扩展为 `chatgpt \|\| apikey` |
| 8 | 用量/计费设置 | 仅 chatgpt 模式 | 扩展为 `chatgpt \|\| apikey` |
| 9 | i18n 多语言 | Statsig 实验门控，API key 无用户上下文时默认关闭 | 强制启用 `!0` |

## 前置要求

- Node.js（用于 npx）
- Python 3

## macOS

### 回滚方法

```bash
cd /Applications/Codex.app/Contents/Resources
rm -rf app
[ -f app.asar1 ] && mv app.asar1 app.asar
[ -f app.asar.bak ] && cp app.asar.bak app.asar
codesign --force --deep --sign - /Applications/Codex.app
echo "已回滚到原始版本"
```

### 一键补丁（macOS）

```bash
# 关闭 Codex
pkill -x Codex 2>/dev/null; sleep 1

cd /Applications/Codex.app/Contents/Resources

# 备份（仅首次）
[ ! -f app.asar.bak ] && cp app.asar app.asar.bak && echo "已备份 app.asar -> app.asar.bak"

# 清理旧补丁
rm -rf app

# Step 1: 提取 asar
npx @electron/asar e ./app.asar app

# Step 2: 重命名 asar（Electron 会自动加载 app/ 文件夹）
mv ./app.asar ./app.asar1

# Step 3: 执行全部补丁
python3 << 'PYTHON'
import os, glob, re, sys, json

# ================================================================
# 配置 - 根据平台调整 base 路径
# ================================================================
PLATFORM = "macos"
if PLATFORM == "macos":
    BASE = "/Applications/Codex.app/Contents/Resources/app/webview/assets"
elif PLATFORM == "windows":
    BASE = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Codex", "resources", "app", "webview", "assets")

# ================================================================
# 补丁定义：每个补丁包含 文件模式、查找策略、替换规则
# 使用 regex 模式实现跨版本兼容（变量名可能变化）
# ================================================================

PATCHES = []
results = {"applied": [], "skipped": [], "failed": []}

def find_file(pattern):
    """通过 glob 模式查找目标文件，支持文件名 hash 变化"""
    matches = glob.glob(os.path.join(BASE, pattern))
    return matches

def apply_patch(filepath, name, find_str, replace_str, find_regex=None, replace_fn=None):
    """
    应用单个补丁。
    优先使用精确字符串匹配 (find_str -> replace_str)。
    如果精确匹配失败，使用 find_regex + replace_fn 做模糊匹配。
    """
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    basename = os.path.basename(filepath)

    # 检查补丁是否已经应用
    if replace_str and replace_str in content:
        results["skipped"].append(f"{basename}: {name} (已应用)")
        print(f"  [SKIP] {name} — 已应用")
        return content

    # 方式 1: 精确字符串匹配
    if find_str and find_str in content:
        content = content.replace(find_str, replace_str, 1)
        results["applied"].append(f"{basename}: {name}")
        print(f"  [OK]   {name}")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return content

    # 方式 2: 正则模糊匹配
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
# 模块 1: permissions-mode-helpers — Fast 模式 (3 个补丁)
# ================================================================
print("\n[模块 1] Fast 模式 — permissions-mode-helpers-*.js")

files = find_file("permissions-mode-helpers-*.js")
if not files:
    # 降级搜索：在所有 JS 中找包含 authMethod + models.some 的文件
    print("  未找到 permissions-mode-helpers-*.js，搜索所有 JS...")
    for f in glob.glob(os.path.join(BASE, "*.js")):
        with open(f, "r", encoding="utf-8") as fh:
            c = fh.read()
        if "authMethod" in c and "models.some" in c:
            files = [f]
            print(f"  -> 发现目标: {os.path.basename(f)}")
            break

for filepath in files:
    # 补丁 1a: Fast 模式授权门控
    # 原始: return!(r?.authMethod!==`chatgpt`||a)  (变量名 r/a 可能变化)
    apply_patch(filepath,
        name="Fast 授权门控",
        find_str="return!(r?.authMethod!==`chatgpt`||a)",
        replace_str="return true",
        find_regex=r'return!\([a-zA-Z_$]+\?\.authMethod!==`chatgpt`\|\|[a-zA-Z_$]+\)',
        replace_fn=lambda m: "return true"
    )

    # 补丁 1b: Hook L() 早期返回分支
    # 原始: if(i?.authMethod!==`chatgpt`||s){  (变量名 i/s 可能变化)
    apply_patch(filepath,
        name="Fast Hook 早期返回",
        find_str="if(i?.authMethod!==`chatgpt`||s){",
        replace_str="if(false&&i?.authMethod!==`chatgpt`||s){",
        find_regex=r'if\(([a-zA-Z_$]+)\?\.authMethod!==`chatgpt`\|\|([a-zA-Z_$]+)\)\{',
        replace_fn=lambda m: f"if(false&&{m.group(1)}?.authMethod!==`chatgpt`||{m.group(2)}){{"
    )

    # 补丁 1c: 模型可用性检查
    # 原始: l?.models.some(N)??!1  (变量名 l/N 可能变化)
    apply_patch(filepath,
        name="模型可用性检查",
        find_str="l?.models.some(N)??!1",
        replace_str="true",
        find_regex=r'[a-zA-Z_$]+\?\.models\.some\([a-zA-Z_$]+\)\?\?!1',
        replace_fn=lambda m: "true"
    )


# ================================================================
# 模块 2: app-main — 插件侧边栏 + i18n (2 个补丁)
# ================================================================
print("\n[模块 2] 插件侧边栏 + i18n — app-main-*.js")

files = find_file("app-main-*.js")
if not files:
    print("  未找到 app-main-*.js，搜索所有 JS...")
    for f in glob.glob(os.path.join(BASE, "*.js")):
        with open(f, "r", encoding="utf-8") as fh:
            c = fh.read()
        if "pluginsDisabledTooltip" in c and "enable_i18n" in c:
            files = [f]
            print(f"  -> 发现目标: {os.path.basename(f)}")
            break

for filepath in files:
    # 补丁 2a: 插件侧边栏门控
    # 原始: d?(0,$.jsx)(rf,{tooltipContent:(0,$.jsx)(Y,{id:`sidebarElectron.pluginsDisabledTooltip`
    # 门控变量 d 可能变化，组件名 rf/Y 也可能变化
    apply_patch(filepath,
        name="插件侧边栏解锁",
        find_str="d?(0,$.jsx)(rf,{tooltipContent:(0,$.jsx)(Y,{id:`sidebarElectron.pluginsDisabledTooltip`",
        replace_str="0?(0,$.jsx)(rf,{tooltipContent:(0,$.jsx)(Y,{id:`sidebarElectron.pluginsDisabledTooltip`",
        find_regex=r'([a-zA-Z_$])\?\(0,\$\.jsx\)\([a-zA-Z_$]+,\{tooltipContent:\(0,\$\.jsx\)\([a-zA-Z_$]+,\{id:`sidebarElectron\.pluginsDisabledTooltip`',
        replace_fn=lambda m: m.group(0).replace(m.group(1) + "?", "0?", 1)
    )

    # 补丁 2b: i18n 多语言强制启用
    # 原始: r=(0,Q.useMemo)(()=>n?.get(`enable_i18n`,!1),[n])
    # Statsig 实验 72216192 在无用户上下文时返回 false，导致 API key 模式无中文
    apply_patch(filepath,
        name="i18n 多语言强制启用",
        find_str="r=(0,Q.useMemo)(()=>n?.get(`enable_i18n`,!1),[n])",
        replace_str="r=(0,Q.useMemo)(()=>!0,[n])",
        find_regex=r'([a-zA-Z_$])=\(0,[a-zA-Z_$]+\.useMemo\)\(\(\)=>[a-zA-Z_$]+\?\.get\(`enable_i18n`,!1\),\[[a-zA-Z_$]+\]\)',
        replace_fn=lambda m: f"{m.group(1)}=(0,Q.useMemo)(()=>!0,[n])"
    )


# ================================================================
# 模块 3: check-plugin-availability — 插件连接器 (1 个补丁)
# ================================================================
print("\n[模块 3] 插件连接器 — check-plugin-availability-*.js")

files = find_file("check-plugin-availability-*.js")
if not files:
    print("  未找到 check-plugin-availability-*.js，搜索所有 JS...")
    for f in glob.glob(os.path.join(BASE, "*.js")):
        with open(f, "r", encoding="utf-8") as fh:
            c = fh.read()
        if "connector-unavailable" in c and "connector" in os.path.basename(f).lower():
            files = [f]
            print(f"  -> 发现目标: {os.path.basename(f)}")
            break
    if not files:
        for f in glob.glob(os.path.join(BASE, "*.js")):
            with open(f, "r", encoding="utf-8") as fh:
                c = fh.read()
            if "connector-unavailable" in c:
                files = [f]
                print(f"  -> 发现目标: {os.path.basename(f)}")
                break

for filepath in files:
    # 补丁 3: 连接器可用性
    # 原始: (i=`connector-unavailable`)
    apply_patch(filepath,
        name="插件连接器解锁",
        find_str="(i=`connector-unavailable`)",
        replace_str="false&&(i=`connector-unavailable`)",
        find_regex=r'\(([a-zA-Z_$])=`connector-unavailable`\)',
        replace_fn=lambda m: f"false&&({m.group(1)}=`connector-unavailable`)"
    )


# ================================================================
# 模块 4: gradient — 品牌视觉 (1 个补丁)
# ================================================================
print("\n[模块 4] 品牌视觉 — gradient-*.js")

files = find_file("gradient-*.js")
if not files:
    print("  未找到 gradient-*.js，搜索所有 JS...")
    for f in glob.glob(os.path.join(BASE, "*.js")):
        with open(f, "r", encoding="utf-8") as fh:
            c = fh.read()
        if "function e(e){return e!==`chatgpt`}" in c:
            files = [f]
            print(f"  -> 发现目标: {os.path.basename(f)}")
            break

for filepath in files:
    # 补丁 4: 品牌视觉统一
    # 原始: function e(e){return e!==`chatgpt`}
    apply_patch(filepath,
        name="品牌视觉统一",
        find_str="function e(e){return e!==`chatgpt`}",
        replace_str="function e(e){return false}",
        find_regex=r'function\s+([a-zA-Z_$]+)\(\1\)\{return\s+\1!==`chatgpt`\}',
        replace_fn=lambda m: f"function {m.group(1)}({m.group(1)}){{return false}}"
    )


# ================================================================
# 模块 5: annotation-comment-editor-card — 语音输入 (1 个补丁)
# ================================================================
print("\n[模块 5] 语音输入 — annotation-comment-editor-card-*.js")

files = find_file("annotation-comment-editor-card-*.js")
if not files:
    print("  未找到 annotation-comment-editor-card-*.js，搜索所有 JS...")
    for f in glob.glob(os.path.join(BASE, "*.js")):
        with open(f, "r", encoding="utf-8") as fh:
            c = fh.read()
        if "authMethod===`chatgpt`" in c and "dictation" in c.lower():
            files = [f]
            print(f"  -> 发现目标: {os.path.basename(f)}")
            break

for filepath in files:
    # 补丁 5: 语音输入解锁
    # 原始: n&&t.authMethod===`chatgpt`
    apply_patch(filepath,
        name="语音输入解锁",
        find_str="n&&t.authMethod===`chatgpt`",
        replace_str="n&&(t.authMethod===`chatgpt`||t.authMethod===`apikey`)",
        find_regex=r'([a-zA-Z_$]+)&&([a-zA-Z_$]+)\.authMethod===`chatgpt`',
        replace_fn=lambda m: f"{m.group(1)}&&({m.group(2)}.authMethod===`chatgpt`||{m.group(2)}.authMethod===`apikey`)"
    )


# ================================================================
# 模块 6: use-usage-settings-access — 用量设置 (1 个补丁)
# ================================================================
print("\n[模块 6] 用量设置 — use-usage-settings-access-*.js")

files = find_file("use-usage-settings-access-*.js")
if not files:
    print("  未找到 use-usage-settings-access-*.js，搜索所有 JS...")
    for f in glob.glob(os.path.join(BASE, "*.js")):
        with open(f, "r", encoding="utf-8") as fh:
            c = fh.read()
        if "let r=e===`chatgpt`" in c and "usage" in os.path.basename(f).lower():
            files = [f]
            print(f"  -> 发现目标: {os.path.basename(f)}")
            break
    if not files:
        for f in glob.glob(os.path.join(BASE, "*.js")):
            with open(f, "r", encoding="utf-8") as fh:
                c = fh.read()
            if "let r=e===`chatgpt`" in c:
                files = [f]
                print(f"  -> 发现目标: {os.path.basename(f)}")
                break

for filepath in files:
    # 补丁 6: 用量设置解锁
    # 原始: let r=e===`chatgpt`
    apply_patch(filepath,
        name="用量设置解锁",
        find_str="let r=e===`chatgpt`",
        replace_str="let r=e===`chatgpt`||e===`apikey`",
        find_regex=r'let\s+([a-zA-Z_$]+)=([a-zA-Z_$]+)===`chatgpt`',
        replace_fn=lambda m: f"let {m.group(1)}={m.group(2)}===`chatgpt`||{m.group(2)}===`apikey`"
    )


# ================================================================
# 汇总报告
# ================================================================
print("\n" + "=" * 60)
print("补丁报告")
print("=" * 60)
total = len(results["applied"]) + len(results["skipped"]) + len(results["failed"])
print(f"  总计: {total} 个补丁")
print(f"  成功: {len(results['applied'])} 个")
print(f"  跳过: {len(results['skipped'])} 个（已应用）")
print(f"  失败: {len(results['failed'])} 个")

if results["applied"]:
    print("\n  已应用:")
    for r in results["applied"]:
        print(f"    ✓ {r}")

if results["skipped"]:
    print("\n  已跳过:")
    for r in results["skipped"]:
        print(f"    - {r}")

if results["failed"]:
    print("\n  ⚠ 失败（需手动处理）:")
    for r in results["failed"]:
        print(f"    ✗ {r}")
    print("\n  失败补丁的排查方法见文档底部【版本更新排查指南】")

if results["failed"] and not results["applied"] and not results["skipped"]:
    print("\n[ERROR] 所有补丁均失败！可能是全新版本，请参考排查指南。")
    sys.exit(1)

print("\n补丁脚本执行完毕。")
PYTHON

# Step 4: 禁用 Electron fuses
npx @electron/fuses write --app /Applications/Codex.app OnlyLoadAppFromAsar=off
npx @electron/fuses write --app /Applications/Codex.app EnableEmbeddedAsarIntegrityValidation=off
npx @electron/fuses write --app /Applications/Codex.app GrantFileProtocolExtraPrivileges=off
npx @electron/fuses write --app /Applications/Codex.app EnableCookieEncryption=off

# Step 5: 重新签名
codesign --force --deep --sign - /Applications/Codex.app

echo ""
echo "=========================================="
echo "  Codex API Key 全功能解锁 — 补丁完成"
echo "=========================================="
echo ""
echo "  启动 Codex，使用 API key 模式登录即可。"
echo "  如果异常，执行回滚命令恢复原版。"
```

---

## Windows

### 回滚方法

```powershell
cd "$env:LOCALAPPDATA\Programs\Codex\resources"
Remove-Item -Recurse -Force app -ErrorAction SilentlyContinue
if (Test-Path app.asar1) { Rename-Item app.asar1 app.asar }
if (Test-Path app.asar.bak) { Copy-Item app.asar.bak app.asar }
Write-Host "已回滚到原始版本"
```

### 一键补丁（Windows）

```powershell
Stop-Process -Name "Codex" -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

cd "$env:LOCALAPPDATA\Programs\Codex\resources"

if (-not (Test-Path app.asar.bak)) {
    Copy-Item app.asar app.asar.bak
    Write-Host "已备份 app.asar -> app.asar.bak"
}

Remove-Item -Recurse -Force app -ErrorAction SilentlyContinue
npx @electron/asar e ./app.asar app
Rename-Item app.asar app.asar1

# 执行与 macOS 相同的 Python 补丁脚本（将 PLATFORM 改为 "windows"）
# python3 patch_codex.py

$codexExe = "$env:LOCALAPPDATA\Programs\Codex\Codex.exe"
npx @electron/fuses write --app $codexExe OnlyLoadAppFromAsar=off
npx @electron/fuses write --app $codexExe EnableEmbeddedAsarIntegrityValidation=off
npx @electron/fuses write --app $codexExe GrantFileProtocolExtraPrivileges=off
npx @electron/fuses write --app $codexExe EnableCookieEncryption=off

Write-Host "Codex API Key 全功能解锁 — 补丁完成"
```

---

## config.toml 参考配置

补丁完成后，编辑 `~/.codex/config.toml` 配置你的 API provider：

```toml
model_provider = "openai"
base_url = "https://your-api-provider.com/v1"
experimental_bearer_token = "sk-your-api-key"

[features]
enable_fast = true
enable_speed_128k = true
enable_pro = true
enable_o3_pro = true
enable_deep_research = true
enable_codex_cloud = true
```

---

## 版本更新排查指南

Codex 更新后 JS 文件名（hash 后缀）和变量名都可能变化。以下是每个补丁的定位方法：

### 通用搜索策略

```bash
cd /Applications/Codex.app/Contents/Resources/app/webview/assets
```

### 1. Fast 模式授权门控

```bash
# 特征关键词: authMethod + chatgpt + return
grep -rn "authMethod" *.js | grep "chatgpt" | grep "return"
# 找到包含 return!(xxx?.authMethod!==`chatgpt`||yyy) 的行
# 替换整个 return 表达式为: return true
```

### 2. Fast 模式 Hook 早期返回

```bash
# 在同一个文件中，找 if(xxx?.authMethod!==`chatgpt`||yyy){
grep -o ".{0,30}authMethod!==.chatgpt.{0,20}" <文件名>
# 在 if 条件前加 false&& 使其永远不进入
```

### 3. 模型可用性检查

```bash
# 在同一个文件中，找 xxx?.models.some(YYY)??!1
grep -o ".{0,20}models\.some.{0,30}" <文件名>
# 替换整个表达式为: true
```

### 4. 插件侧边栏

```bash
grep -rl "pluginsDisabledTooltip" *.js
# 找到 X?(0,$.jsx)(组件,{tooltipContent... 中的门控变量 X
# 将 X? 改为 0?
```

### 5. 插件连接器

```bash
grep -rl "connector-unavailable" *.js
# 找到 (变量=`connector-unavailable`)
# 前面加 false&& 使其永远不执行
```

### 6. 品牌视觉

```bash
grep -rn "return e!==.chatgpt." *.js
# 找到 function e(e){return e!==`chatgpt`}
# 改为 function e(e){return false}
```

### 7. 语音输入

```bash
grep -rn "authMethod===.chatgpt." *.js | grep -v "!=="
# 找到 xxx&&yyy.authMethod===`chatgpt` 且在 annotation/comment/editor 相关文件中
# 扩展为 xxx&&(yyy.authMethod===`chatgpt`||yyy.authMethod===`apikey`)
```

### 8. 用量设置

```bash
grep -rn "let.*===.chatgpt." *.js
# 找到 let r=e===`chatgpt` 且在 usage-settings 相关文件中
# 扩展为 let r=e===`chatgpt`||e===`apikey`
```

### 9. i18n 多语言

```bash
grep -rn "enable_i18n" *.js
# 找到 xxx=(0,YYY.useMemo)(()=>nnn?.get(`enable_i18n`,!1),[nnn])
# 改为 xxx=(0,YYY.useMemo)(()=>!0,[nnn])
# 关键: Statsig 实验门控在无用户上下文时默认返回 false
```

## 原理说明

| 操作 | 原因 | 位置 |
|------|------|------|
| `OnlyLoadAppFromAsar=off` | 让 Electron 读 `app/` 文件夹而非 `app.asar` | Electron fuse |
| `EnableEmbeddedAsarIntegrityValidation=off` | 跳过 asar 完整性 SHA 校验 | Electron fuse |
| `GrantFileProtocolExtraPrivileges=off` | 禁用 file 协议限制 | Electron fuse |
| `EnableCookieEncryption=off` | 禁用 cookie 加密检查 | Electron fuse |
| `mv app.asar app.asar1` | Electron 在 asar 不存在时自动降级到 `app/` 文件夹 | Resources 目录 |
| `codesign --force --deep --sign -` | macOS 拒绝启动未签名的修改应用 | 最终步骤 (仅 macOS) |
| Statsig 实验绕过 | API key 模式无 Statsig 用户上下文，i18n/特性实验默认关闭 | webview JS |
| `authMethod` 门控绕过 | 多处功能检查 `=== 'chatgpt'`，API key 模式被排除 | webview JS |
