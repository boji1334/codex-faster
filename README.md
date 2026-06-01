# Codex API Key 全功能解锁

一键补丁脚本，使 Codex 桌面应用的 **API Key 模式**拥有与 **ChatGPT 账号登录模式**完全相同的功能。

## 功能解锁清单

| # | 功能 | 说明 |
|---|------|------|
| 1 | **Fast/Speed 模式** | 解锁速度选择器 Standard / Fast，默认 Fast |
| 2 | **模型下拉全显示** | 自动从中转站拉取所有可用模型加入选择列表 |
| 3 | **Plugins 插件** | API Key 模式可用插件侧边栏和连接器 |
| 4 | **语音输入/听写** | 扩展为 `chatgpt \|\| apikey` |
| 5 | **用量/计费设置** | 显示用量和计费页面 |
| 6 | **i18n 多语言** | 强制启用中文等多语言界面 |
| 7 | **品牌视觉统一** | 移除 API Key 用户的差异化品牌 |

## 前置要求

- **Node.js**（用于 `npx @electron/asar`）
- **Python 3**（运行补丁引擎）
- **Codex 独立安装版**（`.exe` / `.dmg` 安装包，**非 Microsoft Store 版本**）

> 如何确认？如果 Codex 安装在 `%LOCALAPPDATA%\Programs\Codex\`（Windows）或 `/Applications/Codex.app/`（macOS），那就是独立版。如果是 `C:\Program Files\WindowsApps\` 开头，那是 MS Store 版，不支持补丁。

## 关于 Codex 下载来源

- **macOS：** 官方提供独立 dmg —— [`Codex.dmg`](https://persistent.oaistatic.com/codex-app-prod/Codex.dmg)（拖到 Applications 即可）。这就是支持的"独立版"。
- **Windows：** OpenAI 官网"下载 Windows 版"按钮目前直接跳转 Microsoft Store。**Store 版受系统沙箱保护，无法直接打补丁——但本脚本会自动处理**：检测到 Store 版时，会自动将其复制为可打补丁的独立版（纯本地操作，不联网），只需以管理员身份运行即可。所以 Windows 用户直接从 Store 装 Codex 就行，脚本会搞定剩下的。

> **本脚本不会自动下载安装 Node.js、Python 或 Codex。** Node.js 和 Python 需要你手动备齐（运行时如果检测到缺 Node.js，会给出对应系统的安装命令提示）。Codex 本身请从 Microsoft Store 搜索安装（Windows）或用官方 dmg（macOS）。

## 一键使用

`patch.py` 现在是**自包含的跨平台引擎**：自动关闭 Codex 进程、查找安装目录、解包、打补丁、写 Electron fuse，macOS 上还会自动重新签名。一条命令即可，无需手动执行额外步骤。

### 完整流程（Windows 用户，从零开始）

```
前提：安装 Node.js（https://nodejs.org）和 Python 3（https://python.org）
      从 Microsoft Store 搜索 "Codex" 安装（或已经装了）
```

**操作步骤：**

1. 右键 `patch.bat` → **以管理员身份运行**
2. 等待窗口显示 `Done`（首次约 1-2 分钟，含复制文件和下载 npm 工具包）
3. 按任意键关闭窗口
4. 双击桌面上新出现的 **"Codex (Patched)"** 图标
5. 用 API Key 模式登录，功能全解锁

**点击 bat 后你会看到的完整输出：**

```
============================================================
  Codex API Key Unlocker v2.0
============================================================

[环境检查] 检测前置依赖...
  [OK]   Node.js (npx): C:\Program Files\nodejs\npx.CMD
  [OK]   Python: 3.x
  依赖齐全，继续。

[INFO] 平台: windows
[INFO] 检测到 Microsoft Store 版 Codex:
       C:\Program Files\WindowsApps\OpenAI.Codex_26.xxx_x64__xxxxx
       Store 版受系统沙箱保护，无法直接打补丁。
       正在将其复制为独立版（纯本地操作，不联网）...
       目标: C:\Users\你\AppData\Local\CodexStandalone
       复制中（约 200-300MB，请稍候）...
       [OK] 复制完成。
[INFO] Codex 目录: C:\Users\你\AppData\Local\CodexStandalone\resources
[INFO] Codex 程序: C:\Users\你\AppData\Local\CodexStandalone\Codex.exe

[准备] 提取 app.asar...
  提取完成
  已重命名 app.asar -> app.asar1

[模块 0] 会话保持 — use-auth-*.js
  [OK]   会话保持（authMethod伪装）

[模块 1] Fast 模式 — use-is-fast-mode-enabled-*.js
  [OK]   Fast 授权门控
  [OK]   Fast Hook 早期返回
  [OK]   模型可用性检查

[模块 2] 插件侧边栏 + i18n — app-main-*.js
  [OK]   插件侧边栏解锁
  [OK]   i18n 多语言强制启用

[模块 3] 插件连接器
  [OK]   插件连接器解锁

[模块 4] 品牌视觉
  [OK]   品牌视觉统一

[模块 5] 语音输入
  [OK]   语音输入解锁

