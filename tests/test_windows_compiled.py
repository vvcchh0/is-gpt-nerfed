"""Compiled WinExe/DLL and bundled-runtime contracts, using only isolated offline modes."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PORTABLE = ROOT / "dist/IsGPTNerfed-Windows-0.5.3-port.3-win-x64.zip"


@unittest.skipUnless(sys.platform == "win32", "compiled inbox Windows WPF")
class WindowsCompiledTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="nerfed-compiled-test-")
        cls.app = Path(cls.temporary.name) / "中文 compiled app with spaces"
        result = subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
             str(ROOT / "tools/compile-windows.ps1"), "-OutputDirectory", str(cls.app)],
            capture_output=True, encoding="utf-8", errors="replace", timeout=45,
        )
        if result.returncode:
            cls.temporary.cleanup()
            raise AssertionError(result.stdout + result.stderr)
        shutil.copytree(ROOT / "plugin", cls.app / "plugin", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copy2(ROOT / "launch.cmd", cls.app / "launch.cmd")

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def run_exe(self, app: Path, *args: str, bundled: bool = False):
        with tempfile.TemporaryDirectory(prefix="nerfed-compiled-home-") as temp:
            untouched = Path(temp) / "caller homes stay untouched"
            env = {**os.environ, "NERFED_PYTHON": sys.executable,
                   "CODEX_HOME": str(untouched / "codex"), "NERFED_HOME": str(untouched / "ledger")}
            if bundled:
                env.pop("NERFED_PYTHON", None)
                env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
            result = subprocess.run([str(app / "IsGPTNerfed.exe"), *args], env=env,
                                    capture_output=True, encoding="utf-8", errors="strict", timeout=45)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse(untouched.exists())
            for line in result.stdout.splitlines():
                if line.startswith("Native isolated state: "):
                    self.assertFalse(Path(line.removeprefix("Native isolated state: ")).exists())
            return result

    def test_winexe_metadata_and_embedded_resources(self):
        exe = (self.app / "IsGPTNerfed.exe").read_bytes()
        pe = struct.unpack_from("<I", exe, 0x3C)[0]
        self.assertEqual(exe[pe:pe + 4], b"PE\0\0")
        self.assertEqual(struct.unpack_from("<H", exe, pe + 4)[0], 0x8664, "x64 machine")
        self.assertEqual(struct.unpack_from("<H", exe, pe + 24 + 68)[0], 2, "Windows GUI subsystem")
        dll = str(self.app / "IsGPTNerfed.Panel.dll").replace("'", "''")
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             "$a=[Reflection.Assembly]::LoadFile('" + dll + "'); "
             "@{version=$a.GetName().Version.ToString();resources=@($a.GetManifestResourceNames())}|ConvertTo-Json"],
            capture_output=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        metadata = json.loads(result.stdout)
        self.assertEqual(metadata["version"], "0.5.3.3")
        self.assertEqual(set(metadata["resources"]), {"Nerfed.Native.xaml", "Nerfed.face-ok.png",
                                                    "Nerfed.face-warn.png", "Nerfed.face-alert.png"})
        self.assertFalse((self.app / "windows").exists())
        self.assertFalse((self.app / "macos").exists())
        self.assertIn("0.5.3-port.3", self.run_exe(self.app, "--version").stdout)

    def test_compiled_offline_actions_need_no_source_compilation(self):
        self.assertIn("Native WPF smoke passed", self.run_exe(self.app, "--smoke-test").stdout)
        result = self.run_exe(self.app, "--self-test")
        self.assertIn("Native transport self-test passed", result.stdout)
        self.assertIn("Native self-test passed", result.stdout)
        output = Path(self.temporary.name) / "中文 rendered detail.png"
        self.run_exe(self.app, "--render", str(output), "--render-detail", "--render-width", "380", "--render-scale", "1.5")
        image = output.read_bytes()
        self.assertEqual(image[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(int.from_bytes(image[16:20], "big"), 570)

    def test_compiled_cmd_waits_and_propagates_exit_without_powershell(self):
        # PATH deliberately cannot resolve powershell.exe; the compiled branch must be direct.
        env = {**os.environ, "NERFED_PYTHON": sys.executable,
               "PATH": str(Path(os.environ["SystemRoot"]) / "System32")}
        for args, expected in ((["--smoke-test"], 0), (["--unknown-native-argument"], 1)):
            command = subprocess.list2cmdline([os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c"])
            command += ' "' + subprocess.list2cmdline([str(self.app / "launch.cmd"), *args]) + '"'
            result = subprocess.run(command, env=env, capture_output=True, encoding="utf-8", timeout=45)
            self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
            if expected == 0:
                self.assertIn("Native WPF smoke passed", result.stdout)
            else:
                self.assertIn("Unknown argument", result.stderr)

    def test_portable_embedded_runtime_cli_and_install_resolution(self):
        if not PORTABLE.is_file():
            self.skipTest("build the portable ZIP to test its bundled official Python")
        with tempfile.TemporaryDirectory(prefix="nerfed-portable-test-") as temp:
            folder = Path(temp) / "中文 portable release with spaces"
            with zipfile.ZipFile(PORTABLE) as archive:
                archive.extractall(folder)
            app = folder / "IsGPTNerfed"
            manifest = json.loads((app / "build-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["python"]["sha256"], "97dae5274cc54867065e8d5a3226e48c35017ed332a0fdb0e27d5b5821961297")
            self.assertTrue((app / "runtime/LICENSE.txt").is_file())
            resolved = self.run_exe(app, "--check-runtime", bundled=True).stdout.strip()
            self.assertTrue(Path(resolved).samefile(app / "runtime/python.exe"))
            self.assertIn("Native WPF smoke passed", self.run_exe(app, "--smoke-test", bundled=True).stdout)
            self.assertIn("Native self-test passed", self.run_exe(app, "--self-test", bundled=True).stdout)
            self.run_exe(app, "--render", str(folder / "compiled settings.png"), "--render-settings", bundled=True)
            # Use real CLI parsing in isolated homes, without inference or registration.
            state = folder / "isolated CLI state"
            env = {**os.environ, "PATH": str(Path(os.environ["SystemRoot"]) / "System32"),
                   "CODEX_HOME": str(state / "codex"), "NERFED_HOME": str(state / "ledger")}
            env.pop("NERFED_PYTHON", None)
            backend = app / "plugin/skills/is-gpt-nerfed/scripts/nerfed"
            result = subprocess.run([str(app / "runtime/python.exe"), "-X", "utf8", str(backend),
                                     "snapshot", "--json", "--demo"], env=env,
                                    capture_output=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(result.stdout)["demo"])
            powershell = str(Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe")
            result = subprocess.run([powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                     str(app / "bin/nerfed.ps1"), "selftest"], env=env,
                                    capture_output=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("18/18", result.stdout)
            self.assertIn("selftest: PASS", result.stdout)
            self.assertNotIn("skip", result.stdout.lower())
            self.assertEqual((app / "tests/fixtures/reference_subset.jsonl").read_bytes(),
                             (ROOT / "tests/fixtures/reference_subset.jsonl").read_bytes())
            self.assertEqual([str(path.relative_to(app / "tests")) for path in (app / "tests").rglob("*") if path.is_file()],
                             [str(Path("fixtures/reference_subset.jsonl"))])
            # Hook generation is read-only: decode its command and prove it pins bundled Python.
            code = "import runpy; ns=runpy.run_path(" + repr(str(backend)) + ",run_name='native_contract'); print(ns['powershell_hook_command']('Stop'))"
            result = subprocess.run([str(app / "runtime/python.exe"), "-X", "utf8", "-c", code],
                                    env=env, capture_output=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            encoded = result.stdout.strip().split()[-1]
            hook = base64.b64decode(encoded).decode("utf-16-le")
            self.assertIn(resolved, hook)
            # An explicitly fake setup target verifies install/wrapper resolution with no writes
            # to real Codex registration. The real backend is never called by install in this test.
            backend.write_text("import json,sys\nprint(json.dumps({'python':sys.executable,'args':sys.argv[1:]},ensure_ascii=False))\n", encoding="utf-8")
            powershell = str(Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe")
            result = subprocess.run([powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                     str(app / "install.ps1"), "-NoTrust"], env=env,
                                    capture_output=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            record = next(json.loads(line) for line in result.stdout.splitlines() if line.startswith("{"))
            self.assertTrue(Path(record["python"]).samefile(app / "runtime/python.exe"))
            self.assertEqual(record["args"], ["setup", "--no-trust"])
            result = subprocess.run([powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                     str(app / "bin/nerfed.ps1"), "config", "set", "codex_bin", "C:\\中文 path\\codex.exe"],
                                    env=env, capture_output=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["args"][-1], "C:\\中文 path\\codex.exe")


if __name__ == "__main__":
    unittest.main()
