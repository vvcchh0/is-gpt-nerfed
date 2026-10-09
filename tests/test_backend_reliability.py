"""Atomic-write, fail-open diagnostic and doctor regressions; all state is temporary."""
import argparse
import ctypes
import errno
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager, redirect_stdout
from io import StringIO
from unittest import mock

import test_dgc

dgc = test_dgc.dgc


@contextmanager
def hold_without_delete_share(path):
    """Hold a real Windows read handle that prevents atomic replacement."""
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel32.CreateFileW
    create.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    create.restype = wintypes.HANDLE
    close = kernel32.CloseHandle
    close.argtypes = (wintypes.HANDLE,)
    close.restype = wintypes.BOOL
    handle = create(str(path), 0x80000000, 0x00000003, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    lock = threading.Lock()

    def release():
        nonlocal handle
        with lock:
            if handle is not None:
                if not close(handle):
                    raise ctypes.WinError(ctypes.get_last_error())
                handle = None

    try:
        yield release
    finally:
        release()


class AtomicJsonTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "real Windows sharing semantics")
    def test_windows_reader_conflict_is_reproduced_then_recovers_after_release(self):
        with tempfile.TemporaryDirectory(prefix="nerfed JSON 中文 ") as temp:
            target = Path(temp) / "state.json"
            target.write_text('{"old": true}', encoding="utf-8")
            other = Path(temp) / "replacement.json"
            other.write_text('{"new": true}', encoding="utf-8")
            replace = os.replace
            with hold_without_delete_share(target) as release:
                with self.assertRaises(PermissionError) as failed:
                    replace(other, target)
                self.assertIn(failed.exception.winerror, (5, 32, 33))
                self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"old": True})
                timers = []

                def replace_then_release(source, destination):
                    try:
                        replace(source, destination)
                    except PermissionError:
                        if not timers:
                            timer = threading.Timer(0.025, release)
                            timers.append(timer)
                            timer.start()
                        raise

                try:
                    with mock.patch.object(dgc.os, "replace", side_effect=replace_then_release) as attempts:
                        dgc.write_json(str(target), {"new": "模型"})
                    self.assertGreater(attempts.call_count, 1)
                finally:
                    for timer in timers:
                        timer.join(timeout=2)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"new": "模型"})
            self.assertEqual(list(Path(temp).glob("state.json.*.tmp")), [])

    @unittest.skipUnless(sys.platform == "win32", "real Windows sharing semantics")
    def test_persistent_windows_reader_conflict_fails_bounded_and_preserves_json(self):
        with tempfile.TemporaryDirectory(prefix="nerfed JSON held ") as temp:
            target = Path(temp) / "state.json"
            target.write_text('{"old": true}', encoding="utf-8")
            with hold_without_delete_share(target):
                started = time.monotonic()
                with self.assertRaises(PermissionError):
                    dgc.write_json(str(target), {"new": True})
                elapsed = time.monotonic() - started
            self.assertLess(elapsed, 1.5, "persistent sharing denial must not exhaust a hook timeout")
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"old": True})
            self.assertEqual(list(Path(temp).glob("state.json.*.tmp")), [])

    @unittest.skipUnless(sys.platform == "win32", "real Windows access-denied semantics")
    def test_readonly_windows_target_still_raises_and_preserves_json(self):
        with tempfile.TemporaryDirectory(prefix="nerfed JSON readonly ") as temp:
            target = Path(temp) / "state.json"
            target.write_text('{"old": true}', encoding="utf-8")
            os.chmod(target, stat.S_IREAD)
            try:
                started = time.monotonic()
                with self.assertRaises(PermissionError) as failed:
                    dgc.write_json(str(target), {"new": True})
                self.assertEqual(failed.exception.winerror, 5)
                self.assertLess(time.monotonic() - started, 1.5)
                self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"old": True})
                self.assertEqual(list(Path(temp).glob("state.json.*.tmp")), [])
            finally:
                os.chmod(target, stat.S_IWRITE | stat.S_IREAD)

    def test_concurrent_writers_in_one_process_have_independent_temporary_files(self):
        for inject_denial in (False, True):
            with self.subTest(inject_denial=inject_denial), tempfile.TemporaryDirectory(prefix="nerfed JSON threads ") as temp:
                target = Path(temp) / "state.json"
                barrier = threading.Barrier(2)
                replace = os.replace
                state_lock = threading.Lock()
                sources, errors, injected = [], [], []
                attempts = {}
                retry_source = None

                def rendezvous(source, destination):
                    nonlocal retry_source
                    with state_lock:
                        attempt = attempts[source] = attempts.get(source, 0) + 1
                        if attempt == 1:
                            sources.append(source)
                            if inject_denial and retry_source is None:
                                retry_source = source
                    # Only synchronize each writer's first attempt. A retry must
                    # not wait for a peer that may already have finished writing.
                    if attempt == 1:
                        barrier.wait(timeout=3)
                    if inject_denial and source == retry_source and attempt == 1:
                        injected.append(source)
                        error = PermissionError(errno.EACCES, "injected transient replace denial", source)
                        error.winerror = 5
                        raise error
                    replace(source, destination)

                def write(value):
                    try:
                        dgc.write_json(str(target), {"writer": value})
                    except BaseException as error:
                        errors.append(error)

                # Exercise Windows retry behavior deterministically on every CI OS.
                system = "win32" if inject_denial else sys.platform
                with mock.patch.object(dgc.sys, "platform", system), \
                        mock.patch.object(dgc.os, "replace", side_effect=rendezvous):
                    threads = [threading.Thread(target=write, args=(i,)) for i in (1, 2)]
                    for thread in threads:
                        thread.start()
                    for thread in threads:
                        thread.join(timeout=5)
                self.assertFalse(any(thread.is_alive() for thread in threads))
                self.assertEqual(errors, [])
                self.assertEqual(len(sources), 2)
                self.assertEqual(len(set(sources)), 2)
                self.assertFalse(barrier.broken)
                if inject_denial:
                    self.assertEqual(injected, [retry_source])
                    self.assertGreaterEqual(attempts[retry_source], 2)
                self.assertLessEqual(max(attempts.values()), len(dgc.JSON_REPLACE_RETRY_DELAYS) + 1)
                self.assertIn(json.loads(target.read_text(encoding="utf-8"))["writer"], (1, 2))
                self.assertEqual(list(Path(temp).glob("*.tmp")), [])

    def test_serialization_failure_removes_temporary_file_and_keeps_target(self):
        with tempfile.TemporaryDirectory(prefix="nerfed JSON invalid ") as temp:
            target = Path(temp) / "state.json"
            target.write_text('{"old": true}', encoding="utf-8")
            with self.assertRaises(TypeError):
                dgc.write_json(str(target), {"invalid": object()})
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"old": True})
            self.assertEqual(list(Path(temp).glob("*.tmp")), [])

    def test_non_windows_permission_denial_and_unrelated_errors_are_not_retried(self):
        with tempfile.TemporaryDirectory(prefix="nerfed JSON errors ") as temp:
            target = str(Path(temp) / "state.json")
            for system, error in (("darwin", PermissionError(errno.EACCES, "denied")),
                                  ("win32", OSError(errno.ENOSPC, "no space"))):
                with self.subTest(system=system), mock.patch.object(dgc.sys, "platform", system), \
                        mock.patch.object(dgc.os, "replace", side_effect=error) as replace, \
                        mock.patch.object(dgc.time, "sleep") as sleep:
                    with self.assertRaises(type(error)):
                        dgc.write_json(target, {"new": True})
                    replace.assert_called_once()
                    sleep.assert_not_called()
            self.assertEqual(list(Path(temp).glob("*.tmp")), [])

    def test_hook_shares_a_wait_budget_across_writes_and_resets_it(self):
        with tempfile.TemporaryDirectory(prefix="nerfed JSON budget ") as temp:
            targets = [str(Path(temp) / f"state-{i}.json") for i in range(3)]

            def failing_hook(args):
                for target in targets:
                    with self.assertRaises(PermissionError):
                        dgc.write_json(target, {"new": True})
                return 0

            with mock.patch.object(dgc.sys, "platform", "win32"), \
                    mock.patch.object(dgc.os, "replace", side_effect=PermissionError(errno.EACCES, "denied")), \
                    mock.patch.object(dgc.time, "sleep") as sleep, \
                    mock.patch.object(dgc, "cmd_hook", side_effect=failing_hook):
                self.assertEqual(dgc.main(["hook", "--event", "Stop"]), 0)
            waits = [call.args[0] for call in sleep.call_args_list]
            self.assertLessEqual(sum(waits), dgc.HOOK_WRITE_RETRY_BUDGET_S)
            self.assertLess(sum(waits), 3 * sum(dgc.JSON_REPLACE_RETRY_DELAYS))
            self.assertIsNone(dgc._write_retry_budget.get())
            self.assertEqual(list(Path(temp).glob("*.tmp")), [])


