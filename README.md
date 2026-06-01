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
- **Windows：** OpenAI 官网"下载 Windows 版"按钮目前直接跳转 Microsoft Store。**Store 版受系统沙箱保护，本脚本无法对其打补丁**。如果你已经从 Store 装了 Codex，需要先卸载，然后从社区维护的"重打包独立版"安装（这类项目把 Codex 重新打包成普通 Electron 应用，常见安装位置是 `%LOCALAPPDATA%\CodexStandalone\` 或 `%LOCALAPPDATA%\Programs\Codex\`）。社区项目示例：[aidanqm/Codex-Windows](https://github.com/aidanqm/Codex-Windows)、[Haleclipse/CodexDesktop-Rebuild](https://github.com/Haleclipse/CodexDesktop-Rebuild)。注意它们是第三方重打包，请自行评估风险。

> **本脚本不会自动下载安装 Node.js、Python 或 Codex。** 这些都需要你手动备齐——脚本只在已安装好的环境上打补丁。运行时如果检测到缺 Node.js，会给出对应系统的安装命令提示（`winget` / `brew` / `apt` 等），但仍由你自行执行。

## 一键使用

`patch.py` 现在是**自包含的跨平台引擎**：自动关闭 Codex 进程、查找安装目录、解包、打补丁、写 Electron fuse，macOS 上还会自动重新签名。一条命令即可，无需手动执行额外步骤。

### Windows

```batch
patch.bat
```

或直接运行（自动检测安装位置）：

```powershell
python patch.py
```

### macOS / Linux

```bash
bash patch.sh
```

或直接运行：

```bash
python3 patch.py
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
