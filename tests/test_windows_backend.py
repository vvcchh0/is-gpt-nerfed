"""Cross-process and Windows-specific backend regressions; no user Codex profile is touched."""
import argparse
import base64
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest import mock

import test_dgc

dgc = test_dgc.dgc
import platform_support

SCRIPTS = os.path.dirname(test_dgc.DGC_PATH)


class BackendPortabilityTests(unittest.TestCase):
    def test_purge_does_not_recreate_the_ledger(self):
        with tempfile.TemporaryDirectory(prefix="nerfed purge ") as temp:
            state_home = Path(temp) / "ledger"
            codex_home = Path(temp) / "Codex home"
            codex_home.mkdir()
            state = {
                "NERFED_HOME": str(state_home), "CODEX_HOME": str(codex_home),
                "CONFIG_PATH": str(state_home / "config.json"), "EVENTS_PATH": str(state_home / "events.jsonl"),
                "PROBES_INDEX": str(state_home / "probes.jsonl"), "SESSIONS_DIR": str(state_home / "sessions"),
                "PROBES_DIR": str(state_home / "probes"), "ERRORS_PATH": str(state_home / "errors.log"),
                "WORKER_LOG": str(state_home / "worker.log"), "LOG_PATH": str(state_home / "log.jsonl"),
                "ACCOUNT_PATH": str(state_home / "account.json"), "HOOKS_STATUS_PATH": str(state_home / "hooks_status.json"),
                "CODEX_VERSIONS_PATH": str(state_home / "codex_versions.json"), "UPDATE_PATH": str(state_home / "update.json"),
                "STATE_PATH": str(state_home / "state.json"),
            }
            with mock.patch.multiple(dgc, **state), mock.patch.object(dgc, "codex_bin", return_value=None):
                state_home.mkdir()
                output = StringIO()
                with redirect_stdout(output):
                    result = dgc.cmd_teardown(argparse.Namespace(purge=True))
            self.assertEqual(result, 0)
            self.assertFalse(state_home.exists(), "teardown must not recreate the log after purging")

    def test_sqlite_readonly_uri_escapes_unicode_hash_and_spaces(self):
        with tempfile.TemporaryDirectory(prefix="nerfed db ") as temp:
            codex_home = Path(temp) / "会话 # snapshot"
            codex_home.mkdir()
            db = codex_home / "state_123.sqlite"
            con = sqlite3.connect(db)
            with con:
                con.execute("CREATE TABLE sample(value TEXT)")
                con.execute("INSERT INTO sample VALUES (?)", ("模型",))
            con.close()
            with mock.patch.object(dgc, "CODEX_HOME", str(codex_home)):
                self.assertEqual(dgc.db_query("SELECT value FROM sample"), [{"value": "模型"}])

    @unittest.skipUnless(sys.platform == "win32", "Windows process handles are required")
    def test_pid_alive_uses_non_destructive_process_query(self):
        with mock.patch.object(platform_support.os, "kill", side_effect=AssertionError("os.kill must not be used on Windows")):
            self.assertTrue(platform_support.pid_alive(os.getpid()))
            self.assertFalse(platform_support.pid_alive(0x7FFFFFFF))

    @unittest.skipUnless(sys.platform == "win32", "Windows LockFileEx regression")
    def test_cross_process_lock_stays_held_beyond_ten_seconds(self):
        with tempfile.TemporaryDirectory(prefix="nerfed lock ") as temp:
            lock_path = os.path.join(temp, "锁 file.lock")
            started = os.path.join(temp, "started")
            acquired = os.path.join(temp, "acquired")
            code = (
                "import json,sys; sys.path.insert(0," + repr(SCRIPTS) + "); "
                "import platform_support; path=" + repr(lock_path) + "; started=" + repr(started) + "; acquired=" + repr(acquired) + "; "
                "open(started,'w').close(); f=open(path,'a+',encoding='utf-8'); "
                "ctx=platform_support.exclusive_file_lock(f); ctx.__enter__(); open(acquired,'w').close(); "
                "ctx.__exit__(None,None,None); f.close()"
            )
            with open(lock_path, "a+", encoding="utf-8") as held:
                lock = platform_support.exclusive_file_lock(held)
                lock.__enter__()
                child = subprocess.Popen([sys.executable, "-X", "utf8", "-c", code],
                                         **platform_support.subprocess_options(hidden=True),
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline and not os.path.exists(started):
                        time.sleep(0.05)
                    self.assertTrue(os.path.exists(started), "lock worker did not start")
                    deadline = time.monotonic() + 10.25
                    while time.monotonic() < deadline and child.poll() is None:
                        time.sleep(0.1)
                    self.assertIsNone(child.poll(), "the other process acquired a still-held lock")
                    self.assertFalse(os.path.exists(acquired), "lock expired after a bounded retry window")
                finally:
                    lock.__exit__(None, None, None)
                stdout, stderr = child.communicate(timeout=10)
                self.assertEqual(child.returncode, 0, (stdout + stderr).decode("utf-8", "replace"))
                self.assertTrue(os.path.exists(acquired), "waiting process did not acquire after release")

    @unittest.skipUnless(sys.platform == "win32", "Windows command interpreter is required")
    def test_npm_cmd_and_python_fake_launch_with_unicode_paths(self):
        with tempfile.TemporaryDirectory(prefix="nerfed CLI ") as temp:
            folder = Path(temp) / "中文 CLI folder with spaces"
            folder.mkdir()
            helper = folder / "fake cli.py"
            helper.write_text("import json,sys\nprint(json.dumps(sys.argv[1:],ensure_ascii=False))\n", encoding="utf-8")
            shim = folder / "codex.cmd"
            shim.write_text(f'@echo off\r\nchcp 65001 >nul\r\n"{sys.executable}" -X utf8 "%~dp0fake cli.py" %*\r\n', encoding="utf-8")
            arguments = ["--version", "路径 with spaces", "雪"]
            launched = subprocess.run(platform_support.command_argv(str(shim), arguments), capture_output=True,
                                      text=True, encoding="utf-8", timeout=20,
                                      **platform_support.subprocess_options(hidden=True))
            self.assertEqual(launched.returncode, 0, launched.stderr)
            self.assertEqual(json.loads(launched.stdout), arguments)

            fake_dir = folder / "fake app-server"
            (fake_dir / "fixtures").mkdir(parents=True)
            shutil.copy2(Path(test_dgc.FAKE_CODEX), fake_dir / "fake codex.py")
            shutil.copytree(Path(test_dgc.ROOT) / "tests/fixtures", fake_dir / "fixtures", dirs_exist_ok=True)
            fake_python = fake_dir / "fake codex.py"
            app = dgc.cas.AppServer(str(fake_python))
            try:
                self.assertEqual(app.initialize()["userAgent"], "fake-codex/0.0")
            finally:
                app.close()

    @unittest.skipUnless(sys.platform == "win32", "Windows Codex install layout")
    def test_path_codex_candidates_and_latest_localappdata_binary(self):
        with tempfile.TemporaryDirectory(prefix="nerfed PATH ") as temp:
            path_dir = Path(temp) / "CLI path with spaces"
            path_dir.mkdir()
            exe = path_dir / "codex.exe"
            cmd = path_dir / "codex.cmd"
            exe.touch()
            cmd.touch()
            with mock.patch.dict(os.environ, {"PATH": str(path_dir)}), \
                    mock.patch.object(dgc.platform, "app_codex_bins", return_value=[]):
                self.assertEqual(dgc.codex_candidates(), [str(exe), str(cmd)])

            local = Path(temp) / "Local App Data"
            paths = [local / "OpenAI/Codex/bin/0.160.0/codex.exe", local / "OpenAI/Codex/bin/0.162.0/codex.exe"]
            for candidate in paths:
                candidate.parent.mkdir(parents=True, exist_ok=True)
                candidate.touch()
            with mock.patch.dict(os.environ, {"LOCALAPPDATA": str(local), "PATH": ""}), \
                    mock.patch.object(dgc, "codex_version", side_effect=lambda p: "0.160.0" if "0.160.0" in p else "0.162.0"):
                self.assertEqual(dgc.codex_candidates(), [str(p) for p in paths])
                self.assertEqual(dgc.codex_bin({"codex_bin": None}), str(paths[-1]))
                self.assertEqual(dgc.default_originator(str(paths[-1])), "Codex Desktop")

    @unittest.skipUnless(sys.platform == "win32", "Windows setup workflow")
    def test_setup_builds_windows_hooks_and_trusts_them_without_touching_source(self):
        with tempfile.TemporaryDirectory(prefix="nerfed setup 中文 # ") as temp:
            base = Path(temp)
            state_home = base / "ledger with spaces # tag"
            codex_home = base / "Codex state 中文"
            codex_home.mkdir()
            trust_file = base / "trusted hooks.json"
            manifest_source = Path(dgc.PLUGIN_ROOT) / ".codex-plugin/plugin.json"
            original_manifest = manifest_source.read_bytes()
            state = {
                "NERFED_HOME": str(state_home), "CODEX_HOME": str(codex_home),
                "CONFIG_PATH": str(state_home / "config.json"), "EVENTS_PATH": str(state_home / "events.jsonl"),
                "PROBES_INDEX": str(state_home / "probes.jsonl"), "SESSIONS_DIR": str(state_home / "sessions"),
                "PROBES_DIR": str(state_home / "probes"), "ERRORS_PATH": str(state_home / "errors.log"),
                "WORKER_LOG": str(state_home / "worker.log"), "LOG_PATH": str(state_home / "log.jsonl"),
                "ACCOUNT_PATH": str(state_home / "account.json"), "HOOKS_STATUS_PATH": str(state_home / "hooks_status.json"),
                "CODEX_VERSIONS_PATH": str(state_home / "codex_versions.json"), "UPDATE_PATH": str(state_home / "update.json"),
                "STATE_PATH": str(state_home / "state.json"),
            }
            with mock.patch.multiple(dgc, **state), \
                    mock.patch.object(dgc, "codex_bin", return_value=test_dgc.FAKE_CODEX), \
                    mock.patch.object(dgc, "cmd_doctor", return_value=0), \
                    mock.patch.dict(os.environ, {"FAKE_CODEX_TRUST_FILE": str(trust_file)}):
                output = StringIO()
                with redirect_stdout(output):
                    result = dgc.cmd_setup(argparse.Namespace(no_cli=False, no_trust=False, trust_hooks=True))
                self.assertEqual(result, 0)
                marketplace = state_home / "windows-marketplace"
                generated_plugin = marketplace / "plugin"
                generated_manifest_path = generated_plugin / ".codex-plugin/plugin.json"
                generated_manifest = json.loads(generated_manifest_path.read_text(encoding="utf-8"))
                hooks = generated_manifest["hooks"]
                self.assertEqual(manifest_source.read_bytes(), original_manifest, "Mac source manifest must stay intact")
                self.assertTrue((state_home / "plugin/skills/is-gpt-nerfed/scripts/nerfed").is_file())
                self.assertFalse((state_home / "plugin").is_symlink(), "Windows fallback is a stable copy")
                commands = [hook["command"] for groups in hooks["hooks"].values() for group in groups
                            for hook in group["hooks"] if hook.get("type") == "command"]
                self.assertEqual(len(commands), len(dgc.WINDOWS_HOOK_EVENTS))
                self.assertTrue(all(command.startswith("powershell.exe -NoProfile -NonInteractive -EncodedCommand ") for command in commands))
                decoded = dgc.decoded_windows_hook_text(hooks)
                self.assertIn("-X utf8", decoded)
                self.assertIn("exit 0", decoded)
                self.assertIn(str(sys.executable), decoded)
                self.assertEqual(len(json.loads(trust_file.read_text(encoding="utf-8"))), len(dgc.WINDOWS_HOOK_EVENTS))
                self.assertIn("trusted.", output.getvalue())

                # A broken Python hook must still return success through the actual encoded PowerShell wrapper.
                bad_plugin = base / "broken plugin"
                bad_script = bad_plugin / "skills/is-gpt-nerfed/scripts/nerfed"
                bad_script.parent.mkdir(parents=True)
                bad_script.write_text("this is not valid python !!!", encoding="utf-8")
                payload = commands[0].split("-EncodedCommand ", 1)[1]
                proc = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", payload],
                                      input="{}", text=True, encoding="utf-8", capture_output=True, timeout=20,
                                      env={**os.environ, "PLUGIN_ROOT": str(bad_plugin), "NERFED_HOME": str(base / "empty state"),
                                           "CODEX_HOME": str(base / "empty codex")})
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

                # If the package cache path has gone stale, the stable copy must become the hook's
                # effective PLUGIN_ROOT so imports and bundled bank data resolve from the same copy.
                fallback_home = base / "fallback state"
                fallback_script = fallback_home / "plugin/skills/is-gpt-nerfed/scripts/nerfed"
                fallback_script.parent.mkdir(parents=True)
                fallback_script.write_text(
                    "import os, pathlib; pathlib.Path(os.environ['HOOK_ENV_OUTPUT']).write_text(os.environ['PLUGIN_ROOT'], encoding='utf-8')\n",
                    encoding="utf-8",
                )
                env_output = base / "plugin-root-seen.txt"
                fallback_payload = dgc.decode_powershell_hook(dgc.powershell_hook_command("SessionStart"))
                self.assertIsNotNone(fallback_payload)
                fallback_encoded = base64.b64encode(fallback_payload.encode("utf-16le")).decode("ascii")
                stale_plugin = base / "stale package cache"
                proc = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", fallback_encoded],
                                      input="{}", text=True, encoding="utf-8", capture_output=True, timeout=20,
                                      env={**os.environ, "PLUGIN_ROOT": str(stale_plugin), "NERFED_HOME": str(fallback_home),
                                           "HOOK_ENV_OUTPUT": str(env_output)})
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                self.assertEqual(env_output.read_text(encoding="utf-8"), str(fallback_home / "plugin"))

    @unittest.skipUnless(sys.platform == "win32", "Windows TOML path escaping")
    def test_setup_fallback_toml_escapes_unicode_hash_and_backslashes(self):
        import tomllib

        with tempfile.TemporaryDirectory(prefix="nerfed TOML 中文 # ") as temp:
            base = Path(temp)
            state_home, codex_home = base / "state # folder", base / "Codex home"
            codex_home.mkdir()
            state = {
                "NERFED_HOME": str(state_home), "CODEX_HOME": str(codex_home),
                "CONFIG_PATH": str(state_home / "config.json"), "EVENTS_PATH": str(state_home / "events.jsonl"),
                "PROBES_INDEX": str(state_home / "probes.jsonl"), "SESSIONS_DIR": str(state_home / "sessions"),
                "PROBES_DIR": str(state_home / "probes"), "ERRORS_PATH": str(state_home / "errors.log"),
                "WORKER_LOG": str(state_home / "worker.log"), "LOG_PATH": str(state_home / "log.jsonl"),
                "ACCOUNT_PATH": str(state_home / "account.json"), "HOOKS_STATUS_PATH": str(state_home / "hooks_status.json"),
                "CODEX_VERSIONS_PATH": str(state_home / "codex_versions.json"), "UPDATE_PATH": str(state_home / "update.json"),
                "STATE_PATH": str(state_home / "state.json"),
            }
            with mock.patch.multiple(dgc, **state), mock.patch.object(dgc, "codex_bin", return_value=None), \
                    mock.patch.object(dgc, "cmd_doctor", return_value=0):
                self.assertEqual(dgc.cmd_setup(argparse.Namespace(no_cli=True, no_trust=False, trust_hooks=False)), 0)
            config = tomllib.loads((codex_home / "config.toml").read_text(encoding="utf-8"))
            expected = str(state_home / "windows-marketplace")
            self.assertEqual(config["marketplaces"]["is-gpt-nerfed"]["source"], expected)
            self.assertEqual(config["plugins"]["is-gpt-nerfed@is-gpt-nerfed"]["enabled"], True)

    @unittest.skipUnless(sys.platform == "win32", "Windows update guard")
    def test_windows_never_checks_or_replaces_a_macos_app(self):
        self.assertFalse(dgc.update_status({"check_updates": True})["enabled"])
        with mock.patch.object(dgc, "fetch_latest_release", side_effect=AssertionError("must not check network")):
            self.assertEqual(dgc.cmd_update_check(argparse.Namespace()), 0)
        with mock.patch.object(dgc, "fetch_latest_release", side_effect=AssertionError("must not fetch an app")):
            result = dgc.cmd_update_install(argparse.Namespace(app="C:/should-not-be-touched/IsGPTNerfed.app", force=True))
        self.assertEqual(result, 1)

    @unittest.skipUnless(sys.platform == "win32", "Windows numeric picker")
    def test_picker_uses_numeric_selection_without_terminal_menu_dependency(self):
        snapshot = {"global_probe": None, "default_model": "gpt-6-astra", "default_effort": "high", "threads": [
            {"title": "会话 A", "model": "gpt-6-astra", "effort": "high", "updated_ago": "now", "last_probe": None, "probe_running": None, "id": "id-a"}
        ]}
        with mock.patch.object(dgc, "build_snapshot", return_value=snapshot), mock.patch("builtins.input", return_value="2"):
            self.assertEqual(dgc.pick_probe_target({}), ("thread", "id-a"))


if __name__ == "__main__":
    unittest.main()
