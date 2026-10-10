"""Windows desktop panel for is-gpt-nerfed.

The panel is intentionally a thin client: all detection and configuration state
remain in the shared ``nerfed`` backend.  Backend calls run in a worker thread;
the Tk thread only builds widgets and consumes queued results.
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from tkinter import ttk
from typing import Any, Callable


ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "plugin" / "skills" / "is-gpt-nerfed" / "scripts" / "nerfed"
CONFIG_KEYS = ("frequency", "mode", "notify", "sound", "hide_titles", "queries")
EFFORTS = ("", "none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")
WINDOWS_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def fingerprint_verdict(probe: dict[str, Any]) -> str:
    return str(probe.get("fingerprint_verdict") or probe.get("verdict") or "")


def passive_alert_label(probe: dict[str, Any]) -> str:
    """Describe recorded passive evidence without treating a fingerprint candidate as identity."""
    def kind_label(kind: str) -> str:
        return next((label for token, label in (("effort", "Reasoning effort change"), ("model", "Model identifier change"),
                                                ("context", "Context window change"), ("tier", "Service tier change"))
                     if token in kind), "Passive evidence")

    kinds = {kind_label(str(reason.get("kind") or "")) for reason in probe.get("passive_reasons") or []}
    return "Mixed passive alert" if len(kinds) > 1 else f"{next(iter(kinds))} alert" if kinds else "Passive change alert"


def has_passive_alert(probe: dict[str, Any]) -> bool:
    return bool(probe.get("verdict_basis") == "passive" or probe.get("passive_reasons") or probe.get("verdict") == "DOWNGRADED!")


def probe_presentation(probe: dict[str, Any], declared_model: str = "") -> str:
    """A presentation-only summary; raw reports and historical evidence remain intact below it."""
    if not probe:
        return ""
    verdict = fingerprint_verdict(probe)
    overlap = probe.get("fingerprint_resolution") == "overlap" or verdict == "AMBIGUOUS"
    lines = [f"Declared model: {probe.get('expected') or declared_model or '?'}"]
    if probe.get("stale_account"):
        lines.append("Fingerprint: UNVERIFIED (result belongs to another or unknown account)")
    elif overlap:
        lines.extend(("Fingerprint: Astra / Sol 6.1 · not distinguishable",
                      "The bank cannot reliably distinguish these models. A raw Astra candidate does not confirm model identity."))
    elif verdict == "UNLISTED" or probe.get("fingerprint_resolution") == "unlisted":
        lines.append("Fingerprint: UNLISTED · attribution unavailable; the declared model is absent from the bank.")
    elif verdict == "DOWNGRADED!":
        lines.append("Fingerprint: not independently recorded in this older result")
    else:
        lines.append(f"Fingerprint: {verdict or 'unavailable'}" + (f" · {probe['prediction']}" if probe.get("prediction") else ""))
    if probe.get("finished") or probe.get("finished_ago"):
        lines.append(f"Probe time: {probe.get('finished') or probe.get('finished_ago')}")
    if probe.get("results"):
        lines.append("Raw candidates · closed-set similarity scores (not identity confidence): " + " · ".join(
            f"{result.get('model')} {float(result.get('probability') or 0):.0%}" for result in probe["results"]))
    if has_passive_alert(probe):
        lines.extend(("", "Passive events: " + passive_alert_label(probe)))
        reasons = probe.get("passive_reasons") or []
        for reason in reasons:
            lines.append(f"  {reason.get('kind') or 'recorded evidence'}: {reason.get('detail') or '?'}" +
                         (f" · {reason['ts']}" if reason.get("ts") else ""))
        if not reasons:
            lines.append("  The older record did not save separate reasons; see the recorded evidence and report below.")
    if probe.get("recorded_verdict"):
        lines.append(f"Recorded verdict: {probe['recorded_verdict']} (display uses current attribution rules)")
    return "\n".join(lines)


def tray_notifications(snapshot: dict[str, Any], previous_signature: tuple | None,
                      previous_verdict_id: str | None) -> tuple[list[tuple[str, str]], tuple, str | None]:
    """Select only configured, actionable tray notices and advance their comparison keys."""
    config = snapshot.get("config") or {}
    overall = snapshot.get("overall") or {}
    state = str(overall.get("status") or "ok")
    signature = (state, int(overall.get("downgraded") or 0), int(overall.get("suspicious") or 0))
    verdict = snapshot.get("last_verdict") or {}
    verdict_id = verdict.get("id")
    notices: list[tuple[str, str]] = []
    if config.get("notify", True):
        message = str(overall.get("message") or state)
        new_verdict = bool(verdict_id and verdict_id != previous_verdict_id)
        if previous_signature is not None:
            if state in ("alert", "warn") and signature != previous_signature:
                title = (passive_alert_label(verdict) if has_passive_alert(verdict) else "Model downgrade detected") if state == "alert" else "Suspicious probe result"
                notices.append((title, message))
            elif new_verdict and verdict.get("is_downgrade"):
                notices.append((passive_alert_label(verdict) if has_passive_alert(verdict) else "Model downgrade detected", message))
            elif new_verdict and verdict.get("is_suspicious"):
                notices.append(("Suspicious probe result", message))
            elif (config.get("notify_on_ok") and new_verdict and fingerprint_verdict(verdict) == "MATCH"
                  and verdict.get("fingerprint_resolution") != "overlap"):
                notices.append(("Probe matched", message))
    return notices, signature, verdict_id


class BackendError(RuntimeError):
    """A backend command failed or returned data the panel cannot use."""


@dataclass
class CommandOutput:
    stdout: str
    stderr: str
    returncode: int

    @property
    def text(self) -> str:
        return "\n".join(part for part in (self.stdout.strip(), self.stderr.strip()) if part)


class BackendClient:
    """Run the shared Python CLI with isolated demo state when requested."""

    def __init__(self, backend_path: str | os.PathLike[str] = BACKEND, *, demo: bool = False,
                 popen: Callable[..., Any] = subprocess.Popen):
        self.backend_path = str(Path(backend_path).resolve())
        self.demo = bool(demo)
        self._popen = popen
        self._process_lock = threading.Lock()
        self._active_process: Any | None = None
        self._closed = False
        self._temporary: tempfile.TemporaryDirectory[str] | None = None
        self._demo_root: str | None = None
        if self.demo:
            self._temporary = tempfile.TemporaryDirectory(prefix="if-gpt-nerfed-demo-")
            self._demo_root = self._temporary.name

    def command(self, *args: str) -> list[str]:
        return [sys.executable, "-X", "utf8", self.backend_path, *map(str, args)]

    def environment(self) -> dict[str, str]:
        env = os.environ.copy()
        env.setdefault("NERFED_NO_UPDATE_CHECK", "1")
        if self.demo:
            assert self._demo_root is not None
            env["CODEX_HOME"] = os.path.join(self._demo_root, "codex-home")
            env["NERFED_HOME"] = os.path.join(self._demo_root, "ledger")
        return env

    def _run(self, args: tuple[str, ...], timeout: float) -> CommandOutput:
        command = self.command(*args)
        with self._process_lock:
            if self._closed:
                raise BackendError("The panel is shutting down; no new backend process will be started.")
            try:
                process = self._popen(
                    command,
                    cwd=str(ROOT),
                    env=self.environment(),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=WINDOWS_NO_WINDOW if os.name == "nt" else 0,
                )
            except Exception as exc:
                raise BackendError(f"Could not start nerfed backend: {exc}") from exc
            self._active_process = process
        try:
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                process.kill()
                stdout, stderr = process.communicate()
                detail = "\n".join(x for x in (stdout or "", stderr or "") if x.strip())
                suffix = f"\n{detail}" if detail else ""
                raise BackendError(f"Backend command timed out after {int(timeout)} seconds: {' '.join(args)}{suffix}") from exc
            result = CommandOutput(stdout or "", stderr or "", int(process.returncode or 0))
        finally:
            with self._process_lock:
                if self._active_process is process:
                    self._active_process = None

        if result.returncode != 0:
            raise BackendError(result.text or f"Backend command exited with code {result.returncode}")
        return result

    def _snapshot(self) -> dict[str, Any]:
        args = ("snapshot", "--json", "--demo") if self.demo else ("snapshot", "--json")
        output = self._run(args, 90)
        try:
            data = json.loads(output.stdout)
        except json.JSONDecodeError as exc:
            raise BackendError(f"The backend returned invalid snapshot JSON: {exc}\n{output.text}") from exc
        if not isinstance(data, dict):
            raise BackendError("The backend snapshot was not a JSON object.")
        return data

    def perform(self, action: str, *params: Any) -> dict[str, Any]:
        """Execute one UI action and return a UI-thread-safe result record."""
        if self.demo and action in {"tick", "probe", "retry", "fresh"}:
            return {"action": action, "ok": False, "error": "Inference and scheduled probes are disabled in demo mode."}

        try:
            if action == "snapshot":
                return {"action": action, "ok": True, "snapshot": self._snapshot()}

            if action == "tick":
                output = self._run(("tick",), 900).text
                return {"action": action, "ok": True, "output": output, "snapshot": self._snapshot()}

            if action in ("probe", "retry"):
                thread_id = str(params[0])
                output = self._run(("worker", "--thread", thread_id), 1200).text
                return {"action": action, "ok": True, "output": output, "snapshot": self._snapshot()}

            if action == "fresh":
                model = str(params[0] or "").strip()
                effort = str(params[1] or "").strip()
                command = ["probe", "fresh"]
                if model:
                    command.extend(("--model", model))
                if effort:
                    command.extend(("--effort", effort))
                output = self._run(tuple(command), 1200).text
                return {"action": action, "ok": True, "output": output, "snapshot": self._snapshot()}

            if action == "doctor":
                output = self._run(("doctor",), 240).text
                return {"action": action, "ok": True, "output": output}

            if action == "settings":
                settings = dict(params[0])
                unknown = set(settings) - set(CONFIG_KEYS)
                if unknown:
                    raise BackendError(f"Unsupported panel setting(s): {', '.join(sorted(unknown))}")
                receipts = []
                for key in CONFIG_KEYS:
                    if key not in settings:
                        continue
                    value = settings[key]
                    if isinstance(value, bool):
                        value = "true" if value else "false"
                    output = self._run(("config", "set", key, str(value)), 60)
                    receipts.append(output.text)
                return {"action": action, "ok": True, "output": "\n".join(receipts), "snapshot": self._snapshot()}

            raise BackendError(f"Unknown panel action: {action}")
        except Exception as exc:
            return {"action": action, "ok": False, "error": str(exc)}

    def cancel_active(self) -> None:
        with self._process_lock:
            self._closed = True
            process = self._active_process
        if process is not None:
            try:
                process.terminate()
            except Exception:
                pass

    def close(self) -> None:
        self.cancel_active()
        with self._process_lock:
            process = self._active_process
        if process is not None:
            try:
                process.wait(timeout=2)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
        if self._temporary is not None:
            self._temporary.cleanup()
            self._temporary = None
            self._demo_root = None


class PanelController:
    """Serialize backend work and publish results without touching Tk widgets."""

    def __init__(self, backend: BackendClient, events: queue.Queue | None = None):
        self.backend = backend
        self.events: queue.Queue = events if events is not None else queue.Queue()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="nerfed-panel")
        self._lock = threading.Lock()
        self._pending: set[tuple[str, str]] = set()
        self._closed = False

    def submit(self, action: str, *params: Any) -> bool:
        key = (action, repr(params))
        with self._lock:
            if self._closed or key in self._pending:
                return False
            self._pending.add(key)
            try:
                future = self._executor.submit(self.backend.perform, action, *params)
            except RuntimeError:
                self._pending.discard(key)
                return False

        def completed(done) -> None:
            try:
                result = done.result()
            except Exception as exc:  # defensive: BackendClient normally returns an error record
                result = {"action": action, "ok": False, "error": str(exc)}
            with self._lock:
                self._pending.discard(key)
            self.events.put(result)

        future.add_done_callback(completed)
        return True

    def shutdown(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self.backend.cancel_active()
        self._executor.shutdown(wait=False, cancel_futures=True)


def set_windows_dpi_awareness() -> None:
    """Ask Windows for per-monitor DPI scaling before Tk creates its first window."""
    if os.name != "nt":
        return
    try:
        ctypes = __import__("ctypes")
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


class PanelApp:
    def __init__(self, root: tk.Tk, backend: BackendClient, *, smoke_test: bool = False):
        self.root = root
        self.backend = backend
        self.demo = backend.demo
        self.smoke_test = smoke_test
        self.controller = PanelController(backend)
        self.rows: list[dict[str, Any]] = []
        self.snapshot: dict[str, Any] | None = None
        self._selected_key: str | None = None
        self._last_operation = ""
        self._last_notification_signature: tuple | None = None
        self._last_verdict_id: str | None = None
        self._busy_action: str | None = None
        self._closing = False
        self.exit_code = 0
        self._tray: Any | None = None
        self._tray_events: queue.Queue[str] = queue.Queue()

        root.title("is-gpt-nerfed — Windows panel" + (" [DEMO]" if self.demo else ""))
        root.geometry("1120x780")
        root.minsize(900, 650)
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._set_theme()
        self._build_widgets()
        if os.name == "nt" and not self.smoke_test:
            try:
                from tray import TrayIcon
                self._tray = TrayIcon(self._tray_events.put)
                self._tray.start()
                root.after(250, self._check_tray_startup)
            except Exception:
                self._tray = None

        self.root.after(80, self._poll_events)
        self.root.after(150, lambda: self._submit("snapshot"))
        if not self.demo:
            self.root.after(30_000, self._scheduled_tick)

    def _set_theme(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("vista" if os.name == "nt" else "clam")
        except tk.TclError:
            pass
        family = "Segoe UI" if os.name == "nt" else "TkDefaultFont"
        style.configure("TLabel", font=(family, 9))
        style.configure("Header.TLabel", font=(family, 17, "bold"))
        style.configure("Section.TLabel", font=(family, 10, "bold"))
        style.configure("Warning.TLabel", font=(family, 9, "bold"), foreground="#8a3b00")
        style.configure("Status.TLabel", font=(family, 10, "bold"))

    def _build_widgets(self) -> None:
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)
        header = ttk.Frame(outer)
        header.pack(fill="x")
        title = "is-gpt-nerfed"
        if self.demo:
            title += " — offline demo"
        ttk.Label(header, text=title, style="Header.TLabel").pack(side="left")
        self.status_var = tk.StringVar(value="Loading local status…")
        ttk.Label(header, textvariable=self.status_var, style="Status.TLabel").pack(side="right", padx=(12, 0))

        warning = ("Probes run real model inference and can use billed tokens. The upstream default schedule is every 30 minutes; "
                   "scheduled checks run while this panel is open. You can change frequency or set mode to nudge below.")
        if self.demo:
            warning = "Demo mode uses temporary state. It will not read or change your Codex state and cannot run probes or scheduled checks."
        ttk.Label(outer, text=warning, style="Warning.TLabel", wraplength=1060, justify="left").pack(fill="x", pady=(7, 6))
        install_note = "Install or repair from this checkout with:  .\\install.ps1  (hooks are not auto-trusted)"
        ttk.Label(outer, text=install_note, wraplength=1060).pack(fill="x", pady=(0, 8))

        body = ttk.Panedwindow(outer, orient="horizontal")
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body, padding=(0, 0, 10, 0))
        right = ttk.Frame(body)
        body.add(left, weight=1)
        body.add(right, weight=2)
        # Reserve a useful session/status column while preserving room for the report.
        self.root.after(120, lambda: self._position_session_pane(body))

        ttk.Label(left, text="Sessions and status", style="Section.TLabel").pack(anchor="w", pady=(0, 5))
        list_frame = ttk.Frame(left)
        list_frame.pack(fill="both", expand=True)
        self.session_list = tk.Listbox(list_frame, exportselection=False, activestyle="underline", font=("Segoe UI" if os.name == "nt" else "TkDefaultFont", 9))
        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.session_list.yview)
        self.session_list.configure(yscrollcommand=scroll.set)
        self.session_list.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.session_list.bind("<<ListboxSelect>>", self._on_select)

        settings_frame = ttk.LabelFrame(left, text="Settings", padding=8)
        settings_frame.pack(fill="x", pady=(10, 0))
        self.frequency_var = tk.StringVar(value="30m")
        self.mode_var = tk.StringVar(value="auto")
        self.queries_var = tk.StringVar(value="3")
        self.notify_var = tk.BooleanVar(value=True)
        self.sound_var = tk.BooleanVar(value=True)
        self.hide_titles_var = tk.BooleanVar(value=False)
        ttk.Label(settings_frame, text="Frequency").grid(row=0, column=0, sticky="w", padx=(0, 5), pady=2)
        self.frequency_box = ttk.Combobox(settings_frame, textvariable=self.frequency_var,
                                           values=("30m", "1h", "2h", "4h", "turns:8", "manual"), width=12)
        self.frequency_box.grid(row=0, column=1, sticky="ew", pady=2)
        ttk.Label(settings_frame, text="Mode").grid(row=1, column=0, sticky="w", padx=(0, 5), pady=2)
        self.mode_box = ttk.Combobox(settings_frame, textvariable=self.mode_var, values=("auto", "nudge"), state="readonly", width=12)
        self.mode_box.grid(row=1, column=1, sticky="ew", pady=2)
        ttk.Label(settings_frame, text="Queries").grid(row=2, column=0, sticky="w", padx=(0, 5), pady=2)
        self.queries_box = ttk.Spinbox(settings_frame, from_=1, to=3, textvariable=self.queries_var, width=5)
        self.queries_box.grid(row=2, column=1, sticky="w", pady=2)
        ttk.Checkbutton(settings_frame, text="Desktop notifications", variable=self.notify_var).grid(row=3, column=0, columnspan=2, sticky="w", pady=1)
        ttk.Checkbutton(settings_frame, text="Sound on downgrade", variable=self.sound_var).grid(row=4, column=0, columnspan=2, sticky="w", pady=1)
        ttk.Checkbutton(settings_frame, text="Hide session titles", variable=self.hide_titles_var).grid(row=5, column=0, columnspan=2, sticky="w", pady=1)
        self.apply_settings_button = ttk.Button(settings_frame, text="Apply settings", command=self._apply_settings)
        self.apply_settings_button.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(5, 0))
        settings_frame.columnconfigure(1, weight=1)

        ttk.Label(right, text="Selected session report", style="Section.TLabel").pack(anchor="w", pady=(0, 5))
        text_frame = ttk.Frame(right)
        text_frame.pack(fill="both", expand=True)
        # Keep the report useful but leave vertical room for both action rows at normal window size.
        text_frame.configure(height=320)
        text_frame.pack_propagate(False)
        self.report = tk.Text(text_frame, wrap="word", state="disabled", font=("Consolas" if os.name == "nt" else "TkFixedFont", 9),
                              padx=8, pady=8, background="#fbfbfb", relief="solid", borderwidth=1)
        report_scroll = ttk.Scrollbar(text_frame, orient="vertical", command=self.report.yview)
        self.report.configure(yscrollcommand=report_scroll.set)
        self.report.pack(side="left", fill="both", expand=True)
        report_scroll.pack(side="right", fill="y")

        actions = ttk.Frame(right)
        actions.pack(fill="x", pady=(9, 0))
        self.probe_button = ttk.Button(actions, text="Probe selected", command=self._probe_selected)
        self.probe_button.pack(side="left", padx=(0, 5))
        self.retry_button = ttk.Button(actions, text="Retry selected", command=self._retry_selected)
        self.retry_button.pack(side="left", padx=(0, 5))
        self.fresh_button = ttk.Button(actions, text="Fresh probe", command=self._fresh_probe)
        self.fresh_button.pack(side="left", padx=(0, 10))

        fresh_options = ttk.Frame(right)
        fresh_options.pack(fill="x", pady=(5, 0))
        ttk.Label(fresh_options, text="Fresh model").grid(row=0, column=0, sticky="w", padx=(0, 5))
        self.model_var = tk.StringVar(value="")
        self.model_entry = ttk.Entry(fresh_options, textvariable=self.model_var, width=18)
        self.model_entry.grid(row=0, column=1, sticky="ew", padx=(0, 10))
        ttk.Label(fresh_options, text="Effort").grid(row=0, column=2, sticky="w", padx=(0, 5))
        self.effort_var = tk.StringVar(value="")
        self.effort_box = ttk.Combobox(fresh_options, textvariable=self.effort_var, values=EFFORTS, width=12)
        self.effort_box.grid(row=0, column=3, sticky="w")
        fresh_options.columnconfigure(1, weight=1)

        footer = ttk.Frame(right)
        footer.pack(fill="x", pady=(8, 0))
        self.refresh_button = ttk.Button(footer, text="Refresh", command=lambda: self._submit("snapshot"))
        self.refresh_button.pack(side="left", padx=(0, 5))
        self.doctor_button = ttk.Button(footer, text="Doctor", command=lambda: self._submit("doctor"))
        self.doctor_button.pack(side="left")
        self._operation_var = tk.StringVar(value="")
        ttk.Label(footer, textvariable=self._operation_var).pack(side="left", fill="x", expand=True, padx=10)

        if self.demo:
            for widget in (self.apply_settings_button, self.probe_button, self.retry_button, self.fresh_button,
                           self.model_entry, self.effort_box):
                widget.configure(state="disabled")

    @staticmethod
    def _position_session_pane(body: ttk.Panedwindow) -> None:
        try:
            body.sashpos(0, 350)
        except tk.TclError:
            pass

    def _write_report(self, text: str) -> None:
        self.report.configure(state="normal")
        self.report.delete("1.0", "end")
        self.report.insert("1.0", text or "No report is available for this item.")
        self.report.configure(state="disabled")

    def _selected_row(self) -> dict[str, Any] | None:
        selected = self.session_list.curselection()
        if not selected or selected[0] >= len(self.rows):
            return None
        return self.rows[selected[0]]

    def _on_select(self, _event=None) -> None:
        row = self._selected_row()
        if row is None:
            return
        self._selected_key = row.get("id") or "__fresh__"
        self._render_details(row)
        self._update_action_states()

    def _render_details(self, row: dict[str, Any] | None = None) -> None:
        row = row or self._selected_row()
        if row is None:
            body = "Loading session report…"
        elif row.get("kind") == "fresh":
            body = str((self.snapshot or {}).get("global_report_text") or "Fresh session report is not available yet.")
        else:
            body = str(row.get("report_text") or "No probe report is available for this session.")
            if not row.get("report_text"):
                status = [f"Session: {row.get('title') or row.get('id')}", f"Thread: {row.get('id')}",
                          f"Model: {row.get('model') or '?'}", f"Reasoning effort: {row.get('effort') or '?'}",
                          f"Last activity: {row.get('updated_ago') or '?'}"]
                body = "\n".join(status) + "\n\n" + body
        if row:
            presentation = probe_presentation(row.get("last_probe") or {}, str(row.get("model") or ""))
            if presentation:
                body = presentation + "\n\nRecorded report and evidence\n----------------------------\n" + body
        if self._last_operation:
            body = "Latest panel action\n-------------------\n" + self._last_operation.strip() + "\n\n" + body
        self._write_report(body)

    def _update_action_states(self) -> None:
        row = self._selected_row()
        is_thread = bool(row and row.get("kind") != "fresh")
        enabled = not self.demo and self._busy_action is None
        self.probe_button.configure(state="normal" if enabled and is_thread else "disabled")
        self.retry_button.configure(state="normal" if enabled and is_thread else "disabled")
        self.fresh_button.configure(state="normal" if enabled else "disabled")
        self.refresh_button.configure(state="disabled" if self._busy_action else "normal")
        self.doctor_button.configure(state="disabled" if self._busy_action else "normal")
        self.apply_settings_button.configure(state="normal" if enabled else "disabled")
        self.model_entry.configure(state="normal" if enabled else "disabled")
        self.effort_box.configure(state="normal" if enabled else "disabled")

    def _submit(self, action: str, *params: Any) -> None:
        if self._closing or self._busy_action is not None:
            return
        if self.controller.submit(action, *params):
            self._busy_action = action
            self._operation_var.set(f"Running {action}…")
            self.status_var.set(f"Running {action}…")
            self._update_action_states()

    def _probe_selected(self) -> None:
        row = self._selected_row()
        if row and row.get("kind") != "fresh":
            self._submit("probe", row["id"])

    def _retry_selected(self) -> None:
        row = self._selected_row()
        if row and row.get("kind") != "fresh":
            self._submit("retry", row["id"])

    def _fresh_probe(self) -> None:
        self._submit("fresh", self.model_var.get(), self.effort_var.get())

    def _apply_settings(self) -> None:
        settings: dict[str, Any] = {
            "frequency": self.frequency_var.get().strip(),
            "mode": self.mode_var.get().strip(),
            "queries": self.queries_var.get().strip(),
            "notify": self.notify_var.get(),
            "sound": self.sound_var.get(),
            "hide_titles": self.hide_titles_var.get(),
        }
        if not settings["frequency"] or settings["mode"] not in ("auto", "nudge"):
            self.status_var.set("Enter a valid frequency and choose auto or nudge mode.")
            return
        self._submit("settings", settings)

    def _scheduled_tick(self) -> None:
        if self._closing:
            return
        if not self.demo and self._busy_action is None:
            self._submit("tick")
        self.root.after(30_000, self._scheduled_tick)

    def _load_settings(self, snapshot: dict[str, Any]) -> None:
        config = snapshot.get("config") or {}
        self.frequency_var.set(str(config.get("frequency", "30m")))
        self.mode_var.set(str(config.get("mode", "auto")))
        self.queries_var.set(str(config.get("queries", 3)))
        self.notify_var.set(bool(config.get("notify", True)))
        self.sound_var.set(bool(config.get("sound", True)))
        self.hide_titles_var.set(bool(config.get("hide_titles", False)))

    @staticmethod
    def _row_status(row: dict[str, Any]) -> str:
        probe = row.get("last_probe") or {}
        if row.get("probe_running"):
            return "PROBING"
        if row.get("alert"):
            if has_passive_alert(probe):
                return passive_alert_label(probe).upper()
            if row.get("hard_evidence"):
                return "PASSIVE ALERT"
            return "DOWNGRADE"
        if row.get("suspicious"):
            return "SUSPICIOUS"
        if row.get("halted"):
            return "HALTED"
        if row.get("unverified"):
            return "UNVERIFIED"
        if row.get("upgraded"):
            return "UPGRADED"
        if row.get("due"):
            return "DUE"
        if probe.get("verdict") == "MISMATCH" and probe.get("direction") == "upgrade":
            return "UPGRADED"
        if probe.get("status") == "failed" or probe.get("verdict") in ("INVALID", "FAILED"):
            return "FAILED"
        if probe.get("fingerprint_resolution") == "overlap" or fingerprint_verdict(probe) == "AMBIGUOUS":
            return "AMBIGUOUS"
        return str(fingerprint_verdict(probe) or ("ACTIVE" if row.get("active") else "QUIET"))

    def _apply_snapshot(self, snapshot: dict[str, Any]) -> None:
        self.snapshot = snapshot
        self._load_settings(snapshot)
        overall = snapshot.get("overall") or {}
        status_text = str(overall.get("message") or overall.get("status") or "Status loaded")
        self.status_var.set(status_text)
        if self._tray is not None:
            try:
                self._tray.set_status(status_text)
                notices, signature, verdict_id = tray_notifications(
                    snapshot, self._last_notification_signature, self._last_verdict_id)
                for title, message in notices:
                    self._tray.notify(title, message)
                self._last_notification_signature = signature
                self._last_verdict_id = verdict_id
            except Exception:
                pass

        rows: list[dict[str, Any]] = [{"kind": "fresh", "id": None, "title": "Fresh session",
                                       "model": snapshot.get("default_model"), "effort": snapshot.get("default_effort"),
                                       "last_probe": snapshot.get("global_probe"), "alert": snapshot.get("global_alert"),
                                       "probe_running": snapshot.get("global_running"), "report_text": snapshot.get("global_report_text")}]
        for thread in snapshot.get("threads") or []:
            row = dict(thread)
            row["kind"] = "thread"
            rows.append(row)
        self.rows = rows
        self.session_list.delete(0, "end")
        for row in rows:
            if row.get("kind") == "fresh":
                label = f"[FRESH {self._row_status(row)}] Fresh session"
            else:
                title = row.get("title") or row.get("id") or "Session"
                label = f"[{self._row_status(row)}] {title}"
            self.session_list.insert("end", label)
        target = next((i for i, row in enumerate(rows) if (row.get("id") or "__fresh__") == self._selected_key), 0)
        if rows:
            self.session_list.selection_clear(0, "end")
            self.session_list.selection_set(target)
            self.session_list.activate(target)
            self.session_list.see(target)
            self._selected_key = rows[target].get("id") or "__fresh__"
            self._render_details(rows[target])
        self._update_action_states()

    def _poll_events(self) -> None:
        if self._closing:
            return
        while True:
            try:
                result = self.controller.events.get_nowait()
            except queue.Empty:
                break
            action = str(result.get("action") or "operation")
            if self._busy_action == action:
                self._busy_action = None
            if result.get("ok"):
                if action == "snapshot":
                    self._last_operation = ""
                    self._operation_var.set("Snapshot refreshed")
                else:
                    self._last_operation = str(result.get("output") or f"{action.capitalize()} completed.")
                    self._operation_var.set(f"{action.capitalize()} completed")
                if isinstance(result.get("snapshot"), dict):
                    self._apply_snapshot(result["snapshot"])
                elif action == "doctor":
                    self._render_details()
            else:
                self._last_operation = f"ERROR: {result.get('error') or 'Unknown backend error'}"
                self._operation_var.set(f"{action.capitalize()} failed")
                self.status_var.set(self._last_operation)
                self._render_details()
                if self.smoke_test:
                    self.exit_code = 1
                    print(self._last_operation, file=sys.stderr)
            self._update_action_states()
            if self.smoke_test and action == "snapshot":
                self.root.after(50, self._shutdown)

        while True:
            try:
                action = self._tray_events.get_nowait()
            except queue.Empty:
                break
            if action == "show":
                self.root.deiconify()
                self.root.lift()
                try:
                    self.root.focus_force()
                except tk.TclError:
                    pass
            elif action == "quit":
                self._shutdown()
        self.root.after(80, self._poll_events)

    def _check_tray_startup(self) -> None:
        if self._closing or self._tray is None:
            return
        if getattr(self._tray, "ready", False):
            return
        if getattr(self._tray, "failed", False):
            self._tray = None
            return
        self.root.after(250, self._check_tray_startup)

    def _on_close(self) -> None:
        if self._tray is not None and getattr(self._tray, "ready", False):
            self.root.withdraw()
            config = (self.snapshot or {}).get("config") or {}
            if config.get("notify", True):
                try:
                    self._tray.notify("Panel is still running", "Use the notification area icon to reopen or quit.")
                except Exception:
                    pass
        else:
            self._shutdown()

    def _shutdown(self) -> None:
        if self._closing:
            return
        self._closing = True
        self.controller.shutdown()
        if self._tray is not None:
            try:
                self._tray.stop()
            except Exception:
                pass
        self.backend.close()
        try:
            self.root.destroy()
        except tk.TclError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Windows desktop panel for is-gpt-nerfed")
    parser.add_argument("--demo", action="store_true", help="load synthetic data with isolated temporary state")
    parser.add_argument("--smoke-test", action="store_true", help="build the demo UI, load data, then exit")
    args = parser.parse_args(argv)
    demo = bool(args.demo or args.smoke_test)
    set_windows_dpi_awareness()
    backend = BackendClient(demo=demo)
    try:
        root = tk.Tk()
    except Exception as exc:
        backend.close()
        print(f"Unable to start the Windows panel UI: {exc}", file=sys.stderr)
        return 1
    if args.smoke_test:
        root.withdraw()
    try:
        app = PanelApp(root, backend, smoke_test=args.smoke_test)
    except Exception as exc:
        backend.close()
        try:
            root.destroy()
        except tk.TclError:
            pass
        print(f"Unable to build the Windows panel UI: {exc}", file=sys.stderr)
        return 1
    try:
        root.mainloop()
    finally:
        if not app._closing:
            app._shutdown()
    return app.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