[模块 6] 用量设置
  [OK]   用量设置解锁

[模块 7] 前端模型克隆注入
  [OK]   前端动态模型克隆注入

[模块 8] 补全 config.toml
  + enable_fast = true
  + enable_speed_128k = true
  + enable_pro = true
  ...

[校验] 补丁后 JS 语法检查
  [OK]   use-auth-xxx.js
  [OK]   app-main-xxx.js
  [OK]   model-queries-xxx.js
  ...
  全部补丁文件语法合法

[模块 9] 禁用 Electron 安全熔断器
  [OK]   OnlyLoadAppFromAsar=off
  [OK]   EnableEmbeddedAsarIntegrityValidation=off
  [OK]   GrantFileProtocolExtraPrivileges=off
  [OK]   EnableCookieEncryption=off

============================================================
  补丁报告: 12 补丁，11 OK，1 SKIP，0 失败
============================================================

  桌面快捷方式已创建: Codex (Patched)

  Codex 全功能解锁完成。启动 Codex 使用 API key 模式登录即可。

============================================================
  Done. Launch Codex and log in with API key mode.
============================================================

Press any key to continue . . .
```

> 如果你已有独立版 Codex（非 Store），则不会出现"复制为独立版"那一段，直接从"提取 app.asar"开始。

**脚本自动完成的事（无需手动操作）：**

| 步骤 | 说明 |
|------|------|
| 环境检查 | 检测 Node.js / Python，缺失则给出安装命令 |
| 查找 Codex | 优先找独立版；只有 Store 版则自动复制为独立版 |
| 关闭进程 | 自动 taskkill Codex.exe |
| 解包 | npx @electron/asar 提取 app.asar |
| 打补丁 | 12 个功能解锁补丁（regex 兼容多版本） |
| 语法校验 | node --check 验证所有改动文件，出错自动回滚 |
| 写 Fuse | 禁用 Electron 安全检查（带重试，不怕文件占用） |
| 桌面快捷方式 | 自动创建 "Codex (Patched)" 快捷方式 |

> **为什么需要管理员权限？** Store 版 Codex 装在受保护的 `WindowsApps` 目录，需要管理员权限才能读取并复制。如果你已有独立版（非 Store），普通权限即可。

### Windows（已有独立版）

不需要管理员，直接双击：

```batch
patch.bat
```

### macOS / Linux

```bash
bash patch.sh
```

### 安装在非标准位置？

脚本会自动搜索常见安装目录。如果你的 Codex 装在别处（或自动检测失败），用 `CODEX_PATH` 指定即可——支持安装根目录、`resources` 目录，或 macOS 的 `.app` 路径：

```powershell
# Windows
set CODEX_PATH=D:\MyApps\Codex
python patch.py
```

```bash
# macOS
CODEX_PATH=/Applications/Codex.app python3 patch.py

# Linux
CODEX_PATH=/opt/Codex python3 patch.py
```

也可以用命令行参数：`python patch.py --path "D:\MyApps\Codex"`

## 回滚

```bash
python3 patch.py --rollback
```

或手动：

**Windows:**
```powershell
cd $env:LOCALAPPDATA\Programs\Codex\resources
Remove-Item -Recurse -Force app
Rename-Item app.asar1 app.asar
```

**macOS:**
```bash
cd /Applications/Codex.app/Contents/Resources
rm -rf app
mv app.asar1 app.asar
codesign --force --deep --sign - /Applications/Codex.app
```

## 效果说明

### Fast 模式加速效果

Fast 模式通过 `service_tier: "priority"` 参数控制推理速度。实际加速效果取决于你的 API 中转站/上游：

- **OpenAI API Key 账号**：原生支持 speed tier → 真实 1.5x 加速
- **ChatGPT Plus OAuth 账号**：通过 sub2api 等平台中转时，需在平台配置 "OpenAI Fast/Flex Policy" 规则为 `Pass` 模式
- **其他第三方代理**：取决于代理是否支持透传 `service_tier` 参数

> 已配置 sub2api 的用户：登录管理面板 → 设置 → OpenAI Fast/Flex 策略 → 添加规则（service_tier=priority, 动作=Pass, 范围=全部账号）

### 模型可用性

脚本会自动从中转站 `/v1/models` 拉取模型列表并注入 Codex。哪些模型能用取决于中转站上游的实际支持情况。

### 更新后重跑

Codex 更新会覆盖 `app.asar`，补丁失效。更新后重新运行脚本即可恢复所有功能。脚本支持重复运行——已应用的补丁会自动跳过。

## 原理

| 操作 | 原因 |
|------|------|
| 提取 + 重命名 app.asar | 让 Electron 从解包目录加载修改后的 JS |
| 修改 webview JS 文件 | 绕过 `authMethod !== chatgpt` 门控 |
| 注入 models_cache.json | 扩展模型选择列表 |
| 补全 config.toml features | 启用 fast/speed/pro/deep research 等特性 |
| 禁用 Electron fuses | 关闭 asar 完整性校验 |
| macOS 重新签名 | macOS Gatekeeper 拒绝未签名应用 |

## License

MIT
