# Codex API Key Unlocker

本项目提供一个本地补丁脚本，用来让 Codex 桌面应用的 API Key 模式开放更多桌面端功能。脚本会自动定位 Codex 安装目录、解包并修补 `app.asar`、重新打包、创建 Windows 独立副本 `Codex-boji`，并提供回滚、卸载、同步 Store 更新和本地会话索引修复入口。

> Disclaimer: This project modifies a local desktop app installation. Use it at your own risk, review the source before running, and make sure your use complies with the software terms that apply to you. Do not publish API keys, auth files, session files, logs, screenshots with secrets, or patched app binaries.

## 功能

| 功能 | 说明 |
| --- | --- |
| API Key 会话保持 | 将 API Key 模式的前端身份门控伪装到可用路径，减少功能差异 |
| Fast / Speed 模式 | 尝试开放 Standard / Fast 速度选择相关入口 |
| 插件侧边栏和连接器 | 尝试开放 API Key 模式下的插件入口与连接器可用性检查 |
| 语音输入 | 尝试开放 API Key 模式下的语音/听写入口 |
| 用量设置入口 | 尝试开放桌面端设置里的用量相关入口 |
| i18n 多语言 | 尝试绕过无用户上下文导致的多语言实验门控 |
| 品牌视觉统一 | 尝试移除 API Key 模式下的差异化视觉提示 |
| 模型下拉注入 | 从 `~/.codex/config.toml` 的中转站配置读取 `/v1/models`，补充可选模型 |
| 本地会话加载 | 重建 `~/.codex/session_index.jsonl`，减少切换 API/账号后历史会话缺失 |
| Windows Store 转独立版 | 将 Store 版复制到 `%LOCALAPPDATA%\Codex-boji` 后再打补丁 |
| Store 更新同步 | Store 版更新后，可重新同步到 `Codex-boji` 并再次打补丁 |
| 回滚和卸载 | 支持仅回滚补丁，或删除 Windows 独立副本与快捷方式 |

已移除的旧实验功能：对话内/外置状态显示和用量费用插件。这些功能不再作为项目功能发布；安装时只会尝试清理旧版本中可能残留的状态栏注入片段。

## 前置要求

- Python 3.9+
- Node.js，确保命令行可用 `npx`
- 已安装 Codex 桌面应用

Windows 用户可以从 Microsoft Store 安装 Codex。Store 目录 `C:\Program Files\WindowsApps` 受系统保护，本项目不会原地修改 Store 应用，而是复制到用户目录下的 `Codex-boji` 后再补丁。

## 快速开始

### Windows

推荐右键 `patch.bat`，选择“以管理员身份运行”，然后选择：

```text
[1] Install / patch Codex
```

菜单说明：

| 选项 | 作用 |
| --- | --- |
| `[1] Install / patch Codex` | 安装或更新补丁 |
| `[2] Uninstall patched Codex` | 删除 Windows 独立补丁版 `Codex-boji` 和快捷方式 |
| `[3] Rollback patch only` | 仅恢复补丁文件，保留安装目录 |
| `[4] Load local sessions` | 仅重建本地会话索引 |
| `[5] Sync Store update to Codex-boji` | 将当前 Store 版同步到 `Codex-boji` |
| `[6] Exit` | 退出 |

首次处理 Store 版通常需要管理员权限读取 `WindowsApps`。如果脚本检测到只有 Store 版且本地还没有 `Codex-boji`，`patch.bat` 会尝试自动请求管理员权限。

### macOS / Linux

```bash
bash patch.sh
```

如果 Codex 不在默认位置，可以指定路径：

```bash
CODEX_PATH=/Applications/Codex.app python3 patch.py
```

## 命令行

```bash
python patch.py                 # 安装或更新补丁
python patch.py --rollback      # 仅回滚补丁文件
python patch.py --uninstall     # Windows: 删除 Codex-boji 和快捷方式
python patch.py --sync-store    # Windows: 同步当前 Store 版到 Codex-boji
python patch.py --load-sessions # 仅重建本地会话索引
python patch.py --path <dir>    # 指定非标准 Codex 安装目录
python patch.py --help          # 查看帮助
```

环境变量：

