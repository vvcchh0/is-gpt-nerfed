"""Offline checks for the Windows panel's subprocess contract and UI lifecycle."""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import tempfile
import time
import threading
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
WINDOWS_DIR = ROOT / "windows"
sys.path.insert(0, str(WINDOWS_DIR))

from app import BackendClient, BackendError, CommandOutput, PanelApp, PanelController, probe_presentation, tray_notifications  # noqa: E402


class BackendClientTests(unittest.TestCase):
    def test_closed_client_cannot_spawn_another_backend_process(self):
        popen = mock.Mock()
        client = BackendClient(popen=popen)
        client.close()
        with self.assertRaises(BackendError):
            client._run(("snapshot", "--json"), 1)
        popen.assert_not_called()

    def test_command_uses_utf8_python_and_demo_paths_are_isolated(self):
        with tempfile.TemporaryDirectory() as parent:
            with mock.patch.dict(os.environ, {"CODEX_HOME": "C:/real-codex", "NERFED_HOME": "C:/real-ledger",
                                              "NERFED_NO_UPDATE_CHECK": ""}, clear=False):
                client = BackendClient(demo=True)
                try:
                    command = client.command("snapshot", "--json", "--demo")
                    env = client.environment()
                    self.assertEqual(command[:3], [sys.executable, "-X", "utf8"])
                    self.assertEqual(command[3], str(Path(client.backend_path)))
                    self.assertEqual(command[4:], ["snapshot", "--json", "--demo"])
                    self.assertNotEqual(env["CODEX_HOME"], "C:/real-codex")
                    self.assertNotEqual(env["NERFED_HOME"], "C:/real-ledger")
                    self.assertTrue(env["CODEX_HOME"].startswith(client._demo_root))
                    self.assertTrue(env["NERFED_HOME"].startswith(client._demo_root))
                    self.assertEqual(env["NERFED_NO_UPDATE_CHECK"], "")  # explicit caller setting is respected
                finally:
                    client.close()

    def test_fresh_probe_forwards_optional_model_and_effort(self):
        client = BackendClient(demo=False)
        calls = []
        snapshot = {"config": {}, "threads": [], "overall": {"status": "clear"}}

        def fake_run(args, _timeout):
            calls.append(tuple(args))
            if args[0] == "snapshot":
                return CommandOutput(json.dumps(snapshot), "", 0)
            return CommandOutput("fresh probe complete", "", 0)

        client._run = fake_run
        try:
            result = client.perform("fresh", "gpt-6-astra", "high")
            self.assertTrue(result["ok"], result)
            self.assertEqual(calls[0], ("probe", "fresh", "--model", "gpt-6-astra", "--effort", "high"))
            self.assertEqual(calls[1], ("snapshot", "--json"))
        finally:
            client.close()


