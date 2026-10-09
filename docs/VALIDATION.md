# Windows validation record

Date: 2026-10-08 to 2026-10-09. Baseline: upstream 0.5.3,
`ff0d7c0c8fdc8713273b6570b1ada1838eaad84c`.
Scope and acceptance: [ADR 0001](adr/0001-windows-port.md). Source and algorithm:
[Chinese analysis](ANALYSIS.zh-CN.md). Original author: [NOTICE](../NOTICE.md).

## Native environment

Windows host, Python 3.11, Tk 8.6, Node.js available for JS parity,
Codex desktop bundled CLI `0.162.0-alpha.2`. No WSL or Git Bash was used to run the detector.
All installation tests use temporary `CODEX_HOME` / `NERFED_HOME`; the user's existing
Codex configuration, hook trust, credentials and detector ledger are not modified.

## Acceptance evidence

`python -X utf8 -m unittest discover -s tests -v`: **73 tests passed** on the native
Windows host. The suite includes the original backend and statistical parity tests,
10 Windows backend regressions, two launcher integrations, and 10 panel tests.

Completed native checks:

- Python/JavaScript ModelTrace parity: `python -X utf8 -m unittest discover -s tests -p test_parity.py -v`,
  both tests passed. Canonical and working bank SHA-256 matches the retained provenance.
- `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\bin\nerfed.ps1 selftest`: PASS,
  including 18/18 provided reference outputs. This is fixture validation, not new real-world calibration.
- PowerShell/cmd launchers: two integration tests passed, including a temporary checkout with Chinese
  characters and spaces, argument forwarding and parsing all PowerShell entry points.
- Windows panel: native Tk demo, pythonw panel/backend execution, queue/controller behavior,
  shutdown prevention of new children, notification preferences, and real Win32 tray add/update/notify/delete.
  The demo window was also inspected at 1120 x 780: status labels, probe buttons, fresh-model/effort
  inputs and Refresh/Doctor are visible. The demo exited normally and removed its temporary state.
- Actual local Codex app-server `initialize` + `hooks/list`: succeeded, zero inference requests.
- Actual local Codex SQLite + `build_snapshot`: 29 recent sessions read, no database errors;
  detector writes isolated in a temporary directory. Only counts were emitted in the evidence output.
- Actual local Codex `thread/read` and ephemeral `thread/fork` from a persisted session:
  succeeded, the temporary fork had no rollout path, zero inference requests. The current
  working session was excluded and the original thread was not modified.
- Actual `install.ps1 -TrustHooks -CodexBin <desktop CLI>` in temporary Chinese/space paths:
  exit 0, doctor passed (including bank checksum), and **5/5 hooks trusted**. All five
  generated PowerShell hooks were executed with synthetic input and exited 0; the ledger
  recorded SessionStart, UserPromptSubmit, PreToolUse, Stop, and SessionEnd. The Stop check
  deliberately supplied a stale plugin path and confirmed the stable-copy fallback.
  A separate real-entrypoint timing check took 0.750-0.813 seconds per event on this host,
  below each retained manifest timeout (including SessionEnd's three-second limit); ledger events
  confirmed execution. This does not guarantee timing on every machine or under lock contention.
- Actual `uninstall.ps1 -KeepPath`: exit 0; parsed TOML confirmed the plugin was disabled
  and the ledger was retained. `uninstall.ps1 -KeepPath -Purge`: exit 0 and the ledger
  directory stayed absent. These checks made zero inference requests and did not change user PATH.
- Forced termination of a private Python worker that owned an initialized, idle Codex app-server:
  the child exited within the five-second observation window when its stdin pipe closed.
  The process handle referred only to the newly created private server; no existing Codex process was stopped.

The source ZIP was built with `tools/build-windows.ps1` from a clean committed tree, then extracted
into a temporary Chinese/space path. Its checksum, original bank digest, licenses and entry points
were verified. The extracted PowerShell `--version`, `selftest` (18/18 reference outputs), and
`launch.ps1 --smoke-test` each exited 0 with isolated state and zero inference requests.

## Remote acceptance

[GitHub Actions run 37867014500](https://github.com/vvcchh0/is-gpt-nerfed/actions/runs/37867014500)
tested implementation commit `d224996e1f41888ba23bf170b22eeaf3af416d21` successfully:

| Platform | Python | Result |
| --- | --- | --- |
| Windows | 3.10 | 73 tests passed, plus Windows GUI smoke |
| Windows | 3.11 | 73 tests passed, plus Windows GUI smoke |
| Ubuntu | 3.11 | 59 passed, 14 platform/display checks skipped |
| macOS | 3.11 | 59 passed, 14 platform/display checks skipped |

Python 3.10 uses `tomli` only for independent TOML parsing in a test; the runtime remains stdlib-only.
Ubuntu/macOS runs validate shared backend compatibility and do not certify the Windows UI there.

## Limits of this validation

No real fingerprint inference was performed and no attribution accuracy was measured on the user's
account. Match/mismatch, tools/refusals, busy turns and retry paths are tested against the offline fake
app-server. The live checks validate transport, current database compatibility and installation,
not that probing and the desktop connection have identical server routing.

Active inference cancellation after a forced worker shutdown was not exercised; only an idle real
app-server's exit was verified. Notification Center toast integration, signed EXE packaging,
automatic startup, Windows ARM64, and additional Python/Windows versions are not locally certified.
The remote matrix evidence above is separate from the local, real-Codex and manual visual checks.
