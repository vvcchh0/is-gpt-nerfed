# Windows port

The compiled portable release targets Windows 10/11 **x64**, .NET Framework 4.8 and a signed-in
Codex desktop app or CLI with plugin hooks and the experimental app-server protocol. It contains
`IsGPTNerfed.exe`, `IsGPTNerfed.Panel.dll` with embedded UI resources, and a private Python runtime.
Ordinary GUI startup needs no external Python, compiler, PowerShell host, pip packages, WSL or
administrator privileges. Windows PowerShell 5.1 is still used by installation/CLI helpers and hooks.

Source-mode development needs Python 3.10+ (recommended: 3.11+) and Windows PowerShell 5.1/WPF.
Tcl/Tk is required only for the optional legacy panel; it is not in the bundled Python runtime.

Original author and licenses: [NOTICE.md](../NOTICE.md). 中文源码分析：[ANALYSIS.zh-CN.md](ANALYSIS.zh-CN.md).
Interaction order: [中文操作指南](INTERACTION.zh-CN.md).
Session visibility and eligibility: [会话过滤规则](SESSION_FILTERING.zh-CN.md).
Offline benchmarks and historical probe timing: [性能分析](PERFORMANCE.zh-CN.md).
Design: [ADR 0001](adr/0001-windows-port.md), [native UI decision](adr/0002-native-windows-ui.md),
[compiled distribution](adr/0003-compiled-windows-distribution.md).
Validation evidence: [VALIDATION.md](VALIDATION.md).

## Install and open