| 变量 | 作用 |
| --- | --- |
| `CODEX_PATH` | 指定 Codex 安装根目录、`resources` 目录或 macOS `.app` 路径 |
| `CODEX_HOME` | 指定 Codex 配置目录，默认 `~/.codex` |

## 安装过程

执行 `[1] Install / patch Codex` 时，脚本会做这些事：

1. 检查 Python 和 Node.js / `npx`。
2. 定位 Codex 安装目录。
3. Windows Store 版会复制到 `%LOCALAPPDATA%\Codex-boji`。
4. 关闭正在运行的 Codex 进程，避免文件锁。
5. 解包 `app.asar` 到 `resources/app`，保留原始备份。
6. 按特征搜索前端 bundle 并应用补丁。
7. 清理旧版本可能残留的实验状态栏注入。
8. 从中转站 `/v1/models` 补充模型列表（如果本地配置存在）。
9. 补全 `~/.codex/config.toml` 中的相关 feature 开关。
10. 重建本地会话索引。
11. 用 `node --check` 检查被修改的 JS 文件语法。
12. 重新打包 `app.asar`，并检查启动结构和 native sidecar。
13. 尝试写 Electron fuses 作为兜底；macOS 会尝试重新签名。
14. Windows 会创建桌面和开始菜单快捷方式 `Codex-boji`。

重复运行是幂等的：已应用的补丁会跳过；缺失或新版 hash 文件会重新按特征查找。

## Windows Store 更新

Store 版 Codex 更新后，`Codex-boji` 不会自动跟随更新。请运行：

```powershell
python patch.py --sync-store
python patch.py
```

或在 `patch.bat` 中依次选择 `[5] Sync Store update to Codex-boji` 和 `[1] Install / patch Codex`。

## 本地会话加载

如果切换 API、账号或版本后，本地历史会话列表缺失，可以运行：

```bash
python patch.py --load-sessions
```

脚本会扫描 `~/.codex/sessions` 和 `~/.codex/archived_sessions`，重建 `~/.codex/session_index.jsonl`。它不会上传、删除或修改会话正文。

## 回滚和卸载

仅回滚补丁：

```bash
python patch.py --rollback
```

Windows 删除独立补丁版：

```bash
python patch.py --uninstall
```

`--uninstall` 不会删除 Microsoft Store 官方 Codex，也不会删除 `~/.codex` 配置、auth 或会话数据。

## 项目结构

```text
codex-faster/
├─ patch.py
├─ patch.bat
├─ uninstall.bat
├─ patch.sh
├─ inject_models.py
├─ fast_search.py
├─ tests/
├─ docs/
├─ README.md
├─ CONTRIBUTING.md
├─ SECURITY.md
├─ LICENSE
├─ .gitignore
├─ .gitattributes
└─ .editorconfig
```

更详细说明见 [docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md)。

## 开发验证

```bash
python -m py_compile patch.py inject_models.py fast_search.py tests/test_patch_platform.py
python -m unittest discover -s tests
python patch.py --help
```

Windows 还建议验证：

```bat
patch.bat --help
uninstall.bat
```

## 安全边界

- 不提交 `~/.codex/auth.json`、`config.toml`、会话、日志、截图或任何密钥。
- 不提交解包后的 Codex 应用文件、`.asar`、`.exe`、`.dmg`、`.zip`。
- 不在 `WindowsApps` 中原地修改 Store 应用。
- 不内置任何 API key 或中转站地址。
- 不代理网络请求，不修改模型请求参数，不修改上下文窗口大小。

## 常见问题

| 问题 | 处理 |
| --- | --- |
| `npx not found` | 安装 Node.js 后重新打开终端 |
| 找不到 Codex | 用 `CODEX_PATH` 指定 Codex 根目录或 `resources` 目录 |
| Store 版无权限读取 | 右键 `patch.bat` 以管理员身份运行 |
| 启动没有反应 | 先完全退出官方 Codex，再启动桌面快捷方式 `Codex-boji` |
| Electron 默认欢迎页 | 重新运行 `[1] Install / patch Codex`，脚本会重新打包并审计 `app.asar` |
| 补丁有部分失败 | 可能是 Codex 新版本 bundle 结构改变，请带版本号和日志提交 Issue |

## License

MIT