class HookDiagnosticTests(unittest.TestCase):
    def test_hook_error_has_event_paths_and_stack_without_payload_or_exception_text(self):
        with tempfile.TemporaryDirectory(prefix="nerfed hook error ") as temp:
            home = Path(temp)
            failed_path = str(home / "state.json")
            errors_path, log_path = home / "errors.log", home / "log.jsonl"
            secret = "private-prompt-and-credential-token"

            def denied():
                error = PermissionError(errno.EACCES, secret, failed_path)
                error.winerror = 5
                error.filename2 = str(home / "account.json")
                raise error

            payload = {"hook_event_name": "UserPromptSubmit", "prompt": secret, "credential": secret,
                       "session_id": "private-session-body"}
            with mock.patch.multiple(dgc, NERFED_HOME=temp, ERRORS_PATH=str(errors_path), LOG_PATH=str(log_path)), \
                    mock.patch.object(dgc, "load_config", return_value=dict(dgc.DEFAULT_CONFIG)), \
                    mock.patch.object(dgc, "ensure_dirs", side_effect=denied), \
                    mock.patch.object(dgc.sys, "stdin", StringIO(json.dumps(payload))):
                self.assertEqual(dgc.main(["hook", "--event", "Stop"]), 0)
            text = errors_path.read_text(encoding="utf-8")
            activity = log_path.read_text(encoding="utf-8")
            for private in (secret, "private-session-body", "credential"):
                self.assertNotIn(private, text + activity)
            self.assertEqual(len(text.splitlines()), 1)
            details = json.loads(text.split(" hook crashed ", 1)[1])
            self.assertEqual(details["event"], "UserPromptSubmit")
            self.assertEqual(details["exception_type"], "PermissionError")
            self.assertEqual((details["errno"], details["winerror"]), (errno.EACCES, 5))
            self.assertEqual(details["filename"], failed_path)
            self.assertEqual(details["filename2"], str(home / "account.json"))
            self.assertIn("in cmd_hook", details["traceback"])
            self.assertIn("in denied", details["traceback"])
            self.assertEqual(json.loads(activity)["traceback"], details["traceback"])

    def test_unknown_event_and_system_exit_text_are_not_logged_and_hook_stays_fail_open(self):
        with tempfile.TemporaryDirectory(prefix="nerfed hook unknown ") as temp:
            errors_path = Path(temp) / "errors.log"
            secret = "do-not-log-this-event-or-message"
            with mock.patch.multiple(dgc, NERFED_HOME=temp, ERRORS_PATH=str(errors_path), LOG_PATH=str(Path(temp) / "log.jsonl")), \
                    mock.patch.object(dgc, "cmd_hook", side_effect=SystemExit(secret)):
                self.assertEqual(dgc.main(["hook", "--event", secret]), 0)
            text = errors_path.read_text(encoding="utf-8")
            self.assertNotIn(secret, text)
            self.assertIn('"event": "unknown"', text)
            self.assertIn('"exception_type": "SystemExit"', text)


