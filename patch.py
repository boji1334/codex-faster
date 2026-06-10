#!/usr/bin/env python3
"""
Codex API Key 全功能解锁 — 一键补丁引擎
使 API key 模式拥有与 ChatGPT 账号模式完全相同的功能。
支持版本自动发现，当 Codex 更新后文件名 hash 变化时自动定位目标文件。
"""

import os, glob, re, sys, json, shutil, stat, subprocess, time, urllib.request

# ================================================================
# 配置
# ================================================================
PLATFORM = None  # "macos" | "windows" | "linux" — auto-detected
BASE = None       # webview/assets 路径
CODEX_RESOURCES = None
CODEX_APP = None  # @electron/fuses 的目标：macOS 为 .app，其它平台为可执行文件
API_BASE_URL = None
API_KEY = None
USER_HOME = os.path.expanduser("~")
CODEX_HOME = os.path.abspath(os.path.expanduser(os.environ.get("CODEX_HOME", os.path.join(USER_HOME, ".codex"))))
CONFIG_PATH = os.path.join(CODEX_HOME, "config.toml")
MODELS_CACHE = os.path.join(CODEX_HOME, "models_cache.json")
SESSION_INDEX = os.path.join(CODEX_HOME, "session_index.jsonl")
SESSIONS_DIR = os.path.join(CODEX_HOME, "sessions")
ARCHIVED_SESSIONS_DIR = os.path.join(CODEX_HOME, "archived_sessions")
WINDOWS_STANDALONE_DIR_NAME = "Codex-boji"
WINDOWS_LEGACY_STANDALONE_DIR_NAMES = ["CodexStandalone", "CodexPatched"]
WINDOWS_SHORTCUT_NAME = "Codex-boji"
WINDOWS_LEGACY_SHORTCUT_NAMES = ["Codex (Patched)", "Codex"]
WINDOWS_UPDATE_STATUS = os.path.join(CODEX_HOME, "codex_boji_update_status.json")
WINDOWS_ACTIVE_BUILD_STATUS = os.path.join(CODEX_HOME, "codex_boji_active_build.json")

results = {"applied": [], "skipped": [], "failed": []}
patched_files = set()  # 记录真正被写入修改过的 JS 文件，用于补丁后语法校验


# ================================================================
# 跨平台命令解析：让 npx / codesign 在任何机器上都能被正确调用
# ================================================================
def resolve_executable(name):
    """在 PATH 中解析可执行文件的绝对路径。

    Windows 上 npx 实际是 npx.cmd / npx.ps1，直接用 subprocess(["npx", ...])
    会抛 FileNotFoundError，因此必须显式解析后缀。返回 None 表示未安装。
    """
    found = shutil.which(name)
    if found:
        return found
    if sys.platform == "win32":
        for ext in (".cmd", ".exe", ".bat", ".ps1"):
            found = shutil.which(name + ext)
            if found:
                return found
    return None


def run_command(args, **kwargs):
    """运行外部命令。自动解析可执行文件路径，跨平台安全。

    关键点：Windows 上 npx / @electron 等工具是 .cmd/.bat 批处理脚本。
    不同 Python 版本对“用 subprocess 列表参数直接执行 .cmd”的支持不一致
    （3.7 及更早版本可能失败，且涉及 CVE-2024-3566 的安全修复）。
    为了在任何机器、任何 Python 版本上都稳定，npx 会优先绕开
    npx.CMD，直接用 node.exe 执行 npx-cli.js。
    """
    exe = resolve_executable(args[0])
    if sys.platform == "win32" and args and args[0].lower() == "npx":
        npx_args = _windows_npx_command(list(args[1:]))
        if npx_args:
            return subprocess.run(npx_args, **kwargs)
    if exe:
        if sys.platform == "win32" and exe.lower().endswith((".cmd", ".bat")):
            # 直接执行批处理文件，让 Python 构造完整命令行。不要用
            # ["cmd", "/c", exe, ...]，否则 npx.CMD 内部的 %* 会把
            # "C:\\Program Files\\..." 这类参数重新拆坏。
            return subprocess.run([exe] + list(args[1:]), **kwargs)
        return subprocess.run([exe] + list(args[1:]), **kwargs)
    # 回退：Windows 下用 shell 解析（处理 PATH 中只有 .cmd 包装器的边缘情况）
    if sys.platform == "win32":
        return subprocess.run(" ".join(f'"{a}"' if " " in a else a for a in args),
                              shell=True, **kwargs)
    raise FileNotFoundError(args[0])


def _windows_npx_command(extra_args):
    """Return a batch-free npx invocation on Windows when Node.js is installed.

    npm's generated npx.CMD forwards arguments with `%*`. When Python calls it
    through an extra `cmd /c` layer, quoted paths such as `C:\\Program Files\\...`
    can be split and `@electron/asar` then fails with `C:\\Program` errors.
    Running npx-cli.js through node.exe avoids that wrapper entirely.
    """
    if sys.platform != "win32":
        return None
    npx = resolve_executable("npx")
    if not npx:
        return None
    node = resolve_executable("node")
    npx_dir = os.path.dirname(npx)
    cli_candidates = [
        os.path.join(npx_dir, "node_modules", "npm", "bin", "npx-cli.js"),
        os.path.join(os.path.dirname(npx_dir), "node_modules", "npm", "bin", "npx-cli.js"),
        os.path.join(npx_dir, "npx-cli.js"),
    ]
    cli = next((p for p in cli_candidates if os.path.isfile(p)), None)
    if node and cli:
        return [node, cli] + extra_args
    return None


def _is_windows_store_path(path):
    """Return True for Microsoft Store package paths that should not be patched in place."""
    if sys.platform != "win32" or not path:
        return False
    try:
        norm = os.path.normcase(os.path.abspath(path))
    except OSError:
        norm = os.path.normcase(path)
    marker = os.path.normcase(os.path.join("WindowsApps", ""))
    return marker in norm


def _windows_codex_candidates():
    """汇总 Windows 上所有可能的 Codex 安装根目录（不含 resources）。"""
    cands = []
    env_dirs = [
        os.environ.get("LOCALAPPDATA", ""),
        os.environ.get("PROGRAMFILES", ""),
        os.environ.get("PROGRAMFILES(X86)", ""),
        os.environ.get("PROGRAMDATA", ""),
        os.environ.get("APPDATA", ""),
    ]
    sub_dirs = [
        ["Programs", "Codex"],
        ["Codex"],
        [WINDOWS_STANDALONE_DIR_NAME],
        *([name] for name in WINDOWS_LEGACY_STANDALONE_DIR_NAMES),
        ["OpenAI", "Codex"],
        ["Programs", "@openai", "codex"],
    ]
    for base in env_dirs:
        if not base:
            continue
        for parts in sub_dirs:
            cands.append(os.path.join(base, *parts))
    return cands


def _resources_has_app(rp):
    """判断某个 resources 目录是否是有效的 Codex 安装（含 app.asar 或已解包/已打补丁）。"""
    return os.path.isdir(rp) and (
        os.path.isfile(os.path.join(rp, "app.asar"))
        or os.path.isfile(os.path.join(rp, "app.asar1"))
        or os.path.isdir(os.path.join(rp, "app"))
    )


def _version_key(version):
    """Return a comparable tuple for dotted package versions."""
    if not version:
        return ()
    return tuple(int(p) if p.isdigit() else 0 for p in re.split(r"[._-]", version) if p)


def _parse_store_version(path):
    name = os.path.basename(os.path.normpath(path or ""))
    m = re.search(r"OpenAI\.Codex_([0-9][0-9A-Za-z._-]*)_", name, re.I)
    if m:
        return m.group(1)
    return None


def _store_install_record(candidate):
    """Return normalized Store install metadata when a candidate is patchable."""
    resources = [
        os.path.join(candidate, "app", "resources"),
        os.path.join(candidate, "resources"),
        candidate,
    ]
    for res in resources:
        if _resources_has_app(res):
            app_root = os.path.dirname(res) if os.path.basename(res).lower() == "resources" else candidate
            exe = _find_codex_executable(app_root)
            return {
                "package_root": candidate,
                "copy_root": app_root,
                "resources": res,
                "exe": exe,
                "version": _parse_store_version(candidate),
            }
    return None


def _find_windows_store_codex():
    """Find the newest readable Microsoft Store Codex package."""
    if sys.platform != "win32":
        return None
    win_apps = os.path.join(os.environ.get("PROGRAMFILES", r"C:\Program Files"), "WindowsApps")
    if not os.path.isdir(win_apps):
        return None

    records = []
    try:
        for d in os.listdir(win_apps):
            dl = d.lower()
            if ("openai" in dl and "codex" in dl) or "9plm9xgg6vks" in dl:
                record = _store_install_record(os.path.join(win_apps, d))
                if record:
                    records.append(record)
    except PermissionError:
        raise
    except OSError:
        return None

    if not records:
        return None
    records.sort(key=lambda r: _version_key(r.get("version")), reverse=True)
    return records[0]


def _find_windows_store_codex_appx():
    """Read Store Codex metadata without requiring WindowsApps directory access."""
    if sys.platform != "win32":
        return None
    ps = r'''
$pkg = Get-AppxPackage -Name OpenAI.Codex -ErrorAction SilentlyContinue | Sort-Object Version -Descending | Select-Object -First 1
if ($pkg) {
  [pscustomobject]@{
    Name = $pkg.Name
    Version = $pkg.Version.ToString()
    InstallLocation = $pkg.InstallLocation
  } | ConvertTo-Json -Compress
}
'''
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, timeout=12
        )
        if r.returncode != 0 or not r.stdout.strip():
            return None
        data = json.loads(r.stdout)
        location = data.get("InstallLocation")
        version = data.get("Version")
        resources = os.path.join(location, "app", "resources") if location else None
        return {
            "package_root": location,
            "copy_root": os.path.join(location, "app") if location else None,
            "resources": resources,
            "exe": os.path.join(location, "app", "Codex.exe") if location else None,
            "version": version,
            "metadata_only": True,
        }
    except Exception:
        return None


