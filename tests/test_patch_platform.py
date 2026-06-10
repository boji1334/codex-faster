import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from contextlib import redirect_stdout
from io import StringIO

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import patch


class PatchPlatformTests(unittest.TestCase):
    def tearDown(self):
        patch.PLATFORM = None
        patch.CODEX_RESOURCES = None
        patch.CODEX_APP = None
        patch.BASE = None
        patch.results = {"applied": [], "skipped": [], "failed": []}
        patch.patched_files = set()

    def test_windows_store_path_is_not_patch_target(self):
        store_path = r"C:\Program Files\WindowsApps\OpenAI.Codex_26.1.0.0_x64__abc\app\resources"
        normal_path = r"C:\Users\Alice\AppData\Local\Codex-boji\resources"

        with mock.patch.object(patch.sys, "platform", "win32"):
            self.assertTrue(patch._is_windows_store_path(store_path))
            self.assertFalse(patch._is_windows_store_path(normal_path))

    def test_windows_detect_prefers_boji_over_store_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            boji = root / "Codex-boji"
            resources = boji / "resources"
            resources.mkdir(parents=True)
            (resources / "app.asar").write_text("", encoding="utf-8")

            with mock.patch.object(patch.sys, "platform", "win32"), \
                 mock.patch.dict(os.environ, {"LOCALAPPDATA": str(root)}, clear=False), \
                 mock.patch.object(patch, "WINDOWS_ACTIVE_BUILD_STATUS", str(root / "missing-active.json")), \
                 mock.patch.object(patch, "CODEX_RESOURCES", None), \
                 mock.patch.object(patch, "CODEX_APP", None), \
                 mock.patch.object(patch, "BASE", None), \
                 mock.patch.object(patch, "_convert_store_to_standalone") as convert, \
                 mock.patch.object(patch, "_find_codex_executable", return_value=str(boji / "Codex.exe")):
                with redirect_stdout(StringIO()):
                    patch.detect_platform()
                detected = patch.CODEX_RESOURCES

            convert.assert_not_called()
            self.assertEqual(os.path.normcase(os.path.abspath(detected)), os.path.normcase(str(resources)))

    def test_windows_detect_prefers_active_build_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            boji = root / "Codex-boji"
            boji_resources = boji / "resources"
            boji_resources.mkdir(parents=True)
            (boji_resources / "app.asar").write_text("", encoding="utf-8")

            repair = root / "Codex-boji.repair"
            repair_resources = repair / "resources"
            repair_resources.mkdir(parents=True)
            (repair_resources / "app.asar").write_text("", encoding="utf-8")

            status = root / "active.json"
            status.write_text(f'{{"active_root": "{str(repair).replace(chr(92), chr(92) + chr(92))}"}}', encoding="utf-8")

            with mock.patch.object(patch.sys, "platform", "win32"), \
                 mock.patch.dict(os.environ, {"LOCALAPPDATA": str(root)}, clear=False), \
                 mock.patch.object(patch, "WINDOWS_ACTIVE_BUILD_STATUS", str(status)), \
                 mock.patch.object(patch, "CODEX_RESOURCES", None), \
                 mock.patch.object(patch, "CODEX_APP", None), \
                 mock.patch.object(patch, "BASE", None), \
                 mock.patch.object(patch, "_convert_store_to_standalone") as convert, \
                 mock.patch.object(patch, "_find_codex_executable", return_value=str(repair / "Codex.exe")):
                with redirect_stdout(StringIO()):
                    patch.detect_platform()
                detected = patch.CODEX_RESOURCES

            convert.assert_not_called()
            self.assertEqual(os.path.normcase(os.path.abspath(detected)), os.path.normcase(str(repair_resources)))

    def test_windows_detect_converts_store_when_no_standalone_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resources = root / "Codex-boji" / "resources"

            with mock.patch.object(patch.sys, "platform", "win32"), \
                 mock.patch.dict(os.environ, {"LOCALAPPDATA": str(root), "PROGRAMFILES": str(root)}, clear=False), \
                 mock.patch.object(patch, "WINDOWS_ACTIVE_BUILD_STATUS", str(root / "missing-active.json")), \
                 mock.patch.object(patch, "CODEX_RESOURCES", None), \
                 mock.patch.object(patch, "CODEX_APP", None), \
                 mock.patch.object(patch, "BASE", None), \
                 mock.patch.object(patch, "_convert_store_to_standalone", return_value=str(resources)) as convert, \
                 mock.patch.object(patch, "_find_codex_executable", return_value=str(resources.parent / "Codex.exe")):
                with redirect_stdout(StringIO()):
                    patch.detect_platform()
                detected = patch.CODEX_RESOURCES

            convert.assert_called_once()
            self.assertEqual(os.path.normcase(os.path.abspath(detected)), os.path.normcase(str(resources)))

    def test_windows_npx_command_uses_node_cli_when_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            npm_bin = root / "nodejs" / "node_modules" / "npm" / "bin"
            npm_bin.mkdir(parents=True)
            cli = npm_bin / "npx-cli.js"
            cli.write_text("", encoding="utf-8")
            npx = root / "nodejs" / "npx.cmd"
            npx.write_text("", encoding="utf-8")
            node = root / "nodejs" / "node.exe"
            node.write_text("", encoding="utf-8")

            def fake_resolve(name):
                return {"npx": str(npx), "node": str(node)}.get(name)

            with mock.patch.object(patch.sys, "platform", "win32"), \
                 mock.patch.object(patch, "resolve_executable", side_effect=fake_resolve):
                cmd = patch._windows_npx_command(["-y", "@electron/asar", "l", r"C:\Program Files\App\app.asar"])

            self.assertEqual(cmd[0], str(node))
            self.assertEqual(cmd[1], str(cli))
            self.assertEqual(cmd[-1], r"C:\Program Files\App\app.asar")

    def test_i18n_marker_is_treated_as_already_applied(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app_main = root / "app-main-test.js"
            app_main.write_text("s=/*__codex_boji_i18n__*/!0", encoding="utf-8")

            patch.BASE = str(root)
            with redirect_stdout(StringIO()):
                patch.patch_module_2_plugins_i18n()

            self.assertFalse(patch.results["failed"])
            self.assertIn("app-main-test.js: i18n 多语言强制启用", patch.results["skipped"])

    def test_i18n_default_enabled_file_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = root / "general-settings-test.js"
            settings.write_text("ne(`72216192`)?.get(`enable_i18n`,!0)", encoding="utf-8")

            patch.BASE = str(root)
            with redirect_stdout(StringIO()):
                patch.patch_module_2_plugins_i18n()

            self.assertFalse(patch.results["failed"])
            self.assertIn("general-settings-test.js: i18n 多语言强制启用", patch.results["skipped"])

    def test_remove_js_once_removes_existing_snippet(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "bundle.js"
            target.write_text(
                "console.log('before');\n"
                "/* __codex_boji_context_hud__ */\n"
                "(()=>{window.oldHud=true})();\n"
                "\n//# sourceMappingURL=bundle.js.map",
                encoding="utf-8",
            )

            with redirect_stdout(StringIO()):
                ok = patch.remove_js_once(
                    str(target),
                    "旧版状态栏 UI",
                    "__codex_boji_context_hud__",
                )

            content = target.read_text(encoding="utf-8")
            self.assertTrue(ok)
            self.assertNotIn("__codex_boji_context_hud__", content)
            self.assertNotIn("window.oldHud=true", content)
            self.assertIn("console.log('before');", content)
            self.assertTrue(content.rstrip().endswith("//# sourceMappingURL=bundle.js.map"))

    def test_cleanup_legacy_status_injection_removes_old_markers(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            build = app / ".vite" / "build"
            assets = app / "webview" / "assets"
            build.mkdir(parents=True)
            assets.mkdir(parents=True)
            main = build / "main-test.js"
            preload = build / "preload.js"
            thread = assets / "local-conversation-thread-test.js"
            main.write_text(
                "console.log('main');\n/* __codex_boji_usage_summary_ipc__ */\n(()=>{})();\n",
                encoding="utf-8",
            )
            preload.write_text(
                "console.log('preload');\n/* __codex_boji_usage_summary_preload__ */\n(()=>{})();\n",
                encoding="utf-8",
            )
            thread.write_text(
                "console.log('thread');\n/* __codex_boji_context_hud__ */\n(()=>{})();\n",
                encoding="utf-8",
            )

            patch.CODEX_RESOURCES = str(app.parent)
            patch.BASE = str(assets)
            with redirect_stdout(StringIO()):
                patch.cleanup_legacy_status_injection()

            self.assertNotIn("__codex_boji_usage_summary_ipc__", main.read_text(encoding="utf-8"))
            self.assertNotIn("__codex_boji_usage_summary_preload__", preload.read_text(encoding="utf-8"))
            self.assertNotIn("__codex_boji_context_hud__", thread.read_text(encoding="utf-8"))
            self.assertIn(str(main), patch.patched_files)
            self.assertIn(str(preload), patch.patched_files)
            self.assertIn(str(thread), patch.patched_files)

    def test_app_dir_complete_requires_main_entry_and_hashed_webview(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            (app / ".vite" / "build").mkdir(parents=True)
            (app / "webview" / "assets").mkdir(parents=True)
            (app / "package.json").write_text('{"main":".vite/build/bootstrap.js"}', encoding="utf-8")

            self.assertFalse(patch._app_dir_is_complete(str(app)))

            (app / ".vite" / "build" / "bootstrap.js").write_text("", encoding="utf-8")
            self.assertFalse(patch._app_dir_is_complete(str(app)))

            (app / "webview" / "assets" / "app-main-abc123.js").write_text("", encoding="utf-8")
            self.assertTrue(patch._app_dir_is_complete(str(app)))

    def test_audit_packed_app_requires_bootstrap_and_unpacked_natives(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "app"
            (app / ".vite" / "build").mkdir(parents=True)
            (app / "webview" / "assets").mkdir(parents=True)
            (app / "package.json").write_text('{"main":".vite/build/bootstrap.js"}', encoding="utf-8")
            (root / "app.asar").write_text("", encoding="utf-8")
            unpacked = root / "app.asar.unpacked" / "node_modules"
            (unpacked / "better-sqlite3" / "build" / "Release").mkdir(parents=True)
            (unpacked / "node-pty" / "build" / "Release").mkdir(parents=True)
            (unpacked / "@worklouder" / "device-kit-oai" / "node_modules" / "@worklouder" / "wl-device-kit" / "node_modules" / "node-hid" / "build" / "Release").mkdir(parents=True)
            (unpacked / "better-sqlite3" / "build" / "Release" / "better_sqlite3.node").write_text("", encoding="utf-8")
            (unpacked / "node-pty" / "build" / "Release" / "pty.node").write_text("", encoding="utf-8")
            (unpacked / "node-pty" / "build" / "Release" / "winpty.dll").write_text("", encoding="utf-8")
            (unpacked / "node-pty" / "build" / "Release" / "winpty-agent.exe").write_text("", encoding="utf-8")
            (unpacked / "@worklouder" / "device-kit-oai" / "node_modules" / "@worklouder" / "wl-device-kit" / "node_modules" / "node-hid" / "build" / "Release" / "HID.node").write_text("", encoding="utf-8")

            good_listing = "\n".join([
                "\\package.json",
                "\\.vite\\build\\bootstrap.js",
                "\\webview\\assets",
                "\\webview\\assets\\app-main-abc123.js",
                "\\node_modules\\better-sqlite3\\lib\\database.js",
                "\\node_modules\\node-pty\\lib\\index.js",
            ])
            bad_listing = good_listing.replace("\\.vite\\build\\bootstrap.js\n", "")

            def fake_run_command(args, **kwargs):
                return mock.Mock(returncode=0, stdout=good_listing, stderr="")

            patch.CODEX_RESOURCES = str(root)
            with mock.patch.object(patch, "resolve_executable", return_value="npx"), \
                 mock.patch.object(patch, "run_command", side_effect=fake_run_command), \
                 redirect_stdout(StringIO()):
                self.assertTrue(patch.audit_packed_app())

            with mock.patch.object(patch, "resolve_executable", return_value="npx"), \
                 mock.patch.object(patch, "run_command", return_value=mock.Mock(returncode=0, stdout=bad_listing, stderr="")), \
                 redirect_stdout(StringIO()):
                self.assertFalse(patch.audit_packed_app())

            (unpacked / "node-pty" / "build" / "Release" / "pty.node").unlink()
            with mock.patch.object(patch, "resolve_executable", return_value="npx"), \
                 mock.patch.object(patch, "run_command", side_effect=fake_run_command), \
                 redirect_stdout(StringIO()):
                self.assertFalse(patch.audit_packed_app())

if __name__ == "__main__":
    unittest.main()