class DoctorSummaryTests(unittest.TestCase):
    def doctor(self, home, *, history="", notes=(), trusted=True, recent=True):
        errors_path = home / "errors.log"
        errors_path.write_text(history, encoding="utf-8")
        manifest = home / "manifest.json"
        manifest.write_text(json.dumps({"hooks": {"hooks": {"Stop": [{"hooks": [{"command":
            "powershell.exe EncodedCommand ${PLUGIN_ROOT} exit 0"}]}]}}}), encoding="utf-8")
        hs = {"state": "trusted" if trusted else "unknown", "trusted": 5, "total": 5,
              "checked_ago": "now", "desktop_loaded": True, "desktop_loaded_current": True,
              "last_desktop_event_ago": "now", "notes": list(notes)}
        events = [{"ts": dgc.iso(), "event": "PreToolUse"}] if recent else []
        output = StringIO()
        with mock.patch.multiple(dgc, NERFED_HOME=str(home), CODEX_HOME=str(home),
                                 CONFIG_PATH=str(home / "missing-config.json"), ERRORS_PATH=str(errors_path)), \
                mock.patch.object(dgc, "load_config", return_value=dict(dgc.DEFAULT_CONFIG)), \
                mock.patch.object(dgc, "update_status", return_value={"enabled": False}), \
                mock.patch.object(dgc, "codex_bin", return_value="fake-codex"), \
                mock.patch.object(dgc, "codex_version", return_value="0.162.0"), \
                mock.patch.object(dgc, "codex_candidates", return_value=[]), \
                mock.patch.object(dgc, "db_query", return_value=[]), \
                mock.patch.object(dgc, "manifest_paths", return_value=[str(manifest)]), \
                mock.patch.object(dgc, "decoded_windows_hook_text", return_value="exit 0"), \
                mock.patch.object(dgc, "config_toml_text", return_value=""), \
                mock.patch.object(dgc, "plugin_enabled_in_config", return_value=True), \
                mock.patch.object(dgc, "hooks_status", return_value=hs), \
                mock.patch.object(dgc, "tail_jsonl", return_value=events), \
                mock.patch.object(dgc.cas, "fork_doctor", side_effect=AssertionError("doctor must not probe")), \
                redirect_stdout(output):
            result = dgc.cmd_doctor(argparse.Namespace(live=False, fork=False))
        self.assertEqual(errors_path.read_text(encoding="utf-8"), history, "doctor must retain error history")
        return result, output.getvalue()

    def test_historical_error_and_newer_hook_are_warning_not_all_good_or_recovery(self):
        with tempfile.TemporaryDirectory(prefix="nerfed doctor history ") as temp:
            error_ts = dgc.iso(dgc.now() - 3600)
            result, output = self.doctor(Path(temp), history=f"{error_ts} hook crashed: PermissionError(13, 'denied')\n")
            self.assertEqual(result, 0, output)
            self.assertIn(f"last error at {error_ts}", output)
            self.assertIn("hook activity recorded afterward:", output)
            self.assertIn("does not establish that the error is resolved", output)
            self.assertTrue(output.rstrip().endswith("1 warning(s) — review warnings above"), output)
            self.assertNotIn("all good", output)
            self.assertNotIn("restart", output)
            self.assertNotIn(dgc.SKILL_CMD, output)

    def test_codex_loading_error_is_hard_failure(self):
        with tempfile.TemporaryDirectory(prefix="nerfed doctor failed ") as temp:
            result, output = self.doctor(Path(temp), notes=[{"kind": "error", "message": "hook load failed"}])
            self.assertEqual(result, 1, output)
            self.assertIn("1 problem(s), 0 warning(s)", output)
            self.assertNotIn("all good", output)

    def test_other_warnings_are_counted_and_empty_history_is_not_a_warning(self):
        with tempfile.TemporaryDirectory(prefix="nerfed doctor warn ") as temp:
            result, output = self.doctor(Path(temp), trusted=False, recent=False,
                                         notes=[{"kind": "warning", "message": "hook loading uncertain"}])
            self.assertEqual(result, 0, output)
            self.assertTrue(output.rstrip().endswith("3 warning(s) — review warnings above"), output)
            self.assertNotIn("all good", output)

    def test_clean_pass_has_no_restart_or_probe_requirement(self):
        with tempfile.TemporaryDirectory(prefix="nerfed doctor clean ") as temp:
            result, output = self.doctor(Path(temp))
            self.assertEqual(result, 0, output)
            self.assertTrue(output.rstrip().endswith("all good — passive hook checks passed"), output)
            self.assertNotIn("restart", output)
            self.assertNotIn(dgc.SKILL_CMD, output)


if __name__ == "__main__":
    unittest.main()