def _write_update_status(status):
    try:
        os.makedirs(CODEX_HOME, exist_ok=True)
        with open(WINDOWS_UPDATE_STATUS, "w", encoding="utf-8") as f:
            json.dump(status, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  [WARN] 写入更新状态失败: {e}")


def _read_active_build_root():
    if sys.platform != "win32" or not os.path.isfile(WINDOWS_ACTIVE_BUILD_STATUS):
        return None
    try:
        with open(WINDOWS_ACTIVE_BUILD_STATUS, "r", encoding="utf-8") as f:
            root = json.load(f).get("active_root")
        if isinstance(root, str) and os.path.isdir(root):
            return root
    except Exception:
        pass
    return None


def _write_active_build_root(root, reason=None):
    if sys.platform != "win32" or not root:
        return
    try:
        os.makedirs(CODEX_HOME, exist_ok=True)
        payload = {
            "active_root": root,
            "reason": reason or "active patched Codex build",
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        with open(WINDOWS_ACTIVE_BUILD_STATUS, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  [WARN] 写入活动版本状态失败: {e}")


def _read_boji_version(root):
    manifest = os.path.join(root, ".codex-boji.json")
    if os.path.isfile(manifest):
        try:
            with open(manifest, "r", encoding="utf-8") as f:
                return json.load(f).get("source_version")
        except Exception:
            return None
    return None


def _write_boji_manifest(root, store_record):
    manifest = {
        "name": WINDOWS_STANDALONE_DIR_NAME,
        "source": "Microsoft Store Codex",
        "source_version": store_record.get("version") if store_record else None,
        "source_package_root": store_record.get("package_root") if store_record else None,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    try:
        with open(os.path.join(root, ".codex-boji.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"       [WARN] 写入 Codex-boji 元数据失败: {e}")


def _check_windows_boji_update(store_record=None, standalone_root=None, write=True):
    """Compare Store Codex with the local Codex-boji copy."""
    if sys.platform != "win32":
        return None
    if store_record is None:
        try:
            store_record = _find_windows_store_codex()
        except PermissionError:
            store_record = _find_windows_store_codex_appx()
    if standalone_root is None:
        standalone_root = _windows_standalone_root()

    boji_version = _read_boji_version(standalone_root) if standalone_root and os.path.isdir(standalone_root) else None
    store_version = store_record.get("version") if store_record else None
    update_available = False
    if store_version and boji_version:
        update_available = _version_key(store_version) > _version_key(boji_version)
    status = {
        "app_name": WINDOWS_STANDALONE_DIR_NAME,
        "store_version": store_version,
        "boji_version": boji_version,
        "update_available": update_available,
        "store_package_root": store_record.get("package_root") if store_record else None,
        "boji_root": standalone_root,
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    if write:
        _write_update_status(status)
    return status


def _copy_tree_robust(src, dst):
    """Copy a Codex app directory, using robocopy on Windows for deep app trees."""
    src_abs = os.path.abspath(src)
    dst_abs = os.path.abspath(dst)
    if os.path.normcase(src_abs) == os.path.normcase(dst_abs):
        raise RuntimeError("source and destination are the same directory")

    if sys.platform == "win32" and resolve_executable("robocopy"):
        os.makedirs(dst_abs, exist_ok=True)
        r = run_command(
            [
                "robocopy",
                src_abs,
                dst_abs,
                "/E",
                "/COPY:DAT",
                "/DCOPY:DAT",
                "/XJ",
                "/R:2",
                "/W:1",
                "/NFL",
                "/NDL",
                "/NJH",
                "/NJS",
                "/NP",
            ],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=600,
        )
        # Robocopy uses 0-7 for success/info, >=8 for actual failure.
        if r.returncode < 8:
            return
        output = "\n".join((r.stdout or "", r.stderr or "").splitlines()[-8:])
        raise RuntimeError(f"robocopy failed with exit code {r.returncode}\n{output}")

    shutil.copytree(src_abs, dst_abs, dirs_exist_ok=True)


def _remove_tree_robust(path):
    """Remove a tree, using robocopy on Windows for deep node_modules paths."""
    if not path or not os.path.exists(path):
        return

    path_abs = os.path.abspath(path)
    if not os.path.isdir(path_abs):
        os.remove(path_abs)
        return

    if sys.platform == "win32" and resolve_executable("robocopy"):
        parent = os.path.dirname(path_abs)
        empty = os.path.join(parent, ".codex_boji_empty_delete")
        try:
            os.makedirs(empty, exist_ok=True)
            r = run_command(
                [
                    "robocopy",
                    empty,
                    path_abs,
                    "/MIR",
                    "/XJ",
                    "/R:2",
                    "/W:1",
                    "/NFL",
                    "/NDL",
                    "/NJH",
                    "/NJS",
                    "/NP",
                ],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=300,
            )
            if r.returncode >= 8:
                output = "\n".join((r.stdout or "", r.stderr or "").splitlines()[-8:])
                raise OSError(f"robocopy mirror delete failed with exit code {r.returncode}\n{output}")
        finally:
            shutil.rmtree(empty, ignore_errors=True)
        try:
            os.rmdir(path_abs)
            return
        except OSError:
            pass

    shutil.rmtree(path_abs)


def _replace_file_retry(src, dst, attempts=10, delay=0.8):
    """Replace a file, retrying transient Windows locks from AV/indexers."""
    last_error = None
    for _ in range(attempts):
        try:
            os.replace(src, dst)
            return
        except OSError as e:
            last_error = e
            if sys.platform != "win32":
                raise
            time.sleep(delay)
    raise last_error


def _copy_file_replace_retry(src, dst, attempts=10, delay=0.8):
    tmp = dst + ".copytmp"
    last_error = None
    for _ in range(attempts):
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
            shutil.copy2(src, tmp)
            _replace_file_retry(tmp, dst, attempts=1, delay=delay)
            return
        except OSError as e:
            last_error = e
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            if sys.platform != "win32":
                raise
            time.sleep(delay)
    raise last_error


def _replace_tree_retry(src, dst, root, attempts=10, delay=0.8):
    """Replace a directory tree, retrying transient Windows locks."""
    last_error = None
    for _ in range(attempts):
        try:
            if os.path.isdir(dst):
                if not _path_is_within(dst, root):
                    raise OSError(f"拒绝删除非 resources 内目录: {dst}")
                _remove_tree_robust(dst)
            elif os.path.exists(dst):
                os.remove(dst)
            os.replace(src, dst)
            return
        except OSError as e:
            last_error = e
            if sys.platform != "win32":
                raise
            time.sleep(delay)
    raise last_error


def _asar_unpacked_path(asar_path):
    return asar_path + ".unpacked"


def _backup_original_asar_files():
    """Keep the original archive and its unpacked sidecar together."""
    asar1_path = os.path.join(CODEX_RESOURCES, "app.asar1")
    asar_bak = os.path.join(CODEX_RESOURCES, "app.asar.bak")
    unpacked_path = _asar_unpacked_path(os.path.join(CODEX_RESOURCES, "app.asar"))
    unpacked_bak = os.path.join(CODEX_RESOURCES, "app.asar.unpacked.bak")

    if os.path.exists(asar1_path) and not os.path.exists(asar_bak):
        shutil.copy2(asar1_path, asar_bak)
        print(f"  已备份: {asar_bak}")
    if os.path.isdir(unpacked_path) and not os.path.exists(unpacked_bak):
        _copy_tree_robust(unpacked_path, unpacked_bak)
        print(f"  已备份: {unpacked_bak}")


def _user_override_resources():
    """允许用户通过环境变量或命令行覆盖 Codex 路径，适配非标准安装位置。

    优先级：--path 参数 > CODEX_PATH 环境变量。
    接受 Codex 根目录、resources 目录，或 macOS 的 .app 目录。
    """
    override = None
    for i, a in enumerate(sys.argv):
        if a == "--path" and i + 1 < len(sys.argv):
            override = sys.argv[i + 1]
        elif a.startswith("--path="):
            override = a.split("=", 1)[1]
    if not override:
        override = os.environ.get("CODEX_PATH")
    if not override:
        return None

    p = os.path.abspath(os.path.expanduser(override))
    # macOS .app 包
    if p.endswith(".app") and os.path.isdir(p):
        return os.path.join(p, "Contents", "Resources")
    # 已经是 resources 目录
    if os.path.basename(p).lower() == "resources" and _resources_has_app(p):
        return p
    # 是安装根目录（含 resources 子目录）
    rp = os.path.join(p, "resources")
    if _resources_has_app(rp):
        return rp
    # macOS 根目录传了 Codex.app 的父级
    rp = os.path.join(p, "Contents", "Resources")
    if _resources_has_app(rp):
        return rp
    # 用户直接传了 resources 路径但还没解包
    if os.path.isdir(p):
        return p
    print(f"[WARN] 指定的路径无效或不含 Codex 资源: {override}")
    return None


def detect_platform(convert_store=True):
    global PLATFORM, CODEX_RESOURCES, CODEX_APP, BASE

    # 1. 用户显式指定的路径优先（任何平台通用）
    override = _user_override_resources()

    if sys.platform == "darwin":
        PLATFORM = "macos"
        if override:
            CODEX_RESOURCES = override
        else:
            mac_candidates = [
                "/Applications/Codex.app/Contents/Resources",
                os.path.join(USER_HOME, "Applications", "Codex.app", "Contents", "Resources"),
            ]
            for rp in mac_candidates:
                if _resources_has_app(rp):
                    CODEX_RESOURCES = rp
                    break
        if not CODEX_RESOURCES:
            print("[ERROR] 未找到 Codex 安装目录。")
            print("  请确认 Codex 已安装到 /Applications/Codex.app")
            print("  或用 CODEX_PATH 环境变量指定，例如:")
            print("    CODEX_PATH=/path/to/Codex.app python3 patch.py")
            sys.exit(1)
        # .app = resources 上两级
        CODEX_APP = os.path.dirname(os.path.dirname(CODEX_RESOURCES))

    elif sys.platform == "win32":
        PLATFORM = "windows"
        if override and _is_windows_store_path(override):
            print("[WARN] 指定路径位于 WindowsApps。Store 版不会被原地修改，将改为复制到 Codex-boji 后打补丁。")
            override = None
        if override:
            CODEX_RESOURCES = override
        else:
            active = _read_active_build_root()
            if active:
                for rp in (os.path.join(active, "resources"), os.path.join(active, "app", "resources")):
                    if _resources_has_app(rp):
                        CODEX_RESOURCES = rp
                        break
            preferred = _windows_standalone_root()
            if not CODEX_RESOURCES and preferred:
                for rp in (os.path.join(preferred, "resources"), os.path.join(preferred, "app", "resources")):
                    if _resources_has_app(rp):
                        CODEX_RESOURCES = rp
                        break
            for c in _windows_codex_candidates():
                if CODEX_RESOURCES:
                    break
                for rp in (os.path.join(c, "resources"), os.path.join(c, "app", "resources")):
                    if _resources_has_app(rp) and not _is_windows_store_path(rp):
                        CODEX_RESOURCES = rp
                        break
                if CODEX_RESOURCES:
                    break
            if not CODEX_RESOURCES:
                # 深度搜索：在常见根目录下找 Codex.exe 旁边的 resources
                search_roots = [
                    os.environ.get("LOCALAPPDATA", ""),
                    os.environ.get("PROGRAMFILES", ""),
                    os.environ.get("PROGRAMFILES(X86)", ""),
                ]
                for base in search_roots:
                    if not base or not os.path.isdir(base):
                        continue
                    for root, dirs, files in os.walk(base):
                        if _is_windows_store_path(root):
                            dirs[:] = []
                            continue
                        if any(f.lower() == "codex.exe" for f in files):
                            rp = os.path.join(root, "resources")
                            if _resources_has_app(rp) and not _is_windows_store_path(rp):
                                CODEX_RESOURCES = rp
                                break
                        if CODEX_RESOURCES:
                            break
                    if CODEX_RESOURCES:
                        break
            store_res = None
            if not CODEX_RESOURCES and convert_store:
                # 最后尝试：检测 Microsoft Store 版并自动转换为独立版。
                # Store 版只作为复制源，永远不在 WindowsApps 中原地打补丁。
                store_res = _convert_store_to_standalone()
            if store_res:
                CODEX_RESOURCES = store_res
        if not CODEX_RESOURCES:
            print("[ERROR] 未找到 Codex 安装目录。")
            print("  请确认 Codex 已安装（可从 Microsoft Store 搜索 'Codex' 安装）。")
            print("  如果已安装 Store 版，请以管理员身份运行本脚本，")
            print("  脚本会自动将 Store 版复制为可打补丁的独立版。")
            print("  或用 CODEX_PATH 环境变量指定，例如:")
            print('    set CODEX_PATH=D:\\Codex && python patch.py')
            sys.exit(1)
        CODEX_APP = _find_codex_executable(os.path.dirname(CODEX_RESOURCES))

    elif sys.platform.startswith("linux"):
        PLATFORM = "linux"
        if override:
            CODEX_RESOURCES = override
        else:
            linux_candidates = [
                "/opt/Codex/resources",
                "/usr/lib/codex/resources",
                "/usr/lib/Codex/resources",
                "/usr/share/codex/resources",
                os.path.join(USER_HOME, ".local", "share", "Codex", "resources"),
                os.path.join(USER_HOME, "Applications", "Codex", "resources"),
            ]
            for rp in linux_candidates:
                if _resources_has_app(rp):
                    CODEX_RESOURCES = rp
                    break
        if not CODEX_RESOURCES:
            print("[ERROR] 未找到 Codex 安装目录。")
            print("  请用 CODEX_PATH 环境变量指定安装位置，例如:")
            print("    CODEX_PATH=/opt/Codex python3 patch.py")
            sys.exit(1)
        CODEX_APP = _find_codex_executable(os.path.dirname(CODEX_RESOURCES))

    else:
        print(f"[ERROR] 不支持的操作系统: {sys.platform}")
        sys.exit(1)

    BASE = os.path.join(CODEX_RESOURCES, "app", "webview", "assets")
    if not os.path.isdir(BASE):
        BASE = None  # will be set after asar extraction
    print(f"[INFO] 平台: {PLATFORM}")
    print(f"[INFO] Codex 目录: {CODEX_RESOURCES}")
    if CODEX_APP:
        print(f"[INFO] Codex 程序: {CODEX_APP}")


def _find_codex_executable(install_root):
    """在安装根目录中定位 Codex 可执行文件（用于 @electron/fuses）。"""
    if not install_root or not os.path.isdir(install_root):
        return None
    if sys.platform == "win32":
        names = ["Codex.exe", "codex.exe"]
    else:
        names = ["codex", "Codex"]
    for name in names:
        candidate = os.path.join(install_root, name)
        if os.path.isfile(candidate):
            return candidate
    # 兜底：扫描根目录一层
    try:
        for f in os.listdir(install_root):
            if f.lower() in ("codex.exe", "codex"):
                return os.path.join(install_root, f)
    except OSError:
        pass
    return None


def _convert_store_to_standalone():
    """检测 Microsoft Store 版 Codex，将其复制为独立版供补丁使用。

    纯本地操作：只是把用户电脑上已有的 Store 版文件复制到
    %LOCALAPPDATA%\\Codex-boji\\，不联网、不下载任何东西。
    需要管理员权限（读取 WindowsApps 目录）。
    返回独立版的 resources 路径，失败返回 None。"""
    if sys.platform != "win32":
        return None

    try:
        store = _find_windows_store_codex()
    except PermissionError:
        print("\n[INFO] 检测到 Microsoft Store 版 Codex，但无权限读取 WindowsApps 目录。")
        print("       请以管理员身份运行本脚本（右键 patch.bat → 以管理员身份运行）。")
        return None

    if not store:
        return None

    # 找到了 Store 版，提示用户并复制
    print(f"\n[INFO] 检测到 Microsoft Store 版 Codex:")
    print(f"       {store['package_root']}")
    print(f"       Store 版受系统沙箱保护，无法直接打补丁。")
    print(f"       正在将其复制为 {WINDOWS_STANDALONE_DIR_NAME}（纯本地操作，不联网）...")

    localappdata = os.environ.get("LOCALAPPDATA")
    if not localappdata:
        print("       [ERROR] 未找到 LOCALAPPDATA，无法创建独立版目录。")
        return None

    standalone_root = os.path.join(localappdata, WINDOWS_STANDALONE_DIR_NAME)
    standalone_res = os.path.join(standalone_root, "resources")

    # 如果已经复制过且 resources 里有 app.asar，跳过复制
    if _resources_has_app(standalone_res):
        print(f"       {WINDOWS_STANDALONE_DIR_NAME} 已存在: {standalone_root}，跳过复制。")
        status = _check_windows_boji_update(store, standalone_root)
        if status and status.get("update_available"):
            print(f"       [UPDATE] Store 版更新: {status.get('store_version')} > {status.get('boji_version')}")
            print("                可重新同步 Codex-boji 后再打补丁。")
        return standalone_res

    # 执行复制
    try:
        print(f"       目标: {standalone_root}")
        print(f"       复制中（约 200-300MB，请稍候）...")
        _copy_tree_robust(store["copy_root"], standalone_root)
        print(f"       [OK] 复制完成。")
        _write_boji_manifest(standalone_root, store)
        _check_windows_boji_update(store, standalone_root)
    except PermissionError:
        print(f"       [ERROR] 无权限复制。请以管理员身份运行。")
        return None
    except Exception as e:
        print(f"       [ERROR] 复制失败: {e}")
        return None

    # 确认复制后的 resources 路径
    if _resources_has_app(standalone_res):
        return standalone_res
    # 有些结构 app.asar 直接在根目录，resources 不存在
    if os.path.isfile(os.path.join(standalone_root, "app.asar")):
        # 创建 resources 子目录结构
        os.makedirs(standalone_res, exist_ok=True)
        shutil.move(os.path.join(standalone_root, "app.asar"), os.path.join(standalone_res, "app.asar"))
        return standalone_res

    print(f"       [ERROR] 复制后未找到 app.asar，Store 版结构可能不兼容。")
    return None


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


def file_contains(filepath, *needles):
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return all(needle in content for needle in needles)
    except OSError:
        return False


def find_asset_files_containing(pattern, *needles):
    if BASE is None:
        return []
    return [
        f for f in glob.glob(os.path.join(BASE, pattern))
        if file_contains(f, *needles)
    ]


def apply_patch(filepath, name, find_str=None, replace_str=None, find_regex=None, replace_fn=None, applied_marker=None):
    """应用单个补丁：优先精确匹配，失败则 regex 降级。

    applied_marker: 可选的正则字符串，用于检测“补丁后的形态”。
    对于只有 regex（无 replace_str）的补丁，重跑时原始模式已不匹配，
    单靠 replace_str 无法判断幂等，会误报 FAIL。提供 applied_marker 后，
    若内容已是补丁后形态则正确标记为 [SKIP]。"""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    basename = os.path.basename(filepath)

    # 检查是否已应用（精确串）
    if replace_str and replace_str in content:
        results["skipped"].append(f"{basename}: {name}")
        print(f"  [SKIP] {name} — 已应用")
        return content

    # 检查是否已应用（补丁后形态，用于 regex-only 补丁的幂等判断）
    if applied_marker and re.search(applied_marker, content):
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
        patched_files.add(filepath)
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
                patched_files.add(filepath)
                return content

    results["failed"].append(f"{basename}: {name}")
    print(f"  [FAIL] {name} — 未找到匹配模式")
    return None


def mark_skipped(name, reason, filepath=None):
    label = f"{os.path.basename(filepath)}: {name}" if filepath else name
    results["skipped"].append(label)
    print(f"  [SKIP] {name} — {reason}")


def append_js_once(filepath, name, marker, snippet):
    """Append or update a JS snippet and keep sourceMappingURL comments at EOF."""
    basename = os.path.basename(filepath)
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError as e:
        results["failed"].append(f"{basename}: {name}")
        print(f"  [FAIL] {name} — 无法读取: {e}")
        return False

    def write_updated(updated, status):
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(updated)
        except OSError as e:
            results["failed"].append(f"{basename}: {name}")
            print(f"  [FAIL] {name} — 无法写入: {e}")
            return False
        patched_files.add(filepath)
        results["applied"].append(f"{basename}: {name}")
        print(f"  [OK]   {name}{status}")
        return True

    if marker in content:
        marker_comment = f"/* {marker} */"
        start = content.find(marker_comment)
        if start < 0:
            results["skipped"].append(f"{basename}: {name}")
            print(f"  [SKIP] {name} — 已应用")
            return True
        source_map = re.search(r"\n//# sourceMappingURL=.*?$", content[start:], flags=re.S)
        end = start + source_map.start() if source_map else len(content)
        old_block = content[start:end].strip()
        new_block = snippet.strip()
        if old_block == new_block:
            results["skipped"].append(f"{basename}: {name}")
            print(f"  [SKIP] {name} — 已应用")
            return True
        updated = content[:start].rstrip() + "\n" + snippet.rstrip() + "\n" + content[end:].lstrip("\n")
        return write_updated(updated, "（已更新）")

    source_map = re.search(r"\n//# sourceMappingURL=.*?$", content, flags=re.S)
    if source_map:
        insert_at = source_map.start()
        updated = content[:insert_at].rstrip() + "\n" + snippet.rstrip() + "\n" + content[insert_at:]
    else:
        updated = content.rstrip() + "\n" + snippet.rstrip() + "\n"

    return write_updated(updated, "")


def remove_js_once(filepath, name, marker):
    """Remove a previously injected JS snippet and keep sourceMappingURL comments at EOF."""
    basename = os.path.basename(filepath)
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError as e:
        results["failed"].append(f"{basename}: {name}")
        print(f"  [FAIL] {name} — 无法读取: {e}")
        return False

    marker_comment = f"/* {marker} */"
    start = content.find(marker_comment)
    if start < 0:
        print(f"  [SKIP] {name} — 未安装")
        return True

    source_map = re.search(r"\n//# sourceMappingURL=.*?$", content[start:], flags=re.S)
    end = start + source_map.start() if source_map else len(content)
    updated = content[:start].rstrip() + "\n" + content[end:].lstrip("\n")
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(updated)
    except OSError as e:
        results["failed"].append(f"{basename}: {name}")
        print(f"  [FAIL] {name} — 无法写入: {e}")
        return False
    patched_files.add(filepath)
    results["applied"].append(f"{basename}: {name}")
    print(f"  [OK]   {name}（已移除）")
    return True


def find_build_file(pattern, search_keywords=None):
    """Find files under app/.vite/build. Used for Electron main/preload patches."""
    app_dir = os.path.join(CODEX_RESOURCES, "app") if CODEX_RESOURCES else None
    if not app_dir:
        return []
    build_dir = os.path.join(app_dir, ".vite", "build")
    matches = glob.glob(os.path.join(build_dir, pattern))
    if matches:
        return matches
    if search_keywords and os.path.isdir(build_dir):
        print(f"  未找到 {pattern}，按特征搜索...")
        for f in glob.glob(os.path.join(build_dir, "*.js")):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    c = fh.read(1024 * 200)
                if all(kw in c for kw in search_keywords):
                    print(f"  -> 发现目标: {os.path.basename(f)}")
                    return [f]
            except OSError:
                pass
    return []


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
    print("\n[模块 1] Fast 模式 — service tier / fast_mode")
    files = []
    for pattern, keywords in [
        ("use-is-fast-mode-enabled-*.js", ["authMethod", "canUseFastMode"]),
        ("permissions-mode-helpers-*.js", ["authMethod", "models.some"]),
        ("use-service-tier-settings-*.js", ["fast_mode", "authMethod"]),
        ("read-service-tier-for-request-*.js", ["fast_mode", "authMethod"]),
    ]:
        for f in find_file(pattern, search_keywords=keywords):
            if f not in files:
                files.append(f)
    if not files:
        print("  [FAIL] 未找到 Fast 模式文件")
        return

    for filepath in files:
        basename = os.path.basename(filepath)
        if basename.startswith("use-service-tier-settings-"):
            apply_patch(filepath,
                name="Fast 授权门控（新版 service tier）",
                find_str="a=i?.authMethod===`chatgpt`",
                replace_str="a=i?.authMethod===`chatgpt`||i?.authMethod===`apikey`",
                find_regex=r'([a-zA-Z_$]+)=([a-zA-Z_$]+)\?\.authMethod===`chatgpt`',
                replace_fn=lambda m: f"{m.group(1)}={m.group(2)}?.authMethod===`chatgpt`||{m.group(2)}?.authMethod===`apikey`"
            )
            apply_patch(filepath,
                name="Fast feature requirement 宽松通过",
                find_str="c?.requirements?.featureRequirements?.fast_mode!==!1",
                replace_str="/*__codex_boji_fast_feature__*/true",
                find_regex=r'[a-zA-Z_$]+\?\.requirements\?\.featureRequirements\?\.fast_mode!==!1',
                replace_fn=lambda m: "/*__codex_boji_fast_feature__*/true",
                applied_marker=r'__codex_boji_fast_feature__'
            )
            continue
        if basename.startswith("read-service-tier-for-request-"):
            apply_patch(filepath,
                name="Fast 请求门控（新版 request）",
                find_str="return n===`chatgpt`?(await e.query.fetch(c,{authMethod:n,hostId:t})).requirements?.featureRequirements?.fast_mode!==!1:!1",
                replace_str="return/*__codex_boji_fast_request__*/n===`chatgpt`||n===`apikey`?!0:!1",
                find_regex=r'return\s+([a-zA-Z_$]+)===`chatgpt`\?\(await [^;]+?fast_mode!==!1:!1',
                replace_fn=lambda m: f"return/*__codex_boji_fast_request__*/{m.group(1)}===`chatgpt`||{m.group(1)}===`apikey`?!0:!1",
                applied_marker=r'__codex_boji_fast_request__'
            )
            continue

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
    plugin_files = [f for f in files if file_contains(f, "pluginsDisabledTooltip")]
    plugin_new_files = []
    if not plugin_files:
        plugin_new_files = find_file("use-is-plugins-enabled-*.js",
                                     search_keywords=["plugins", "experimental-features"])
    if not plugin_files and not plugin_new_files:
        plugin_files = find_file("use-is-plugins-enabled-*.js",
                                 search_keywords=["plugins", "experimental-features"])
    i18n_files = []
    for f in (
        files
        + find_asset_files_containing("*.js", "__codex_boji_i18n__")
        + find_asset_files_containing("*.js", "enable_i18n")
    ):
        if f not in i18n_files and (
            file_contains(f, "__codex_boji_i18n__")
            or file_contains(f, "enable_i18n")
        ):
            i18n_files.append(f)
    if not files:
        if not plugin_files and not plugin_new_files and not i18n_files:
            print("  [FAIL] 未找到 app-main-*.js")
            return

    for filepath in plugin_files:
        # 补丁 2a: 插件侧边栏 — 门控变量 → 0
        # 新版: d?(0,$.jsx)(eo,{tooltipContent:...
        # 旧版: X?(0,$.jsx)(组件,{tooltipContent:...
        result = apply_patch(filepath,
            name="插件侧边栏解锁",
            find_str=None,
            replace_str=None,
            find_regex=r'([a-zA-Z_$])\?\(0,\$\.jsx\)\([a-zA-Z_$]+,\{tooltipContent:\(0,\$\.jsx\)\([a-zA-Z_$]+,\{id:`sidebarElectron\.pluginsDisabledTooltip`',
            replace_fn=lambda m: m.group(0).replace(m.group(1) + "?", "0?", 1),
            # 补丁后形态：门控变量已被替换为常量 0
            applied_marker=r'0\?\(0,\$\.jsx\)\([a-zA-Z_$]+,\{tooltipContent:\(0,\$\.jsx\)\([a-zA-Z_$]+,\{id:`sidebarElectron\.pluginsDisabledTooltip`'
        )

    for filepath in plugin_new_files:
        apply_patch(filepath,
            name="插件侧边栏解锁（新版 feature gate）",
            find_str="c?.enabled??!0",
            replace_str="/*__codex_boji_plugins_enabled__*/true",
            find_regex=r'[a-zA-Z_$]+\?\.enabled\?\?!0',
            replace_fn=lambda m: "/*__codex_boji_plugins_enabled__*/true",
            applied_marker=r'__codex_boji_plugins_enabled__'
        )

    for filepath in i18n_files:
        # 补丁 2b: i18n 多语言强制启用
        # Statsig 实验门控在无用户上下文时返回 false
        if file_contains(filepath, "__codex_boji_i18n__"):
            mark_skipped("i18n 多语言强制启用", "已应用", filepath)
        elif file_contains(filepath, "?.get(`enable_i18n`,!1)"):
            apply_patch(filepath,
                name="i18n 多语言强制启用（新版 Statsig）",
                find_str="s=a?.get(`enable_i18n`,!1)",
                replace_str="s=/*__codex_boji_i18n__*/!0",
                find_regex=r'([a-zA-Z_$]+)=([a-zA-Z_$]+)\?\.get\(`enable_i18n`,!1\)',
                replace_fn=lambda m: f"{m.group(1)}=/*__codex_boji_i18n__*/!0",
                applied_marker=r'__codex_boji_i18n__'
            )
        elif file_contains(filepath, "?.get(`enable_i18n`,!0)"):
            mark_skipped("i18n 多语言强制启用", "当前文件默认已启用", filepath)
        else:
            apply_patch(filepath,
                name="i18n 多语言强制启用",
                find_str=None,
                replace_str=None,
                find_regex=r'([a-zA-Z_$])=\(0,([a-zA-Z_$]+)\.useMemo\)\(\(\)=>[a-zA-Z_$]+\?\.get\(`enable_i18n`,!1\),\[([a-zA-Z_$]+)\]\)',
                replace_fn=lambda m: f"{m.group(1)}=(0,{m.group(2)}.useMemo)(()=>!0,[{m.group(3)}])",
                # 补丁后形态：useMemo 直接返回 !0，且原 enable_i18n 取值已被移除
                applied_marker=r'=\(0,[a-zA-Z_$]+\.useMemo\)\(\(\)=>!0,\[[a-zA-Z_$]+\]\)'
            )
    if not i18n_files:
        mark_skipped("i18n 多语言强制启用", "当前版本无 enable_i18n 门控")


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
    files = [f for f in files if file_contains(f, "!==`chatgpt`")]
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
            mark_skipped("品牌视觉统一", "当前版本无品牌视觉门控")
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
    auth_json_path = os.path.join(CODEX_HOME, "auth.json")
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
    print("\n[模块 7] 前端模型克隆注入 — model-queries / models-and-reasoning-efforts")
    files = find_file("models-and-reasoning-efforts-*.js",
                      search_keywords=["defaultModel", "useHiddenModels"])
    if not files:
        files = find_file("model-queries-*.js",
                          search_keywords=["list-models-for-host", "defaultModel"])
    if not files:
        print("  [FAIL] 未找到模型前端处理文件")
        return

    models_to_inject = fetch_user_models()
    js_array_str = json.dumps(models_to_inject)

    find_str = 'select:({data:r})=>{let i=[],a=new Set(e),o=null;return r.forEach(e=>{if(d?a.has(e.model):!e.hidden){let n=t===`copilot`?[e.supportedReasoningEfforts.find(e=>e.reasoningEffort===`medium`)??{reasoningEffort:`medium`,description:`medium effort`}]:[...e.supportedReasoningEfforts];i.push({...e,supportedReasoningEfforts:n}),e.isDefault&&(o=e)}}),o??=i.find(e=>e.model===n)??null,{models:i,defaultModel:o}}'
    
    # 精确替换字符串（已知特定版本，变量名固定为 r/n）
    replace_str = f'select:({{data:r}})=>{{let i=[];r.forEach(e=>{{i.push({{...e,hidden:false,supportedReasoningEfforts:[...e.supportedReasoningEfforts]}})}});let extraModels={js_array_str};let template=i[0];if(template){{extraModels.forEach(m=>{{if(!i.some(exist=>exist.model===m)){{let newModel={{...template}};for(let key in newModel){{if(typeof newModel[key]==="string"){{if(newModel[key]===template.model||newModel[key]===template.slug){{newModel[key]=m}}else if(newModel[key]===template.displayName||newModel[key]===template.display_name||newModel[key]===`GPT-5.5`){{newModel[key]=m.replace(/-/g," ").replace(/\\b\\w/g,c=>c.toUpperCase())}}}}}}newModel.model=m;newModel.slug=m;newModel.display_name=m.replace(/-/g," ").replace(/\\b\\w/g,c=>c.toUpperCase());newModel.displayName=newModel.display_name;newModel.isDefault=false;i.push(newModel)}}}})}}return {{models:i,defaultModel:i.find(e=>e.model===n)||i[0]||null}};}}'

    # 超强鲁棒性正则模糊匹配，防止未来混淆变量名发生改变
    find_regex = r'select\s*:\s*\(\{\s*data\s*:\s*([a-zA-Z_$]+)\s*\}\)\s*=>\s*\{.*?i\.find\(e=>e\.model===([a-zA-Z_$]+)\).*?defaultModel\s*:\s*[a-zA-Z_$]+\s*\}\}'
    
    def replace_fn(m):
        data_var = m.group(1)
        default_var = m.group(2)  # 从原始代码捕获默认模型变量名，不硬编码
        # 从 replace_str 派生，只替换变量名，确保 JS 结构与精确匹配版本完全一致
        out = replace_str
        out = out.replace('({data:r})', '({data:' + data_var + '})')
        out = out.replace('r.forEach', data_var + '.forEach')
        # rfind 替换最后一个 ===n) ，对应 defaultModel 变量
        last_idx = out.rfind('===n)')
        if last_idx >= 0:
            out = out[:last_idx] + '===' + default_var + ')' + out[last_idx + 5:]
        return out

    for filepath in files:
        basename = os.path.basename(filepath)
        # 精准幂等性检查
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        if "__codex_boji_extra_models__" in content or "extraModels" in content:
            results["skipped"].append(f"{basename}: 前端动态模型克隆注入")
            print(f"  [SKIP] 前端动态模型克隆注入 — 已应用")
            continue

        if basename.startswith("models-and-reasoning-efforts-"):
            new_func = (
                "function e({authMethod:e,availableModels:t,defaultModel:n,models:r,useHiddenModels:i})"
                "{let a=[],o=null,s=i&&e!==`amazonBedrock`;r.forEach(n=>{if(s?t.has(n.model):!n.hidden)"
                "{let t=e===`copilot`?[n.supportedReasoningEfforts.find(e=>e.reasoningEffort===`medium`)??"
                "{reasoningEffort:`medium`,description:`medium effort`}]:[...n.supportedReasoningEfforts];"
                "a.push({...n,hidden:false,supportedReasoningEfforts:t}),n.isDefault&&(o=n)}});"
                f"const __codex_boji_extra_models__={js_array_str},__codex_boji_template__=a[0];"
                "__codex_boji_template__&&__codex_boji_extra_models__.forEach(e=>{"
                "if(!a.some(t=>t.model===e||t.id===e||t.slug===e)){let n={...__codex_boji_template__};"
                "for(let r in n)typeof n[r]===`string`&&(n[r]===__codex_boji_template__.model||n[r]===__codex_boji_template__.id||n[r]===__codex_boji_template__.slug?"
                "n[r]=e:(n[r]===__codex_boji_template__.displayName||n[r]===__codex_boji_template__.display_name)&&(n[r]=e.replace(/-/g,\" \").replace(/\\b\\w/g,c=>c.toUpperCase())));"
                "n.model=e,n.id=e,n.slug=e,n.display_name=e.replace(/-/g,\" \").replace(/\\b\\w/g,c=>c.toUpperCase()),"
                "n.displayName=n.display_name,n.hidden=false,n.isDefault=false,a.push(n)}});"
                "o??=a.find(e=>e.model===n||e.id===n||e.slug===n)??null;return{models:a,defaultModel:o}}"
            )
            apply_patch(filepath,
                name="前端动态模型克隆注入（新版模型处理）",
                find_str=None,
                replace_str=None,
                find_regex=r'function\s+e\(\{authMethod:e,availableModels:t,defaultModel:n,models:r,useHiddenModels:i\}\)\{.*?\{models:a,defaultModel:o\}\}',
                replace_fn=lambda m: new_func,
                applied_marker=r'__codex_boji_extra_models__'
            )
            continue

        apply_patch(filepath,
            name="前端动态模型克隆注入",
            find_str=find_str,
            replace_str=replace_str,
            find_regex=find_regex,
            replace_fn=replace_fn
        )


# ================================================================
# 模块 8: 清理旧版状态栏实验残留
# ================================================================
def cleanup_legacy_status_injection():
    """Remove abandoned experimental status UI snippets from older builds."""
    print("\n[模块 8] 清理旧版状态栏残留")
    targets = [
        (find_build_file("main-*.js", search_keywords=["codex_boji:usage-summary"]),
         "旧版状态栏 main IPC", "__codex_boji_usage_summary_ipc__"),
        (find_build_file("preload.js", search_keywords=["codexBojiBridge"]),
         "旧版状态栏 preload bridge", "__codex_boji_usage_summary_preload__"),
        (find_file("local-conversation-thread-*.js", search_keywords=["__codex_boji_context_hud__"]),
         "旧版状态栏 UI", "__codex_boji_context_hud__"),
    ]
    removed = 0
    for files, name, marker in targets:
        for filepath in files:
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    if marker not in f.read():
                        continue
                if remove_js_once(filepath, name, marker):
                    removed += 1
            except OSError:
                continue
    if removed == 0:
        print("  [OK]   未发现旧版状态栏残留")


# ================================================================
# 模型注入: 从中转站拉取模型列表，注入 models_cache.json
# ================================================================
def inject_models():
    """从中转站 /v1/models 拉取模型，补充到 Codex 模型列表"""
    print("\n[模块 9] 模型下拉注入")

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
    print("\n[模块 10] 补全 config.toml")
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
# 本地会话加载: 重建 session_index.jsonl
# ================================================================
def _extract_text_from_content(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
            elif isinstance(item, str):
                parts.append(item)
        return " ".join(parts)
    return ""


def _title_from_message(text):
    text = re.sub(r"<environment_context>.*?</environment_context>", " ", text or "", flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    return text[:60]


def _parse_session_file(path):
    session_id = None
    created_at = None
    updated_at = None
    title = None

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                timestamp = obj.get("timestamp")
                if isinstance(timestamp, str):
                    updated_at = timestamp
                    if not created_at:
                        created_at = timestamp

                payload = obj.get("payload")
                if obj.get("type") == "session_meta" and isinstance(payload, dict):
                    if isinstance(payload.get("id"), str):
                        session_id = payload["id"]
                    if isinstance(payload.get("timestamp"), str):
                        created_at = payload["timestamp"]
                        updated_at = updated_at or payload["timestamp"]
                    continue

                if title or not isinstance(payload, dict):
                    continue

                if payload.get("type") == "user_message":
                    title = _title_from_message(payload.get("message"))
                elif payload.get("type") == "message" and payload.get("role") == "user":
                    title = _title_from_message(_extract_text_from_content(payload.get("content")))
    except OSError:
        return None

    if not session_id:
        stem = os.path.splitext(os.path.basename(path))[0]
        m = re.search(r"(019[a-z0-9-]{32,})", stem)
        session_id = m.group(1) if m else stem

    if not updated_at:
        updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(os.path.getmtime(path)))

    if not title:
        title = f"Local session {session_id[:8]}"

    return {
        "id": session_id,
        "thread_name": title,
        "updated_at": updated_at,
    }


def _iter_local_session_files():
    for base in (SESSIONS_DIR, ARCHIVED_SESSIONS_DIR):
        if not os.path.isdir(base):
            continue
        for root, _, files in os.walk(base):
            for name in files:
                if name.endswith(".jsonl"):
                    yield os.path.join(root, name)


def rebuild_local_session_index():
    """Merge every local session file into CODEX_HOME/session_index.jsonl."""
    print("\n[模块 11] 加载本地会话")

    codex_home = os.path.dirname(SESSION_INDEX)
    if not os.path.isdir(codex_home):
        print(f"  [SKIP] Codex 配置目录不存在: {codex_home}")
        return

    existing = {}
    existing_order = []
    bad_lines = 0
    if os.path.exists(SESSION_INDEX):
        with open(SESSION_INDEX, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    bad_lines += 1
                    continue
                session_id = item.get("id")
                if not isinstance(session_id, str) or not session_id:
                    bad_lines += 1
                    continue
                if session_id not in existing:
                    existing_order.append(session_id)
                existing[session_id] = {
                    "id": session_id,
                    "thread_name": item.get("thread_name") or f"Local session {session_id[:8]}",
                    "updated_at": item.get("updated_at") or "",
                }

    discovered = []
    for path in _iter_local_session_files():
        item = _parse_session_file(path)
        if item:
            discovered.append(item)

    if not discovered:
        print("  [SKIP] 未找到本地会话文件")
        return

    added = 0
    refreshed = 0
    for item in discovered:
        session_id = item["id"]
        if session_id not in existing:
            existing_order.append(session_id)
            existing[session_id] = item
            added += 1
            continue
        # 保留已有标题；只在本地文件更新时间更晚时刷新 updated_at。
        old = existing[session_id]
        if item.get("updated_at", "") > old.get("updated_at", ""):
            old["updated_at"] = item["updated_at"]
            refreshed += 1

    if added == 0 and refreshed == 0 and bad_lines == 0:
        print(f"  [SKIP] 会话索引已完整，本地会话: {len(discovered)} 个")
        return

    if os.path.exists(SESSION_INDEX):
        bak = SESSION_INDEX + ".bak"
        shutil.copy2(SESSION_INDEX, bak)
        print(f"  已备份: {bak}")

    items = [existing[sid] for sid in existing_order if sid in existing]
    items.sort(key=lambda x: x.get("updated_at") or "", reverse=False)

    with open(SESSION_INDEX, "w", encoding="utf-8", newline="\n") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")

    print(f"  扫描本地会话: {len(discovered)} 个")
    print(f"  新增索引: {added} 个")
    if refreshed:
        print(f"  更新时间: {refreshed} 个")
    if bad_lines:
        print(f"  清理异常索引行: {bad_lines} 行")


# ================================================================
# Electron fuses + 代码签名（跨平台，内置于 patch.py，无需依赖外部脚本）
def validate_patched_syntax():
    """补丁后用 node --check 校验被修改的 JS 文件语法。

    这是关键安全网：如果某条补丁的替换破坏了 JS 语法（如括号不配对），
    Codex 启动时 webview 会崩溃卡 logo。这里在写 fuse 之前提前发现语法错误，
    并自动从备份恢复对应文件，避免用户拿到一个打不开的 Codex。
    返回 True 表示全部合法（或无法校验时放行），False 表示发现语法错误并已回滚。"""
    print("\n[校验] 补丁后 JS 语法检查")

    if not patched_files:
        print("  无新修改文件，跳过校验")
        return True

    node = resolve_executable("node")
    if not node:
        print("  [WARN] 未找到 node，跳过语法校验（建议安装 Node.js 以启用此安全检查）")
        return True

    import tempfile
    bad = []
    for fp in sorted(patched_files):
        basename = os.path.basename(fp)
        try:
            # 复制成 .mjs 让 node 按 ES module 解析（这些文件用 import/export）
            tmpdir = tempfile.mkdtemp()
            mjs = os.path.join(tmpdir, basename.replace(".js", ".mjs"))
            shutil.copyfile(fp, mjs)
            r = run_command(["node", "--check", mjs],
                            capture_output=True, text=True, timeout=60)
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception as e:
            print(f"  [WARN] {basename} 无法校验: {e}")
            continue
        if r.returncode == 0:
            print(f"  [OK]   {basename}")
        else:
            # 提取 SyntaxError 行
            err_line = ""
            for line in (r.stderr or "").splitlines():
                if "Error:" in line or "SyntaxError" in line:
                    err_line = line.strip()
                    break
            print(f"  [FAIL] {basename} 语法错误: {err_line}")
            bad.append(fp)

    if not bad:
        print("  全部补丁文件语法合法")
        return True

    # 发现语法错误：从备份 asar 恢复受损文件，避免 Codex 打不开
    print(f"\n  [严重] {len(bad)} 个文件被补丁改出语法错误，正在从备份恢复...")
    restored = _restore_files_from_backup(bad)
    if restored:
        print(f"  已恢复 {restored} 个文件到原始版本（对应功能未生效，但 Codex 可正常启动）")
    else:
        print("  [WARN] 自动恢复失败，建议运行: python patch.py --rollback")
    return False


def _restore_files_from_backup(file_paths):
    """从 app.asar.bak 提取原始版本，覆盖指定的受损文件。返回成功恢复的数量。"""
    asar_bak = os.path.join(CODEX_RESOURCES, "app.asar.bak")
    if not os.path.isfile(asar_bak):
        return 0
    if not resolve_executable("npx"):
        return 0
    import tempfile
    extract_dir = tempfile.mkdtemp()
    try:
        r = run_command(["npx", "-y", "@electron/asar", "e", asar_bak, extract_dir],
                        capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            return 0
        count = 0
        for fp in file_paths:
            candidates = []
            if BASE and _path_is_within(fp, BASE):
                rel = os.path.relpath(fp, BASE)
                candidates.append(os.path.join(extract_dir, "webview", "assets", rel))
            app_dir = os.path.join(CODEX_RESOURCES, "app")
            if _path_is_within(fp, app_dir):
                rel = os.path.relpath(fp, app_dir)
                candidates.append(os.path.join(extract_dir, rel))
            for orig in candidates:
                if os.path.isfile(orig):
                    shutil.copyfile(orig, fp)
                    count += 1
                    break
        return count
    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)


def _path_is_within(path, root):
    try:
        path_abs = os.path.abspath(path)
        root_abs = os.path.abspath(root)
        return os.path.commonpath([path_abs, root_abs]) == root_abs
    except (OSError, ValueError):
        return False


def _write_fuse(value, retries=4, delay=1.5):
    """写单个 Electron fuse，带重试。

    Windows 上 @electron/fuses 连续写同一个 Codex.exe 时，前一次的文件句柄
    可能还没释放，导致 EBUSY: resource busy or locked。这里捕获该错误并
    退避重试，使多 fuse 连续写入在任何机器上都稳定。
    返回 (是否成功, 最后一次 stderr)。"""
    last_err = ""
    for attempt in range(1, retries + 1):
        try:
            r = run_command(
                ["npx", "-y", "@electron/fuses", "write", "--app", CODEX_APP, value],
                capture_output=True, text=True, timeout=120
            )
        except Exception as e:
            last_err = str(e)
            time.sleep(delay)
            continue
        if r.returncode == 0:
            return True, ""
        last_err = (r.stderr or "").strip()
        # EBUSY / 锁定 / 占用 -> 等待后重试；其它错误（如权限）直接返回
        if "EBUSY" in last_err or "resource busy" in last_err or "locked" in last_err:
            if attempt < retries:
                print(f"         {value} 文件被占用，{delay}s 后重试 ({attempt}/{retries})...")
                time.sleep(delay)
                continue
        else:
            break
    return False, last_err


def _is_unsupported_fuse_error(err):
    return bool(err) and (
        "Could not find sentinel" in err
        or "fuses are only supported in Electron 12 and higher" in err
    )


def _split_rel_path(rel):
    return [p for p in re.split(r"[\\/]+", rel.strip("\\/")) if p]


def _app_package_main(app_dir):
    package_json = os.path.join(app_dir, "package.json")
    try:
        with open(package_json, "r", encoding="utf-8") as f:
            main_entry = json.load(f).get("main")
        if isinstance(main_entry, str) and main_entry.strip():
            return main_entry.strip()
    except Exception:
        pass
    return ".vite/build/bootstrap.js"


def _app_dir_is_complete(app_dir):
    if not os.path.isdir(app_dir):
        return False

    main_entry = _app_package_main(app_dir)
    required = [
        os.path.join(app_dir, "package.json"),
        os.path.join(app_dir, *_split_rel_path(main_entry)),
        os.path.join(app_dir, "webview", "assets"),
    ]
    assets_dir = os.path.join(app_dir, "webview", "assets")
    has_app_main = bool(glob.glob(os.path.join(assets_dir, "app-main-*.js")))
    return all(os.path.exists(p) for p in required) and has_app_main


def _extract_asar_to_app(asar_path, app_dir):
    if not os.path.isfile(asar_path):
        print(f"  [WARN] 解包源不存在: {asar_path}")
        return False
    if not resolve_executable("npx"):
        print("[ERROR] 未找到 npx，请先安装 Node.js: https://nodejs.org")
        return False

    if os.path.isdir(app_dir):
        _remove_tree_robust(app_dir)
    print(f"\n[准备] 提取 {os.path.basename(asar_path)}...")

    # @electron/asar resolves unpacked files from "<archive>.unpacked". After
    # the original archive has been renamed to app.asar1, that would become
    # app.asar1.unpacked, but Electron packages keep them in app.asar.unpacked.
    # Use a temporary hard/copy named app.asar so extraction can see the normal
    # unpacked directory without renaming the user's original backup.
    extract_source = asar_path
    temp_extract_source = None
    normal_asar = os.path.join(os.path.dirname(asar_path), "app.asar")
    if os.path.basename(asar_path).lower() != "app.asar":
        temp_extract_source = normal_asar + ".extract"
        temp_unpacked = temp_extract_source + ".unpacked"
        try:
            if os.path.exists(temp_extract_source):
                os.remove(temp_extract_source)
            if os.path.isdir(temp_unpacked):
                _remove_tree_robust(temp_unpacked)
            elif os.path.exists(temp_unpacked):
                os.remove(temp_unpacked)
            shutil.copy2(asar_path, temp_extract_source)
            unpacked = _asar_unpacked_path(asar_path)
            backup_unpacked = os.path.join(os.path.dirname(asar_path), "app.asar.unpacked.bak")
            normal_unpacked = normal_asar + ".unpacked"
            if os.path.isdir(unpacked):
                _copy_tree_robust(unpacked, temp_unpacked)
            elif os.path.isdir(backup_unpacked):
                _copy_tree_robust(backup_unpacked, temp_unpacked)
            elif os.path.isdir(normal_unpacked):
                # Junctions would be nicer, but copying avoids extra shell
                # quoting and works on machines without Developer Mode.
                _copy_tree_robust(normal_unpacked, temp_unpacked)
            extract_source = temp_extract_source
        except Exception as e:
            if os.path.exists(temp_extract_source):
                try:
                    os.remove(temp_extract_source)
                except OSError:
                    pass
            if os.path.isdir(temp_unpacked):
                _remove_tree_robust(temp_unpacked)
            print(f"  [ERROR] 无法准备临时解包源: {e}")
            return False

    result = run_command(
        ["npx", "-y", "@electron/asar", "e", extract_source, app_dir],
        capture_output=True, text=True, timeout=300
    )
    if temp_extract_source:
        try:
            if os.path.exists(temp_extract_source):
                os.remove(temp_extract_source)
            temp_unpacked = temp_extract_source + ".unpacked"
            if os.path.isdir(temp_unpacked):
                _remove_tree_robust(temp_unpacked)
        except OSError:
            pass
    if result.returncode != 0:
        print(f"[ERROR] 提取失败:\n{result.stderr}")
        return False
    if not _app_dir_is_complete(app_dir):
        print("  [ERROR] 提取后的 app/ 不完整，缺少 package.json、.vite/build 或 webview/assets")
        return False
    print("  提取完成")
    return True


def prepare_app_dir():
    """Ensure CODEX_RESOURCES/app is a complete, clean extraction source.

    Prefer app.asar1/app.asar.bak once they exist, because app.asar may be the
    repacked patched archive from a previous run. If that repacked archive was
    bad, extracting from it would preserve the corruption.
    """
    asar_path = os.path.join(CODEX_RESOURCES, "app.asar")
    asar1_path = os.path.join(CODEX_RESOURCES, "app.asar1")
    asar_bak = os.path.join(CODEX_RESOURCES, "app.asar.bak")
    app_dir = os.path.join(CODEX_RESOURCES, "app")

    if not any(os.path.exists(p) for p in (asar_path, asar1_path, asar_bak)):
        print(f"\n[ERROR] 未找到 app.asar、app.asar1 或 app.asar.bak: {CODEX_RESOURCES}")
        print("  请确认 Codex 已正确安装。")
        return False

    if os.path.exists(asar_path) and not os.path.exists(asar1_path):
        os.rename(asar_path, asar1_path)
        print("  已重命名 app.asar -> app.asar1")

    pristine_asar = asar1_path if os.path.exists(asar1_path) else asar_bak

    if _app_dir_is_complete(app_dir):
        return True

    # If app/ is missing or incomplete, never trust the current app.asar when a
    # pristine archive exists.
    if pristine_asar and os.path.exists(pristine_asar):
        return _extract_asar_to_app(pristine_asar, app_dir)

    return _extract_asar_to_app(asar_path, app_dir)


def audit_packed_app():
    print("\n[校验] app.asar 启动结构检查")

    if not CODEX_RESOURCES:
        print("  [FAIL] 未定位 resources 目录")
        return False

    asar_path = os.path.join(CODEX_RESOURCES, "app.asar")
    unpacked_dir = asar_path + ".unpacked"
    app_dir = os.path.join(CODEX_RESOURCES, "app")
    main_entry = _app_package_main(app_dir)
    required_entries = [
        ("package.json", "package.json", "entry"),
        (main_entry.replace("/", "\\"), main_entry, "entry"),
        ("webview\\assets", "webview\\assets", "tree"),
        ("webview\\assets\\app-main-*", "webview\\assets\\app-main", "prefix"),
        ("node_modules\\better-sqlite3\\lib\\database.js", "node_modules\\better-sqlite3\\lib\\database.js", "entry"),
        ("node_modules\\better-sqlite3\\build\\Release\\better_sqlite3.node", "node_modules\\better-sqlite3\\build\\Release\\better_sqlite3.node", "unpacked"),
        ("node_modules\\node-pty\\lib\\index.js", "node_modules\\node-pty\\lib\\index.js", "entry"),
        ("node_modules\\node-pty\\build\\Release\\pty.node", "node_modules\\node-pty\\build\\Release\\pty.node", "unpacked"),
        ("node_modules\\node-pty\\build\\Release\\winpty.dll", "node_modules\\node-pty\\build\\Release\\winpty.dll", "unpacked"),
        ("node_modules\\node-pty\\build\\Release\\winpty-agent.exe", "node_modules\\node-pty\\build\\Release\\winpty-agent.exe", "unpacked"),
        ("node_modules\\@worklouder\\device-kit-oai\\node_modules\\@worklouder\\wl-device-kit\\node_modules\\node-hid\\build\\Release\\HID.node", "node_modules\\@worklouder\\device-kit-oai\\node_modules\\@worklouder\\wl-device-kit\\node_modules\\node-hid\\build\\Release\\HID.node", "unpacked"),
    ]

    if not os.path.isfile(asar_path):
        print(f"  [FAIL] 缺少 app.asar: {asar_path}")
        return False
    if not resolve_executable("npx"):
        print("  [WARN] 未找到 npx，跳过 app.asar 内容检查")
        return True

    try:
        r = run_command(["npx", "-y", "@electron/asar", "l", asar_path],
                        capture_output=True, text=True, timeout=120)
    except Exception as e:
        print(f"  [FAIL] app.asar 列表读取失败: {e}")
        return False
    if r.returncode != 0:
        print(f"  [FAIL] app.asar 列表读取失败: {(r.stderr or '').strip()}")
        return False

    entries = set(line.strip().lstrip("\\/") for line in r.stdout.splitlines() if line.strip())
    ok = True
    for label, rel, mode in required_entries:
        rel_norm = rel.replace("/", "\\").strip("\\/")
        if mode == "prefix":
            in_asar = any(e == rel_norm or e.startswith(rel_norm) for e in entries)
        elif mode == "tree":
            in_asar = rel_norm in entries or any(e.startswith(rel_norm + "\\") for e in entries)
        else:
            in_asar = rel_norm in entries
        in_unpacked = os.path.exists(os.path.join(unpacked_dir, *_split_rel_path(rel_norm)))
        exists = in_asar or in_unpacked
        if mode == "unpacked":
            exists = in_unpacked
        print(f"  [{'OK' if exists else 'FAIL'}] {label}")
        ok = ok and exists
    return ok


def repack_patched_asar():
    """Pack the patched app/ directory back into app.asar.

    Newer Codex/Electron shells may keep OnlyLoadAppFromAsar enabled or may not
    expose writable fuses. Keeping a patched app.asar lets Codex start through
    the normal production path instead of relying on Electron loading app/.
    """
    print("\n[模块 12] 重新打包 app.asar")

    if not CODEX_RESOURCES:
        print("  [WARN] 未定位到 resources 目录，跳过 app.asar 打包。")
        return False

    app_dir = os.path.join(CODEX_RESOURCES, "app")
    asar_path = os.path.join(CODEX_RESOURCES, "app.asar")
    tmp_asar = asar_path + ".tmp"
    unpacked_dir = asar_path + ".unpacked"
    tmp_unpacked_dir = tmp_asar + ".unpacked"

    if not _app_dir_is_complete(app_dir):
        print(f"  [WARN] app/ 目录不完整，跳过打包: {app_dir}")
        return False

    if not resolve_executable("npx"):
        print("  [WARN] 未找到 npx，无法重新打包 app.asar。")
        print("         Codex 可能会显示 Electron 默认页，请安装 Node.js 后重跑。")
        return False

    for tmp_path in (tmp_asar, tmp_unpacked_dir):
        try:
            if os.path.isdir(tmp_path):
                _remove_tree_robust(tmp_path)
            elif os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError as e:
            print(f"  [WARN] 无法删除旧临时文件: {e}")
            return False

    try:
        result = run_command(
            [
                "npx", "-y", "@electron/asar", "pack",
                "--unpack-dir", "node_modules/{@worklouder,better-sqlite3,node-pty}",
                app_dir,
                tmp_asar,
            ],
            capture_output=True, text=True, timeout=300
        )
    except Exception as e:
        print(f"  [WARN] app.asar 打包异常: {e}")
        return False

    if result.returncode != 0:
        print("  [WARN] app.asar 打包失败")
        err = (result.stderr or result.stdout or "").strip()
        if err:
            print(f"         {err.splitlines()[-1] if err.splitlines() else err}")
        try:
            if os.path.exists(tmp_asar):
                os.remove(tmp_asar)
        except OSError:
            pass
        return False

    try:
        _replace_file_retry(tmp_asar, asar_path)
        if os.path.isdir(tmp_unpacked_dir):
            # Electron derives this path from app.asar. If we leave the
            # temporary app.asar.tmp.unpacked directory in place, native
            # modules such as better-sqlite3 resolve against stale files.
            _replace_tree_retry(tmp_unpacked_dir, unpacked_dir, CODEX_RESOURCES)
    except OSError as e:
        print(f"  [WARN] 无法替换 app.asar: {e}")
        return False

    print(f"  [OK]   已生成补丁版 app.asar: {asar_path}")
    if os.path.isdir(unpacked_dir):
        print(f"  [OK]   已同步原生模块目录: {unpacked_dir}")
    return True


def _codesign_macos():
    if PLATFORM != "macos":
        return

    print("\n[模块 14] macOS 重新签名")
    if not resolve_executable("codesign"):
        print("  [WARN] 未找到 codesign（需要 Xcode Command Line Tools），跳过。")
        return
    try:
        r = run_command(
            ["codesign", "--force", "--deep", "--sign", "-", CODEX_APP],
            capture_output=True, text=True, timeout=180
        )
        if r.returncode == 0:
            print(f"  [OK]   已重新签名 {CODEX_APP}")
        else:
            print(f"  [WARN] 重新签名失败: {r.stderr.strip()}")
            print("         若 Codex 无法启动，请手动执行:")
            print(f"         codesign --force --deep --sign - {CODEX_APP}")
    except Exception as e:
        print(f"  [WARN] codesign 执行异常: {e}")


# ================================================================
def apply_fuses_and_sign():
    """关闭 Electron 安全熔断器，让 Codex 从解包的 app/ 目录加载修改后的 JS。
    macOS 还需重新签名，否则 Gatekeeper 拒绝启动被修改的应用。
    所有步骤跨平台统一，使 `python patch.py` 在任何机器上都能独立完成补丁。"""
    print("\n[模块 13] 禁用 Electron 安全熔断器")

    if not CODEX_APP:
        print("  [WARN] 未定位到 Codex 可执行文件，跳过 fuse 设置。")
        print("         Codex 可能无法加载补丁，请手动执行 @electron/fuses。")
        _codesign_macos()
        return

    packed_asar = os.path.join(CODEX_RESOURCES, "app.asar") if CODEX_RESOURCES else None
    if packed_asar and os.path.isfile(packed_asar):
        print("  [SKIP] 已生成补丁版 app.asar，不需要依赖解包目录启动")
        _codesign_macos()
        return

    if not resolve_executable("npx"):
        print("  [WARN] 未找到 npx，跳过 fuse 设置。请安装 Node.js 后重跑。")
        _codesign_macos()
        return

    # 写 fuse 前确保 Codex 进程已退出并释放文件句柄
    kill_codex()
    _wait_exe_unlocked(CODEX_APP)

    fuses = [
        "OnlyLoadAppFromAsar=off",
        "EnableEmbeddedAsarIntegrityValidation=off",
        "GrantFileProtocolExtraPrivileges=off",
        "EnableCookieEncryption=off",
    ]
    all_ok = True
    for fuse in fuses:
        ok, err = _write_fuse(fuse)
        if ok:
            print(f"  [OK]   {fuse}")
        elif _is_unsupported_fuse_error(err):
            print(f"  [SKIP] {fuse} — 当前 Codex 外壳不支持 Electron fuse 写入")
        else:
            all_ok = False
            print(f"  [WARN] fuse {fuse} 设置失败（可能需要管理员/sudo 权限）")
            if err:
                print(f"         {err.splitlines()[-1] if err.splitlines() else err}")
    if not all_ok:
        print("  [HINT] 若 Codex 启动后补丁未生效，请以管理员/sudo 身份重跑本脚本。")

    _codesign_macos()


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
def check_prerequisites():
    """检查必备依赖（Node.js + Python 3）。
    只检测、给出对应系统的安装命令提示，不自动下载/执行——影响系统的操作必须由用户决定。
    返回 True 表示依赖齐全可继续，False 表示缺失（main 中会退出）。"""
    print("\n[环境检查] 检测前置依赖...")
    missing = []

    # Node.js（npx 是它的一部分）
    npx_path = resolve_executable("npx")
    if npx_path:
        print(f"  [OK]   Node.js (npx): {npx_path}")
    else:
        print("  [缺]   Node.js (未找到 npx)")
        missing.append("node")

    # Python 自身已经在跑，但提示 3.x（兼容性参考）
    py_ver = "{}.{}".format(sys.version_info.major, sys.version_info.minor)
    print(f"  [OK]   Python: {py_ver} ({sys.executable})")

    if not missing:
        print("  依赖齐全，继续。")
        return True

    # 给对应系统的安装命令提示（不自动执行）
    print("\n[ERROR] 缺少必要依赖，无法继续。请按以下命令自行安装后重试：\n")
    if "node" in missing:
        print("  Node.js 安装方式（任选其一）：")
        if sys.platform == "win32":
            print("    1) 用 winget（Windows 10/11 自带）：")
            print("       winget install OpenJS.NodeJS.LTS")
            print("    2) 用 Chocolatey：")
            print("       choco install nodejs-lts")
            print("    3) 直接下载安装包：https://nodejs.org/en/download")
        elif sys.platform == "darwin":
            print("    1) 用 Homebrew：")
            print("       brew install node")
            print("    2) 直接下载安装包：https://nodejs.org/en/download")
        else:  # linux
            print("    Debian/Ubuntu:  sudo apt install nodejs npm")
            print("    Fedora/RHEL:    sudo dnf install nodejs")
            print("    Arch:           sudo pacman -S nodejs npm")
            print("    或下载安装包：  https://nodejs.org/en/download")
        print("\n  提示：本脚本不会自动安装系统依赖，以上命令需要你手动执行。")
    return False


def _windows_known_folder(name):
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", f"[Environment]::GetFolderPath('{name}')"],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return None


def _create_windows_shortcut(shortcut_path, label):
    os.makedirs(os.path.dirname(shortcut_path), exist_ok=True)
    if os.path.isfile(shortcut_path):
        print(f"  {label}快捷方式已存在: {WINDOWS_SHORTCUT_NAME}")
        return

    ps_script = f'''
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut("{shortcut_path}")
$sc.TargetPath = "{CODEX_APP}"
$sc.WorkingDirectory = "{os.path.dirname(CODEX_APP)}"
$sc.IconLocation = "{CODEX_APP},0"
$sc.Description = "Codex-boji (API Key Patched)"
$sc.Save()
'''
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_script],
        capture_output=True, text=True, timeout=15
    )
    if r.returncode == 0:
        print(f"  {label}快捷方式已创建: {WINDOWS_SHORTCUT_NAME}")
    else:
        print(f"  [WARN] 创建{label}快捷方式失败: {r.stderr.strip()}")
        print(f"         你可以手动创建快捷方式指向: {CODEX_APP}")


def create_desktop_shortcut():
    """创建 'Codex-boji' 快捷方式，指向补丁版 Codex.exe。
    仅 Windows 生效（macOS/Linux 用户直接从 Applications 或命令行启动）。
    使用 PowerShell COM 对象创建 .lnk，不依赖第三方库。"""
    if sys.platform != "win32" or not CODEX_APP:
        return

    targets = []
    desktop = _windows_known_folder("Desktop") or os.path.join(os.path.expanduser("~"), "Desktop")
    if desktop:
        targets.append((os.path.join(desktop, f"{WINDOWS_SHORTCUT_NAME}.lnk"), "桌面"))

    start_menu = _windows_known_folder("StartMenu")
    if start_menu:
        targets.append((os.path.join(start_menu, "Programs", f"{WINDOWS_SHORTCUT_NAME}.lnk"), "开始菜单"))

    print()
    for shortcut_path, label in targets:
        try:
            _create_windows_shortcut(shortcut_path, label)
        except Exception as e:
            print(f"  [WARN] 创建{label}快捷方式异常: {e}")
            print(f"         你可以手动创建快捷方式指向: {CODEX_APP}")


def _windows_standalone_root():
    localappdata = os.environ.get("LOCALAPPDATA")
    if not localappdata:
        return None
    preferred = os.path.join(localappdata, WINDOWS_STANDALONE_DIR_NAME)
    if os.path.isdir(preferred):
        return preferred
    for name in WINDOWS_LEGACY_STANDALONE_DIR_NAMES:
        legacy = os.path.join(localappdata, name)
        if os.path.isdir(legacy):
            return legacy
    return preferred


def _windows_preferred_standalone_root():
    localappdata = os.environ.get("LOCALAPPDATA")
    if not localappdata:
        return None
    return os.path.join(localappdata, WINDOWS_STANDALONE_DIR_NAME)


def _windows_all_standalone_roots():
    localappdata = os.environ.get("LOCALAPPDATA")
    if not localappdata:
        return []
    roots = [os.path.join(localappdata, WINDOWS_STANDALONE_DIR_NAME)]
    active = _read_active_build_root()
    if active:
        roots.append(active)
    roots.append(os.path.join(localappdata, WINDOWS_STANDALONE_DIR_NAME + ".repair"))
    roots.extend(os.path.join(localappdata, name) for name in WINDOWS_LEGACY_STANDALONE_DIR_NAMES)
    seen = set()
    unique = []
    for root in roots:
        norm = os.path.normcase(os.path.abspath(root))
        if norm not in seen:
            unique.append(root)
            seen.add(norm)
    return unique


def _windows_shortcut_paths():
    """Return shortcut paths created by this project on Windows."""
    if sys.platform != "win32":
        return []
    candidates = []
    home = os.path.expanduser("~")
    shortcut_names = [WINDOWS_SHORTCUT_NAME] + WINDOWS_LEGACY_SHORTCUT_NAMES
    candidates.extend(os.path.join(home, "Desktop", f"{name}.lnk") for name in shortcut_names)
    appdata = os.environ.get("APPDATA", "")
    programdata = os.environ.get("PROGRAMDATA", "")
    if appdata:
        candidates.extend(os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs", f"{name}.lnk") for name in shortcut_names)
    if programdata:
        candidates.extend(os.path.join(programdata, "Microsoft", "Windows", "Start Menu", "Programs", f"{name}.lnk") for name in shortcut_names)

    seen = set()
    unique = []
    for path in candidates:
        norm = os.path.normcase(os.path.abspath(path))
        if norm not in seen:
            unique.append(path)
            seen.add(norm)
    return unique


def _shortcut_target(path):
    if sys.platform != "win32" or not os.path.isfile(path):
        return None
    ps = f'''
$ErrorActionPreference = "Stop"
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut("{path}")
$sc.TargetPath
'''
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return None


def _remove_windows_shortcuts_for_root(root):
    removed = []
    if not root:
        return removed
    root_abs = os.path.normcase(os.path.abspath(root))
    for shortcut in _windows_shortcut_paths():
        if not os.path.isfile(shortcut):
            continue
        target = _shortcut_target(shortcut)
        if not target:
            if os.path.splitext(os.path.basename(shortcut))[0] in ([WINDOWS_SHORTCUT_NAME] + WINDOWS_LEGACY_SHORTCUT_NAMES):
                try:
                    os.remove(shortcut)
                    removed.append(shortcut)
                except OSError as e:
                    print(f"  [WARN] 删除快捷方式失败: {shortcut} ({e})")
            continue
        target_abs = os.path.normcase(os.path.abspath(target))
        if target_abs.startswith(root_abs + os.sep) or target_abs == os.path.normcase(os.path.abspath(os.path.join(root, "Codex.exe"))):
            try:
                os.remove(shortcut)
                removed.append(shortcut)
            except OSError as e:
                print(f"  [WARN] 删除快捷方式失败: {shortcut} ({e})")
    return removed


def _kill_windows_processes_under(root):
    """Kill only Codex processes whose executable is inside the standalone root."""
    if sys.platform != "win32" or not root:
        return 0
    ps = f'''
$root = [System.IO.Path]::GetFullPath("{root}").TrimEnd("\\")
$count = 0
Get-CimInstance Win32_Process -Filter "name = 'Codex.exe' or name = 'codex.exe'" | ForEach-Object {{
    if ($_.ExecutablePath) {{
        $exe = [System.IO.Path]::GetFullPath($_.ExecutablePath)
        if ($exe.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {{
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            $count += 1
        }}
    }}
}}
$count
'''
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, timeout=15
        )
        if r.returncode == 0 and r.stdout.strip().isdigit():
            return int(r.stdout.strip())
    except Exception:
        pass
    return 0


def uninstall_standalone():
    """Remove the Windows standalone copy and shortcuts created by this project."""
    if sys.platform != "win32":
        print(f"[ERROR] --uninstall 目前只处理 Windows 上自动创建的 {WINDOWS_STANDALONE_DIR_NAME}。")
        print("        macOS/Linux 请使用 --rollback 后手动删除对应安装目录。")
        sys.exit(1)

    roots = _windows_all_standalone_roots()
    if not roots:
        print(f"[ERROR] 未找到 LOCALAPPDATA，无法定位 {WINDOWS_STANDALONE_DIR_NAME}。")
        sys.exit(1)

    print("=" * 60)
    print(f"  {WINDOWS_STANDALONE_DIR_NAME} Uninstall")
    print("=" * 60)

    any_removed = False
    all_shortcuts = []
    for root in roots:
        print(f"[INFO] 目标目录: {root}")

        killed = _kill_windows_processes_under(root)
        if killed:
            print(f"  已关闭补丁版 Codex 进程: {killed}")

        removed_shortcuts = _remove_windows_shortcuts_for_root(root)
        all_shortcuts.extend(removed_shortcuts)
        for shortcut in removed_shortcuts:
            print(f"  已删除快捷方式: {shortcut}")

        root_existed = os.path.isdir(root)
        if root_existed:
            exe = os.path.join(root, "Codex.exe")
            if os.path.isfile(exe):
                _wait_exe_unlocked(exe, timeout=8.0)
            try:
                shutil.rmtree(root)
                print(f"  已删除目录: {root}")
                any_removed = True
            except OSError as e:
                print(f"  [ERROR] 删除目录失败: {e}")
                print("          请确认补丁版 Codex 已退出，然后重新运行卸载。")
                sys.exit(1)
        else:
            print("  目录不存在，跳过。")

    if not all_shortcuts and not any_removed:
        print("  未发现需要删除的补丁版文件。")

    print("\n卸载完成。官方 Store 版 Codex 不会被删除。")


def sync_store_to_boji():
    """Replace Codex-boji with the current Microsoft Store Codex copy."""
    if sys.platform != "win32":
        print(f"[ERROR] --sync-store 目前只支持 Windows 上的 {WINDOWS_STANDALONE_DIR_NAME}。")
        sys.exit(1)

    try:
        store = _find_windows_store_codex()
    except PermissionError:
        print("\n[INFO] 检测到 Microsoft Store 版 Codex，但无权限读取 WindowsApps 目录。")
        print("       请以管理员身份运行本脚本。")
        sys.exit(1)

    if not store:
        print("[ERROR] 未找到可读取的 Microsoft Store Codex。")
        sys.exit(1)

    root = _windows_preferred_standalone_root()
    if not root:
        print("[ERROR] 未找到 LOCALAPPDATA，无法创建 Codex-boji。")
        sys.exit(1)

    print("=" * 60)
    print(f"  Sync Microsoft Store Codex -> {WINDOWS_STANDALONE_DIR_NAME}")
    print("=" * 60)
    print(f"[INFO] Store: {store['package_root']}")
    print(f"[INFO] 目标:  {root}")

    killed = _kill_windows_processes_under(root)
    if killed:
        print(f"  已关闭 {WINDOWS_STANDALONE_DIR_NAME} 进程: {killed}")

    backup = None
    if os.path.isdir(root):
        backup = root + ".bak-" + time.strftime("%Y%m%d-%H%M%S")
        try:
            os.rename(root, backup)
            print(f"  已备份旧版本: {backup}")
        except OSError as e:
            print(f"  [ERROR] 备份旧版本失败: {e}")
            print("          请确认 Codex-boji 已退出，然后重新运行。")
            sys.exit(1)

    try:
        print("  正在复制 Store 版文件...")
        _copy_tree_robust(store["copy_root"], root)
        _write_boji_manifest(root, store)
        _check_windows_boji_update(store, root)
        print("  [OK] 同步完成。")
    except Exception as e:
        print(f"  [ERROR] 同步失败: {e}")
        if backup and os.path.isdir(backup) and not os.path.isdir(root):
            try:
                os.rename(backup, root)
                print("  已恢复旧版本。")
            except OSError as restore_error:
                print(f"  [WARN] 恢复旧版本失败: {restore_error}")
        sys.exit(1)

    print(f"\n请继续运行: python patch.py")


def print_usage():
    print("Usage:")
    print("  python patch.py                 Install or update patched Codex")
    print("  python patch.py --rollback      Roll back patch files only")
    print(f"  python patch.py --uninstall     Remove Windows {WINDOWS_STANDALONE_DIR_NAME} and shortcuts")
    print(f"  python patch.py --sync-store    Sync current Store Codex into {WINDOWS_STANDALONE_DIR_NAME}")
    print("  python patch.py --load-sessions Rebuild local session index only")
    print("  python patch.py --path <dir>    Target a non-standard Codex install")
    print("")
    print("Environment:")
    print("  CODEX_PATH=<dir>                Target Codex app/resources directory")
    print("  CODEX_HOME=<dir>                Target Codex config directory (default: ~/.codex)")


def kill_codex():
    """关闭正在运行的 Codex 进程，避免文件被占用导致补丁失败（跨平台）。"""
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/f", "/im", "Codex.exe"],
                           capture_output=True, text=True)
        elif sys.platform == "darwin":
            subprocess.run(["pkill", "-x", "Codex"], capture_output=True, text=True)
        else:
            subprocess.run(["pkill", "-f", "codex"], capture_output=True, text=True)
    except Exception:
        pass


def _wait_exe_unlocked(exe_path, timeout=8.0):
    """等待可执行文件不再被占用（进程退出后句柄释放需要时间）。

    Windows 上以独占方式尝试打开文件来判断是否已解锁；其它平台仅短暂等待。
    避免 @electron/fuses 因 EBUSY 写入失败。"""
    if not exe_path or not os.path.isfile(exe_path):
        time.sleep(0.5)
        return
    if sys.platform != "win32":
        time.sleep(0.8)
        return
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            # 以读写方式独占打开；若被占用会抛 PermissionError/OSError
            fd = os.open(exe_path, os.O_RDWR)
            os.close(fd)
            return
        except OSError:
            time.sleep(0.5)
    # 超时也继续，让后续重试逻辑兜底


def main():
    global BASE, CODEX_RESOURCES

    print("=" * 60)
    print("  Codex API Key 全功能解锁 v2.0")
    print("=" * 60)

    # 0. 前置依赖检查（缺 Node.js 直接退出，给出对应系统的安装命令）
    if not check_prerequisites():
        sys.exit(1)

    detect_platform()
    kill_codex()
    load_config()

    # 检查 asar 状态，并从原始包准备完整 app/ 目录
    if not prepare_app_dir():
        sys.exit(1)
    asar1_path = os.path.join(CODEX_RESOURCES, "app.asar1")
    app_dir = os.path.join(CODEX_RESOURCES, "app")
    if os.path.exists(asar1_path):
        print("  app.asar1 已存在，作为原始备份保留")

    # 设置全局路径
    BASE = os.path.join(app_dir, "webview", "assets")
    if not os.path.isdir(BASE):
        print(f"[ERROR] webview/assets 不存在: {BASE}")
        sys.exit(1)

    # 备份原始 asar 及其 unpacked sidecar（仅首次）
    _backup_original_asar_files()

    # 执行补丁
    patch_module_0_session_persist()
    patch_module_1_fast_mode()
    patch_module_2_plugins_i18n()
    patch_module_3_plugin_connector()
    patch_module_4_brand()
    patch_module_5_voice()
    patch_module_6_usage()
    patch_module_7_frontend_models()
    cleanup_legacy_status_injection()

    # 模型注入
    inject_models()

    # 配置补全
    patch_config()

    # 本地会话索引修复，避免切换 API/账号后历史会话列表缺项
    rebuild_local_session_index()

    # 补丁后语法校验（关键安全网：防止改坏 JS 导致 Codex 卡 logo）
    syntax_ok = validate_patched_syntax()

    # 重新打包 app.asar，避免新版 Electron shell 因 fuse 不可写而进入默认欢迎页
    packed_ok = repack_patched_asar()
    audit_ok = audit_packed_app()
    if not packed_ok or not audit_ok:
        print("\n[ERROR] 打包后的 Codex 启动结构检查未通过，已停止。")
        print("        不建议启动 Codex-boji；请把上方 [FAIL] 信息反馈以便修复。")
        sys.exit(1)

    # 禁用 Electron 熔断器作为兜底 + macOS 重新签名（内置，跨平台）
    apply_fuses_and_sign()

    # 报告
    print_report()

    if results["failed"] and not results["applied"] and not results["skipped"]:
        print("\n[ERROR] 所有补丁均失败！可能是全新版本，请提交 Issue。")
        sys.exit(1)

    if not syntax_ok:
        print("\n  [注意] 部分补丁因语法问题已自动回退，对应功能未生效，")
        print("         但 Codex 可正常启动。请把上方 [FAIL] 信息反馈以便修复。")

    # 创建桌面快捷方式（Windows），方便用户启动补丁版 Codex
    create_desktop_shortcut()
    if sys.platform == "win32":
        _write_active_build_root(os.path.dirname(CODEX_APP) if CODEX_APP else os.path.dirname(CODEX_RESOURCES))

    if sys.platform == "win32":
        status = _check_windows_boji_update()
        if status and status.get("update_available"):
            print(f"\n  [UPDATE] Microsoft Store Codex 已更新: {status.get('store_version')} > {status.get('boji_version')}")
            print(f"           建议同步更新 {WINDOWS_STANDALONE_DIR_NAME} 后重新打补丁。")

    print(f"\n  Codex 全功能解锁完成。启动 Codex 使用 API key 模式登录即可。")
    print(f"  如需回滚，运行: python3 patch.py --rollback\n")


def rollback():
    """回滚补丁"""
    detect_platform()
    kill_codex()
    asar1_path = os.path.join(CODEX_RESOURCES, "app.asar1")
    asar_path = os.path.join(CODEX_RESOURCES, "app.asar")
    app_dir = os.path.join(CODEX_RESOURCES, "app")
    asar_bak = os.path.join(CODEX_RESOURCES, "app.asar.bak")

    print("回滚补丁...")
    if os.path.isdir(app_dir):
        shutil.rmtree(app_dir)
        print("  已删除 app/ 目录")
    if os.path.exists(asar1_path):
        if os.path.exists(asar_path):
            os.remove(asar_path)
            print("  已删除补丁版 app.asar")
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

    # 恢复 Electron fuse（将被关掉的安全开关重新打开，让 Codex 回到出厂状态）
    print("\n  恢复 Electron 安全熔断器...")

    if not CODEX_APP:
        print("  [WARN] 未找到 Codex 可执行文件，跳过 fuse 恢复。")
        print("         请手动执行: npx -y @electron/fuses write --app <Codex路径> OnlyLoadAppFromAsar=on")
    elif not resolve_executable("npx"):
        print("  [WARN] 未找到 npx，跳过 fuse 恢复。请安装 Node.js 后手动执行。")
    else:
        # 确保 Codex 已退出、文件句柄已释放，避免 EBUSY
        kill_codex()
        _wait_exe_unlocked(CODEX_APP)
        fuses_to_restore = [
            "OnlyLoadAppFromAsar=on",
            "EnableEmbeddedAsarIntegrityValidation=on",
            "GrantFileProtocolExtraPrivileges=on",
            "EnableCookieEncryption=on",
        ]
        fuse_ok = True
        for fuse in fuses_to_restore:
            ok, err = _write_fuse(fuse)
            if ok:
                print(f"  [OK]   {fuse}")
            else:
                fuse_ok = False
                print(f"  [WARN] fuse {fuse} 恢复失败（可能需要管理员权限）")
                if err:
                    print(f"         {err.splitlines()[-1] if err.splitlines() else err}")
        if not fuse_ok:
            print("  [HINT] 请以管理员/sudo 身份重新运行: python patch.py --rollback")

    # macOS 回滚后需重新签名
    if PLATFORM == "macos" and CODEX_APP and resolve_executable("codesign"):
        try:
            r = run_command(
                ["codesign", "--force", "--deep", "--sign", "-", CODEX_APP],
                capture_output=True, text=True, timeout=180
            )
            if r.returncode == 0:
                print("  [OK]   已重新签名")
            else:
                print(f"  [WARN] 重新签名失败: {r.stderr.strip()}")
        except Exception as e:
            print(f"  [WARN] codesign 执行异常: {e}")

    print("回滚完成。")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--rollback":
        rollback()
    elif len(sys.argv) > 1 and sys.argv[1] == "--uninstall":
        uninstall_standalone()
    elif len(sys.argv) > 1 and sys.argv[1] == "--sync-store":
        sync_store_to_boji()
    elif len(sys.argv) > 1 and sys.argv[1] == "--load-sessions":
        rebuild_local_session_index()
    elif len(sys.argv) > 1 and sys.argv[1] in ("--help", "-h", "/?"):
        print_usage()
    else:
        main()