class ControllerTests(unittest.TestCase):
    @staticmethod
    def ambiguous_probe(**overrides):
        return {"id": "sol-61", "expected": "gpt-6.1-sol", "prediction": "gpt-6-astra", "probability": 1.0,
                "verdict": "AMBIGUOUS", "fingerprint_verdict": "AMBIGUOUS", "fingerprint_resolution": "overlap",
                "fingerprint_group": ["gpt-6-astra", "gpt-6.1-sol"],
                "results": [{"model": "gpt-6-astra", "probability": 1.0}], **overrides}

    def test_ambiguous_fingerprint_is_neutral_and_raw_candidate_is_labeled(self):
        probe = self.ambiguous_probe()
        text = probe_presentation(probe)
        self.assertIn("Declared model: gpt-6.1-sol", text)
        self.assertIn("Fingerprint: Astra / Sol 6.1 · not distinguishable", text)
        self.assertIn("closed-set similarity scores (not identity confidence)", text)
        self.assertNotIn("Fingerprint: MATCH", text)
        self.assertNotIn("Passive events", text)
        self.assertEqual(PanelApp._row_status({"last_probe": probe}), "AMBIGUOUS")
        snapshot = {"config": {"notify": True, "notify_on_ok": True}, "last_verdict": probe,
                    "overall": {"status": "ok", "downgraded": 0, "suspicious": 0}}
        self.assertEqual(tray_notifications(snapshot, ("ok", 0, 0), "old")[0], [])

    def test_passive_alert_keeps_independent_ambiguous_fingerprint_and_evidence(self):
        probe = self.ambiguous_probe(verdict="DOWNGRADED!", is_downgrade=True, verdict_basis="passive",
                                     passive_reasons=[{"kind": "silent_effort_change", "detail": "high → low",
                                                       "ts": "2026-10-10T10:00:00Z"}])
        text = probe_presentation(probe)
        self.assertIn("Fingerprint: Astra / Sol 6.1 · not distinguishable", text)
        self.assertIn("Passive events: Reasoning effort change alert", text)
        self.assertIn("high → low · 2026-10-10T10:00:00Z", text)
        self.assertEqual(PanelApp._row_status({"alert": True, "last_probe": probe}), "REASONING EFFORT CHANGE ALERT")
        snapshot = {"config": {"notify": True}, "last_verdict": probe,
                    "overall": {"status": "alert", "downgraded": 1, "suspicious": 0, "message": "1 alert"}}
        self.assertEqual(tray_notifications(snapshot, ("ok", 0, 0), "old")[0],
                         [("Reasoning effort change alert", "1 alert")])
        probe["passive_reasons"].append({"kind": "context_window_change", "detail": "256000 → 128000", "ts": "later"})
        self.assertIn("Passive events: Mixed passive alert", probe_presentation(probe))

    def test_unlisted_and_legacy_results_remain_readable(self):
        unlisted = {"verdict": "UNLISTED", "expected": "future-model", "prediction": "gpt-6-astra", "probability": 1.0}
        text = probe_presentation(unlisted)
        self.assertIn("UNLISTED · attribution unavailable", text)
        self.assertNotIn("100%", text)
        self.assertEqual(PanelApp._row_status({"last_probe": unlisted}), "UNLISTED")
        legacy = {"verdict": "DOWNGRADED!", "expected": "gpt-6-astra"}
        self.assertIn("not independently recorded", probe_presentation(legacy))
        self.assertIn("did not save separate reasons", probe_presentation(legacy))
        self.assertEqual(PanelApp._row_status({"last_probe": {"verdict": "MATCH"}}), "MATCH")

    def test_details_preserve_recorded_report_and_event_history(self):
        panel = PanelApp.__new__(PanelApp)
        panel._last_operation = ""
        panel._write_report = mock.Mock()
        panel._render_details({"kind": "thread", "model": "gpt-6.1-sol", "last_probe": self.ambiguous_probe(),
                               "report_text": "original verdict MISMATCH\nEvidence · high → low · old timestamp"})
        text = panel._write_report.call_args.args[0]
        self.assertIn("not distinguishable", text)
        self.assertIn("original verdict MISMATCH\nEvidence · high → low · old timestamp", text)

    def test_tray_notices_follow_notify_and_notify_on_ok(self):
        prev = ("ok", 0, 0)
        alert = {"config": {"notify": True, "notify_on_ok": False},
                 "overall": {"status": "alert", "downgraded": 1, "suspicious": 0, "message": "1 downgraded"},
                 "last_verdict": {"id": "probe-1", "verdict": "MISMATCH", "is_downgrade": True}}
        notices, signature, verdict_id = tray_notifications(alert, prev, None)
        self.assertEqual(notices, [("Model downgrade detected", "1 downgraded")])
        self.assertEqual(signature, ("alert", 1, 0))
        self.assertEqual(verdict_id, "probe-1")

        suppressed = dict(alert, config={"notify": False, "notify_on_ok": True})
        notices, _, _ = tray_notifications(suppressed, prev, None)
        self.assertEqual(notices, [])

        matched = {"config": {"notify": True, "notify_on_ok": False},
                   "overall": {"status": "ok", "downgraded": 0, "suspicious": 0, "message": "all clear"},
                   "last_verdict": {"id": "probe-2", "verdict": "MATCH"}}
        notices, _, _ = tray_notifications(matched, prev, "probe-1")
        self.assertEqual(notices, [])
        matched["config"]["notify_on_ok"] = True
        notices, _, _ = tray_notifications(matched, prev, "probe-1")
        self.assertEqual(notices, [("Probe matched", "all clear")])

    def test_action_arguments_are_queued_and_returned(self):
        events = queue.Queue()

        class FakeBackend:
            def __init__(self):
                self.calls = []
                self.cancelled = False

            def perform(self, action, *params):
                self.calls.append((action, params))
                return {"action": action, "ok": True, "params": params}

            def cancel_active(self):
                self.cancelled = True

        backend = FakeBackend()
        controller = PanelController(backend, events)
        settings = {"frequency": "1h", "mode": "nudge", "notify": False}
        self.assertTrue(controller.submit("settings", settings))
        result = events.get(timeout=3)
        self.assertEqual(result["action"], "settings")
        self.assertEqual(backend.calls, [("settings", (settings,))])
        controller.shutdown()
        self.assertTrue(backend.cancelled)
        self.assertFalse(controller.submit("snapshot"))
        controller.shutdown()  # idempotent

    def test_duplicate_inflight_action_is_coalesced(self):
        events = queue.Queue()
        release = threading.Event()
        started = threading.Event()

        class SlowBackend:
            def perform(self, action, *params):
                started.set()
                release.wait(2)
                return {"action": action, "ok": True}

            def cancel_active(self):
                release.set()

        controller = PanelController(SlowBackend(), events)
        self.assertTrue(controller.submit("snapshot"))
        self.assertTrue(started.wait(2))
        self.assertFalse(controller.submit("snapshot"))
        controller.shutdown()
        self.assertTrue(events.get(timeout=3)["ok"])