For normal use, download the **win-x64 ZIP** from the
[Windows release](https://github.com/vvcchh0/is-gpt-nerfed/releases/tag/windows-v0.5.3-port.4),
extract the whole directory, and double-click `IsGPTNerfed.exe`. Keep the DLL, `runtime/` and
`plugin/` alongside it. For first installation run `install.ps1` in that directory, review the
hook commands and trust them, then restart Codex. Installation and probing remain explicit actions.

The source package or a clone is the developer option. From its root:

```powershell
git clone --branch windows https://github.com/vvcchh0/is-gpt-nerfed.git if-gpt-nerfed-main
cd if-gpt-nerfed-main
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
.\launch.cmd
```

The installer shows the hook commands before offering to trust them. Trust is required for
automatic monitoring; installation alone does not make hooks run. For a reviewed unattended
installation use `-TrustHooks`; to defer trust use `-NoTrust`, then `nerfed hooks trust` or Codex `/hooks`.
Restart Codex after installation or reinstalling so it reloads the definitions.

```powershell
# Explicit Codex executable, optional user PATH entry, and open the panel:
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -TrustHooks -AddToPath -Launch -CodexBin 'C:\path with spaces\codex.exe'
```

The portable app and helpers prefer their local `runtime/python.exe`. In source mode,
`NERFED_PYTHON` can point to a specific `python.exe`; discovery skips Store aliases. Hooks remember
the selected interpreter, so keep the extracted directory and reinstall if it is moved or removed.
The previous Tk app remains available in the source package with `launch.cmd --legacy-tk` or
`python -X utf8 windows/app.py`, using an external Tcl/Tk-enabled Python.
Native `codex.exe` and npm `codex.cmd` shims are supported. The `.cmd` bridge rejects embedded
quotes, `%`, `!` and newlines rather than letting cmd.exe reinterpret them; use a native executable
if your shim path or arguments contain these characters.

## Desktop and terminal

The native panel follows upstream's status hero, semantic session rows, expanded attribution/history,
fresh-session section and separate settings page. Chinese UI labels preserve model IDs, raw verdict
codes, stored records and CLI contracts. Click a session title to expand evidence; use its probe/retry
button for inference. Fresh model/effort overrides affect only the next manual fresh-session probe.
Refresh, diagnostics and settings navigation remain available while a probe runs.

Settings use an explicit save action. Session frequency and fresh-session frequency are distinct;
reminder mode controls session scheduling, not the fresh heartbeat. Use manual for both frequencies
to avoid later automatic probes. Enabling a timed fresh heartbeat with no prior sample for the current
account can make it due immediately. Closing the window keeps monitoring through the system tray;
use Quit to exit. If the tray is unavailable, the window remains usable. Demo uses synthetic data:

```powershell
.\launch.cmd --demo
.\launch.cmd --legacy-tk --demo  # source package with an external Tcl/Tk-enabled Python
.\bin\nerfed.cmd --version
.\bin\nerfed.cmd doctor --live
.\bin\nerfed.cmd selftest
.\bin\nerfed.cmd probe now --thread <session-id>
.\bin\nerfed.cmd probe fresh --model gpt-6-astra --effort medium
.\bin\nerfed.cmd report
.\bin\nerfed.cmd log --since 2h
.\bin\nerfed.cmd config set frequency manual
.\bin\nerfed.cmd config set mode nudge
```

Use the GUI or the Windows numbered terminal picker; the original Unix terminal picker is retained
for macOS/Linux. If `nerfed` is not on PATH, use the explicit `.\bin\nerfed.cmd` path.

Default monitoring scans logs after each turn. Its 30-minute probe interval uses elapsed wall-clock
time since the previous probe/nudge or session creation, checked while the session has recent hook activity.
While open, the native panel reads a snapshot every eight seconds. It checks eligible session
scheduling at most once per minute and retries a due fresh heartbeat at most once per five minutes.
Active probes use your Codex quota:
normally three answers, with bounded retries on transport/timeouts. Set `frequency=manual` and
`fresh_frequency=manual` for manual probes only, or `mode=nudge` for reminders.

## State and uninstall

The existing state format is retained under `%USERPROFILE%\.codex\is-gpt-nerfed`.
`CODEX_HOME` and `NERFED_HOME` override those roots. Installation produces a Windows-only local
marketplace and hook manifest under the ledger, with a stable plugin copy for hooks; the tracked
source manifest stays compatible with Unix. No Windows Developer Mode or symbolic links are required.
This is the same plugin identity as upstream, so it replaces an existing installation of that identity.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\uninstall.ps1
# Also remove probe history and settings (explicitly destructive):
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\uninstall.ps1 -Purge
```

Quit the panel and let any already scheduled probes finish first. The default uninstall preserves
the ledger. Restart Codex to unload hooks.

## Limits and privacy

The macOS SwiftUI app, DMG installer and self-updater remain upstream features. Windows provides a
compiled EXE/DLL portable ZIP with a private runtime, plus a separate source ZIP and optional Tk panel.
The original images and upstream attribution are retained. Windows does not download or install
macOS releases; update by pulling `windows` and rerunning the installer. There is no automatic startup
registration, signed executable, MSI installer or Windows Notification Center toast integration in this version.
Tray balloon delivery depends on Windows notification settings; the ledger remains the authoritative record.
Without the panel running, notification events remain in the local log and session hook messages.

Passive checks cost no inference tokens. Active probes send challenges, and for fork probes inherited
session context, through normal Codex inference under your account. They are not an offline test.
The detector does not upload records to an additional analytics service. `auth.json` is read only to
derive an account hash/masked label; no credentials are written into the repository.

Closed-set fingerprint scores are calibrated similarities among models in the bundled bank. They are
not proof of the exact server weights, capability loss or billing fraud. A model absent from the bank
can resemble an enrolled model; prompt, reasoning effort, serving changes and context can shift its
distribution. A log records the requested model, not an independently verified serving identity.
See the Chinese analysis for the statistical method and the distinction between signals and conclusions.

## Doctor and historical permission errors

Doctor distinguishes hard failed checks from warnings. A historical `hook crashed: PermissionError`
entry does not by itself establish a current installation failure. Later hook activity is useful
context, not proof that the original cause has been fixed. Old errors remain in `errors.log`; this
release does not erase them to make diagnostics appear clean.

The old logger stored only an exception representation, so a record without filename or traceback
cannot identify the failed resource. New hook diagnostics record safe event/error/file/frame
metadata, without hook input, session text or credentials. If it recurs, use those fields to locate
the affected file before changing permissions. Hooks remain fail-open so an internal monitor error
does not block the user's Codex turn.

Windows may briefly deny atomic replacement while another process holds the destination open.
The shared JSON writer now retries that class of failure within a short budget and preserves the
old JSON on persistent failure. This addresses a reproduced failure mode; it does not retroactively
prove the cause of any old log entry. No blanket administrator/ACL change is part of the fix.

## Development and packaging

The Python 3.10 test suite also needs `python -m pip install tomli` for independent TOML
parsing in the installation regression. Python 3.11+ includes `tomllib`; the app itself needs neither package.

```powershell
python -X utf8 -m unittest discover -s tests -v
.\launch.cmd --smoke-test
python -X utf8 windows/app.py --smoke-test  # optional legacy panel
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\build-windows.ps1
```

The release build produces separate source and win-x64 portable ZIPs plus SHA-256 files from clean
committed HEAD. The portable archive contains compiled EXE/DLL resources, the plugin, helpers,
licenses and pinned CPython runtime; the source archive retains the auditable originals. Downloads
are build-time only and must match the fixed official runtime hash. See ADR 0003 for provenance.
