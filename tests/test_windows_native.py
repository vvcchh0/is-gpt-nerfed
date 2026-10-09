"""Offline native WPF interaction and Process transport contracts; no real inference."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == "win32", "inbox Windows PowerShell/WPF")
class WindowsNativeTests(unittest.TestCase):
    def run_panel(self, *args: str, timeout: int = 45) -> subprocess.CompletedProcess[str]:
        # native.ps1 must replace these sentinel homes with its own temporary homes.
        with tempfile.TemporaryDirectory(prefix="nerfed-native-test-") as temp:
            sentinel = Path(temp) / "user state must stay untouched"
            env = {**os.environ, "NERFED_PYTHON": sys.executable,
                   "CODEX_HOME": str(sentinel / "codex"), "NERFED_HOME": str(sentinel / "ledger")}
            result = subprocess.run(
                ["powershell.exe", "-NoLogo", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass",
                 "-File", str(ROOT / "windows/native.ps1"), *args],
                env=env, capture_output=True, encoding="utf-8", errors="replace", timeout=timeout,
            )
            self.assertFalse(sentinel.exists(), "native offline modes touched caller homes")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return result

    def test_fake_transport_interactions_and_lifecycle(self):
        result = self.run_panel("--self-test")
        self.assertIn("Native transport self-test passed", result.stdout)
        self.assertIn("Native self-test passed", result.stdout)
        home = next(line.removeprefix("Native isolated state: ") for line in result.stdout.splitlines()
                    if line.startswith("Native isolated state: "))
        self.assertFalse(Path(home).exists(), "self-test temporary state was not cleaned")

    def test_render_narrow_settings_at_150_percent_dpi(self):
        with tempfile.TemporaryDirectory(prefix="nerfed-native-render-") as temp:
            output = Path(temp) / "中文 render with spaces.png"
            result = self.run_panel("--render", str(output), "--render-settings",
                                    "--render-width", "380", "--render-scale", "1.5")
            self.assertIn("Rendered synthetic native panel", result.stdout)
            # Read only the PNG header: this test needs no Pillow or third-party package.
            data = output.read_bytes()
            self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(int.from_bytes(data[16:20], "big"), 570)
            self.assertEqual(int.from_bytes(data[20:24], "big"), 1620)


if __name__ == "__main__":
    unittest.main()