class WindowsSmokeTests(unittest.TestCase):
    @staticmethod
    def _run_smoke(interpreter: str, prefix: str) -> subprocess.CompletedProcess:
        command = [interpreter, "-X", "utf8", str(WINDOWS_DIR / "app.py"), "--smoke-test"]
        env = os.environ.copy()
        env["NERFED_NO_UPDATE_CHECK"] = "1"
        with tempfile.TemporaryDirectory(prefix=prefix) as parent:
            codex_home = Path(parent) / "codex-home"
            ledger_home = Path(parent) / "ledger"
            env["CODEX_HOME"] = str(codex_home)
            env["NERFED_HOME"] = str(ledger_home)
            completed = subprocess.run(command, cwd=ROOT, env=env, capture_output=True,
                                       text=True, encoding="utf-8", errors="replace", timeout=45)
            if codex_home.exists() or ledger_home.exists():
                raise AssertionError("demo mode wrote into the parent process CODEX_HOME/NERFED_HOME")
            return completed

    def test_demo_ui_loads_snapshot_and_exits(self):
        if os.name != "nt" and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            self.skipTest("Tk has no display in this environment; run on Windows for native smoke validation")
        # Running this file with python.exe covers the console-interpreter path.
        completed = self._run_smoke(sys.executable, "panel-smoke-parent-")
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertNotIn("Unable to start the Windows panel UI", completed.stderr)

    @unittest.skipUnless(os.name == "nt", "pythonw.exe is Windows-only")
    def test_pythonw_can_run_demo_panel_and_backend_snapshot(self):
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        if not pythonw.exists():
            self.skipTest("pythonw.exe is not installed beside the test interpreter")
        completed = self._run_smoke(str(pythonw), "panel-pythonw-smoke-")
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    @unittest.skipUnless(os.name == "nt", "pythonw.exe is Windows-only")
    def test_pythonw_can_run_the_backend_snapshot_command(self):
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        if not pythonw.exists():
            self.skipTest("pythonw.exe is not installed beside the test interpreter")
        with tempfile.TemporaryDirectory(prefix="panel-pythonw-backend-") as temp:
            env = os.environ.copy()
            env["CODEX_HOME"] = str(Path(temp) / "codex")
            env["NERFED_HOME"] = str(Path(temp) / "ledger")
            env["NERFED_NO_UPDATE_CHECK"] = "1"
            completed = subprocess.run(
                [str(pythonw), "-X", "utf8", str(ROOT / "plugin" / "skills" / "is-gpt-nerfed" / "scripts" / "nerfed"),
                 "snapshot", "--json", "--demo"],
                cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertTrue(json.loads(completed.stdout)["demo"])

    @unittest.skipUnless(os.name == "nt", "native notification area is Windows-only")
    def test_tray_icon_lifecycle(self):
        from tray import TrayIcon

        tray = TrayIcon(lambda _action: None)
        tray.start()
        deadline = time.monotonic() + 3
        while not tray.ready and not tray.failed and time.monotonic() < deadline:
            time.sleep(0.03)
        if tray.failed:
            self.skipTest(f"Windows notification area unavailable: {tray.error}")
        self.assertTrue(tray.ready, tray.error)
        tray.set_status("tray lifecycle test")
        tray.notify("is-gpt-nerfed test", "Native notification route check.")
        time.sleep(0.15)
        tray.stop()
        self.assertFalse(tray.ready)
        self.assertFalse(tray.failed, tray.error)
        self.assertFalse(tray._thread.is_alive())
        self.assertIsNone(tray._hwnd, "tray window handle should be released on shutdown")
        self.assertFalse(tray._added, "Shell_NotifyIcon entry should be removed on shutdown")
        self.assertFalse(tray._class_registered, "tray window class should be unregistered on shutdown")


if __name__ == "__main__":
    unittest.main()
