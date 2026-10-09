"""Exercise native PowerShell/cmd launchers without installing into a user profile."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == "win32", "native Windows launchers")
class WindowsLauncherTests(unittest.TestCase):
    def test_argument_forwarding_in_unicode_and_space_paths(self):
        with tempfile.TemporaryDirectory(prefix="nerfed-launch-") as temp:
            checkout = Path(temp) / "中文 checkout with spaces"
            (checkout / "tools").mkdir(parents=True)
            (checkout / "bin").mkdir()
            scripts = checkout / "plugin/skills/is-gpt-nerfed/scripts"
            scripts.mkdir(parents=True)
            for name in ("nerfed.ps1", "nerfed.cmd"):
                shutil.copy2(ROOT / "bin" / name, checkout / "bin" / name)
            shutil.copy2(ROOT / "tools/windows-runtime.ps1", checkout / "tools/windows-runtime.ps1")
            (scripts / "nerfed").write_text(
                "import json,sys\nprint(json.dumps(sys.argv[1:],ensure_ascii=False))\n", encoding="utf-8"
            )
            env = {**os.environ, "NERFED_PYTHON": sys.executable, "PYTHONUTF8": "1"}
            expected = ["config", "set", "codex_bin", "C:\\中文 path\\codex.exe", "--flag"]
            ps = subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                 str(checkout / "bin/nerfed.ps1"), *expected],
                env=env, capture_output=True, encoding="utf-8", timeout=30,
            )
            self.assertEqual(ps.returncode, 0, ps.stderr)
            self.assertEqual(json.loads(ps.stdout.strip()), expected)
            # cmd /s /c strips its outer quotes; preserve a second pair around the script path.
            command_line = subprocess.list2cmdline([os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c"])
            command_line += ' "' + subprocess.list2cmdline([str(checkout / "bin/nerfed.cmd"), *expected]) + '"'
            cmd = subprocess.run(
                command_line,
                env=env, capture_output=True, encoding="utf-8", timeout=30,
            )
            self.assertEqual(cmd.returncode, 0, cmd.stderr)
            self.assertEqual(json.loads(cmd.stdout.strip()), expected)

    def test_powershell_entrypoints_parse(self):
        files = [ROOT / name for name in ("install.ps1", "uninstall.ps1", "launch.ps1",
                                          "windows/native.ps1", "bin/nerfed.ps1", "tools/windows-runtime.ps1", "tools/build-windows.ps1")]
        literal = ",".join("'" + str(p).replace("'", "''") + "'" for p in files)
        code = (
            "$bad=0; foreach($p in @(" + literal + ")) {"
            "$tokens=$null; $errors=$null; "
            "[System.Management.Automation.Language.Parser]::ParseFile($p,[ref]$tokens,[ref]$errors)|Out-Null; "
            "if($errors.Count) {$errors|Out-String|Write-Output; $bad++}}; exit $bad"
        )
        proc = subprocess.run(["powershell.exe", "-NoProfile", "-Command", code],
                              capture_output=True, encoding="utf-8", timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_default_native_and_explicit_legacy_smoke(self):
        with tempfile.TemporaryDirectory(prefix="nerfed-launch-ui-") as temp:
            user_state = Path(temp) / "untouched caller homes"
            env = {**os.environ, "NERFED_PYTHON": sys.executable,
                   "CODEX_HOME": str(user_state / "codex"), "NERFED_HOME": str(user_state / "ledger")}
            for options, expected in ((["--smoke-test"], "Native WPF smoke passed"),
                                      (["--legacy-tk", "--smoke-test"], "")):
                command = subprocess.list2cmdline([os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c"])
                command += ' "' + subprocess.list2cmdline([str(ROOT / "launch.cmd"), *options]) + '"'
                result = subprocess.run(command, env=env, capture_output=True, encoding="utf-8",
                                        errors="replace", timeout=45)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                if expected:
                    self.assertIn(expected, result.stdout)
                self.assertFalse(user_state.exists())


if __name__ == "__main__":
    unittest.main()
