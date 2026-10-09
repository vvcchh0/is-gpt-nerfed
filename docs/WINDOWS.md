# Windows port

Windows 10/11 desktop, Windows PowerShell 5.1 with the OS's .NET Framework WPF, Python 3.10+
(recommended: 3.11+), and a signed-in Codex desktop app or CLI with plugin hooks and the
experimental app-server protocol are required. The default panel is native WPF; Tcl/Tk is
only required for the optional legacy panel. No .NET SDK, pip packages, administrator privileges,
WSL or Git Bash are needed at runtime.

Original author and licenses: [NOTICE.md](../NOTICE.md). 中文源码分析：[ANALYSIS.zh-CN.md](ANALYSIS.zh-CN.md).
Interaction order: [中文操作指南](INTERACTION.zh-CN.md).
Design: [ADR 0001](adr/0001-windows-port.md), [native UI decision](adr/0002-native-windows-ui.md).
Validation evidence: [VALIDATION.md](VALIDATION.md).

## Install and open

Extract or clone the `windows` branch, then run PowerShell from its root:

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

`NERFED_PYTHON` can point to a specific `python.exe`. The installer resolves a real interpreter,
skipping Store aliases. Hooks remember that interpreter, so reinstall if it is moved or removed.
The previous Tk app remains available with `launch.cmd --legacy-tk` or directly with
`python -X utf8 windows/app.py`.
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
.\launch.cmd --legacy-tk --demo
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

The macOS SwiftUI app, DMG installer and self-updater remain upstream features. Windows uses a
native WPF desktop/tray panel, an optional legacy Tk panel, and a Python-dependent source ZIP.
The original images and upstream attribution are retained. Windows does not download or install
macOS releases; update by pulling `windows` and rerunning the installer. There is no automatic startup
registration, signed standalone EXE, or Windows Notification Center toast integration in this version.
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

## Development and packaging

The Python 3.10 test suite also needs `python -m pip install tomli` for independent TOML
parsing in the installation regression. Python 3.11+ includes `tomllib`; the app itself needs neither package.

```powershell
python -X utf8 -m unittest discover -s tests -v
.\launch.cmd --smoke-test
python -X utf8 windows/app.py --smoke-test  # optional legacy panel
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\build-windows.ps1
```

The build produces a source ZIP plus a SHA-256 file from the committed HEAD, with the licenses,
plugin, GUI and installers. Python is a prerequisite, not embedded in that ZIP.
