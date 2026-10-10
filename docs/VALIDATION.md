# Windows validation record

## Astra / Sol 6.1 ambiguity — 0.5.3-port.5, 2026-10-10

Source: the user's Sol 6.1 → Astra observation and
[upstream Issue #15](https://github.com/kiyoakii/is-gpt-nerfed/issues/15).
Design and limits: [ADR 0004](adr/0004-conservative-fingerprint-resolution.md) and
[reliability analysis](FINGERPRINT_RELIABILITY.zh-CN.md).
The three implementation/research tracks used **GPT-6.1 Sol xhigh**, without redelegation.
The parent reviewed backend/UI diffs, evidence provenance, results, and three actual synthetic screenshots.

### Local acceptance

`python -X utf8 -m unittest discover -s tests -v`: **125 tests passed in 186.698 seconds**,
exit 0 on native Windows / Python 3.11.2. The port.5 development portable ZIP was built before
the suite so its packaged backend, compiled EXE/DLL and private runtime were exercised.
Formal release artifacts are rebuilt from clean committed HEAD, not the dirty development snapshot.

- Seven new backend regressions cover exact `6.1` model normalization, neutral overlap for Astra/Sol,
  unrelated listed/unlisted behavior, independent fingerprint/passive verdicts, reasons/timestamps,
  absence of ambiguity notifications/halt, historical read-time projection without file changes,
  and CLI/report provenance. Existing fake-fork/self/snapshot expectations now use the conservative rule.
- Five new offline research tests cover grouping, incomplete/unusable groups, supplied response hashes,
  compatibility with the unchanged production scorer, feature pair accounting and bank preservation.
- WPF synthetic assertions actually construct the details view with a Sol declaration, neutral overlap,
  labelled raw scores and a timed effort-change finding together. Tk report/notification regressions,
  native interaction/lifecycle, narrow 150% DPI, compiled metadata and portable-runtime tests passed.
  Actual main/detail/settings renders were visually reviewed and saved in the existing documentation paths.
- The offline benchmark's AST extraction was updated for the independent verdict helpers; its quick
  JSON run succeeds without real inference. Three quick samples are a compatibility smoke, not a
  replacement for port.4's repeated timing study.
- Independently verified all **15** retained upstream file hashes and all **four** research reports'
  input/bank/scorer hashes. Git attributes preserve the hash-pinned external originals byte-for-byte
  on Windows, Linux and macOS checkouts; the original MIT notice is retained.

The fixed public candidate's original validator was inspected and actually run with an already
available Python/NumPy runtime: **151.234 seconds, exit 0, integrity PASS**. It builds only an
in-memory research candidate. Sol three-answer CV is 6/12 and holdout 1/3; Astra CV decreases
from 12/12 to 9/12 when that candidate is added. Commands, original stdout and provenance are in
[the research appendix](research/gpt61-sol/README.md).

Exactly **two** user-authorized Common test chats were created, requested Sol high and Astra high,
with three numeric-only turns each. Six valid answers and both three-answer groups map to Astra
in both existing banks. Only those two chats' model/effort metadata was checked; both were archived
after collection. This is an exploratory sample, with shared per-chat history and no independent
holdout, not a production enrollment or serving-weight authentication. Separate private historical
inspection is summarized anonymously in the reliability report; private sessions are not published.

The production bank SHA-256 remains
`1c2cb74d372f9f0f30d0dabbb7b7a838660d2f769a88d0c8489e4c662e088c21`.
Numerical scorer, prompts, inference defaults and passive scan rules were not changed.
Real-account schedules, settings, hook trust and installed plugin files were not modified by validation.
Old probe/ledger evidence is preserved; `AMBIGUOUS` is a deliberate loss of claimed specificity,
not a newly proven Sol classifier.

Formal portable/source checksums, clean source commit, extracted-package acceptance and exact-commit
four-job CI are recorded with the
[port.5 release](https://github.com/vvcchh0/is-gpt-nerfed/releases/tag/windows-v0.5.3-port.5).
Historical records below retain their original scope and original numerical results.

## Internal-session filtering and performance analysis — 0.5.3-port.4, 2026-10-10

Source: the user's request to optimize Guardian review filtering and determine whether fingerprint
latency comes from local computation or the conversational probe. Implementation, benchmark and
release integration used **GPT-6.1 Sol, xhigh**, without redelegation. The parent reviewed the final
diff, regression cases, benchmark method and anonymous historical timing aggregates.
Behavior and rationale: [session filtering](SESSION_FILTERING.zh-CN.md).
Measurements, reproduction and statistical limits: [performance analysis](PERFORMANCE.zh-CN.md).

### Local acceptance

`python -X utf8 -m unittest discover -s tests -v`: **109 tests passed in 104.703 seconds**,
exit 0 on native Windows/Python 3.11.2. The port.4 development portable ZIP was built before the
run, so the compiled-package test exercised the updated archive rather than the earlier release.
Development archives are acceptance snapshots; formal releases are rebuilt from clean committed HEAD.

- Fifteen new isolated source-classification regressions cover old/new source spellings, structured
  metadata, old schemas, same-named main sessions, user forks, stale ledgers, snapshot merging,
  hook/tick/worker/manual probe eligibility and audit inclusion. A fixture with 151 newer internal
  records still returns the requested 40 main sessions using one read connection.
- Existing Python/JavaScript numerical parity, backend reliability, launchers, WPF/Tk and portable
  tests passed. The compiled EXE/DLL reports port.4 / assembly `0.5.3.4`; the package exercises its
  private runtime, offline 18-row selftest, synthetic UI, installer/wrapper resolution and Unicode paths.
- A single real-database **read-only** compatibility check, with detector state isolated in a temporary
  directory, returned 40 old-list entries including 34 Guardian records, versus 7 main entries and
  zero recognized internal entries after filtering. The new query took 16.35 ms and produced no error
  log. This is one snapshot, not a general performance benchmark.
- The new standard-library benchmark ran successfully with the public fixture; its quick JSON
  interface was also parsed and checked. Three-answer attribution plus verdict took a median 11.7 ms.
  Existing local records, summarized without session identifiers or answers, place the median completed
  three-fork probe at 189.7 seconds. The performance document keeps the two measurement scopes distinct.

The ModelTrace bank digest remains
`1c2cb74d372f9f0f30d0dabbb7b7a838660d2f769a88d0c8489e4c662e088c21`.
Prompts, numerical scorer, app-server protocol and default probe settings were not changed.
No new real inference, real-account installation or hook-trust changes were performed.

Formal portable/source checksums, source commit and exact-commit cross-platform CI are recorded with
the [port.4 release](https://github.com/vvcchh0/is-gpt-nerfed/releases/tag/windows-v0.5.3-port.4).
Historical records below retain their original validation scope.

## Compiled distribution and hook reliability — 0.5.3-port.3, 2026-10-09

Scope: [ADR 0003](adr/0003-compiled-windows-distribution.md). Both implementation tracks
used **GPT-6.1 Sol, xhigh** without redelegation. The parent reviewed the final source,
compiled synthetic screenshot, unchanged ModelTrace digest and complete regression results.

### Local acceptance

`python -X utf8 -m unittest discover -s tests -v`: **94 tests passed in 95.085 seconds**,
exit 0 on Windows/Python 3.11.2. The portable development archive was rebuilt from the final
frontend/backend implementation before this run. Subsequent package acceptance adds the existing
18-row reference fixture and tests Windows long/8.3 path identity using the actual file. The
compiled package contract is rechecked after those adjustments, and the release records exact-HEAD
CI results. Development archives are test snapshots, not publishable release artifacts.

New coverage includes:

- Four compiled frontend/package tests: actual x64 GUI PE metadata, DLL version `0.5.3.3`,
  embedded XAML/three faces, smoke and interaction self-test, synthetic render, direct CMD
  waiting/exit codes, and app-local Python with no Python on PATH or `NERFED_PYTHON` override.
  The compiled app is exercised without `windows/` or `macos/` source resources.
- The portable interpreter's real CLI/synthetic snapshot and hook-command generation;
  an explicitly fake setup backend verifies installer and helper interpreter/argument routing
  in a path with Chinese characters and spaces. No real account is used.
- Four launcher tests, including a forced CP936 caller. Chinese JSON values remain correct
  inside the PowerShell pipeline and the original console encoding is restored after the call.
  This catches decoding corruption that a byte round trip alone can hide.
- Thirteen reliability/diagnostic tests. A real `CreateFileW` handle without delete sharing
  reproduces `PermissionError`/WinError 5 on replacement; release after 25 ms allows a later
  attempt to succeed. Persistent contention and a read-only target retain the old JSON and
  clean the temporary file. The separate persistent-contention observation failed in 156 ms.
  Retry waits are capped at 150 ms per write and 250 ms cumulatively per hook; unrelated and
  non-Windows failures are not retried. These are wait budgets, not a whole-hook timing guarantee.
- Unique temporary files under same-process concurrent writes, serialization-failure cleanup,
  fail-open hook handling, safe error metadata without input/locals/exception text, and honest
  doctor warning/failure summaries. Historical errors remain visible; later activity is not
  interpreted as proof of recovery.

The observed user log contained one old error at `2026-10-09T11:18:33Z` and subsequent hook
activity. Its old exception representation lacks the failed path and stack, so this work does
**not** claim the reproduced sharing conflict was that historical error's original cause.
No log was erased, ACL changed, or existing process stopped to hide the symptom.

`git diff --check` passed. The bank SHA-256 is still
`1c2cb74d372f9f0f30d0dabbb7b7a838660d2f769a88d0c8489e4c662e088c21`.
Prompts, scoring thresholds and ledger formats remain unchanged.

### Formal distribution evidence

Formal artifacts are rebuilt from clean committed HEAD with `tools/build-windows.ps1`.
The [port.3 release](https://github.com/vvcchh0/is-gpt-nerfed/releases/tag/windows-v0.5.3-port.3)
records the exact commit, source/portable checksums, four-platform CI and extracted-archive
acceptance results. Its build manifest includes each distributed file's SHA-256, source state,
the official CPython 3.13.16 archive URL/digest and retained `runtime/LICENSE.txt`.
Development archives marked dirty are not used as release assets.

### Limits

Checks use isolated homes and synthetic/fake inference. The user's installed copy, settings,
hook trust and running Tk/Codex processes are not updated by this validation. No real fingerprint
inference or current-account attribution calibration is performed. Physical monitor DPI changes,
ARM64, accessibility and server-side cancellation remain uncertified. The portable x64 EXE/DLL
is unsigned, requires .NET Framework 4.8, and is not an MSI or auto-start registration.
Python modules intentionally remain auditable source beside their private interpreter.

## Native WPF update — 0.5.3-port.2, 2026-10-09

Scope: [ADR 0002](adr/0002-native-windows-ui.md), based on upstream screenshots and macOS
sources. Implementation was delegated to **GPT-6.1 Sol, xhigh**; the parent reviewed the
transport, lifecycle, UI semantics and synthetic screenshots, then ran the complete suite.
The original Tk implementation remains available through `launch.cmd --legacy-tk`.

### Local acceptance

`python -X utf8 -m unittest discover -s tests -v`: **76 tests passed in 73.183 seconds**,
exit 0 on the native Windows host with Python 3.11.2 and Windows PowerShell 5.1/.NET Framework WPF.
This includes the existing statistical/backend/Tk tests, three launcher integrations and
two new native tests. All new UI verification uses isolated homes and synthetic/fake inference.

The native `--smoke-test` and `--self-test` both exited 0. The interaction self-test exercises:

- Session detection, retry using the same worker entry point, fresh model/effort overrides,
  omitted blank overrides, and changed-setting persistence.
- Refresh and diagnostics while a fake probe waits; settings drafts and fresh-input keyboard
  focus survive snapshot refresh. At the actual minimum 380 × 560 window size, scrolling
  brings the Save button fully into the viewport.
- Separate recent failure and last valid verdict; scheduler output does not enter the report.
  Demo cannot run inference/scheduling, and heartbeat/tick requests are throttled independently.
- Actual `NotifyIcon` creation, visibility and disposal, synthetic-window hide/restore,
  shutdown rejection of new work and suppression of late-callback refreshes.
- Real `Process` transport against a temporary dummy Python backend: Unicode, spaces, quotes
  and trailing backslashes round-trip; concurrent large stdout/stderr drain; a diagnostic
  request completes while a config command waits; shutdown stops only owned processes and
  prevents the next config command from starting.
- Caller homes remain untouched; the self-test's unique temporary root is removed after exit.
  Recursive cleanup verifies the final absolute parent/name and rejects a reparse-point root.

Five synthetic exports were generated successfully and visually reviewed: main, detail, settings,
380-pixel-wide main and settings at 150% render scale. Text wraps without horizontal overflow;
the footer remains visible and long settings scroll. Published examples:
[main](windows-native-main.png), [detail](windows-native-detail.png), [settings](windows-native-settings.png).
The user's screenshot and real session titles are not included in the repository.

`git diff --check` passed. This update does not change `plugin/`, `macos/`, `LICENSE` or `NOTICE.md`.
The bank SHA-256 remains `1c2cb74d372f9f0f30d0dabbb7b7a838660d2f769a88d0c8489e4c662e088c21`,
matching the retained provenance. Sound remains owned by the existing backend, avoiding duplicate
frontend sounds. Detection thresholds, prompts, scoring and ledger formats remain the same.
The final bootstrap-error-feedback edit separately passed PowerShell parsing and isolated native
smoke; its no-argument startup error dialog was reviewed in source rather than forced interactively.

### Distribution and remote evidence

The source archive and exact-commit CI results for this update are recorded with their checksum in
the [0.5.3-port.2 release](https://github.com/vvcchh0/is-gpt-nerfed/releases/tag/windows-v0.5.3-port.2).
The release retains upstream ancestry and attribution. Build from a clean commit with
`tools/build-windows.ps1`; archive entry-point verification uses a temporary path with Chinese
characters and spaces, isolated homes and no real inference.

### Current limits

No real fingerprint inference, real-account panel startup, new hook trust or installation change
was performed for this UI update. No existing Tk or Codex process was stopped. The earlier port's
live installation/app-server checks below are historical evidence, not repeated UI-update tests.
The 150% export uses WPF `RenderTargetBitmap`; it does not certify physical monitor DPI changes,
multiple monitors, Windows ARM64, screen readers or notification delivery under all Windows policies.
There is still no signed standalone EXE, Notification Center toast integration or automatic startup.
Active server-side inference cancellation remains unverified.

## Initial Windows port — 0.5.3-port.1

Date: 2026-10-08 to 2026-10-09. Baseline: upstream 0.5.3,
`ff0d7c0c8fdc8713273b6570b1ada1838eaad84c`.
Scope and acceptance: [ADR 0001](adr/0001-windows-port.md). Source and algorithm:
[Chinese analysis](ANALYSIS.zh-CN.md). Original author: [NOTICE](../NOTICE.md).

### Native environment

Windows host, Python 3.11, Tk 8.6, Node.js available for JS parity,
Codex desktop bundled CLI `0.162.0-alpha.2`. No WSL or Git Bash was used to run the detector.
All installation tests use temporary `CODEX_HOME` / `NERFED_HOME`; the user's existing
Codex configuration, hook trust, credentials and detector ledger are not modified.

### Acceptance evidence

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

### Remote acceptance

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

### Limits of this validation

No real fingerprint inference was performed and no attribution accuracy was measured on the user's
account. Match/mismatch, tools/refusals, busy turns and retry paths are tested against the offline fake
app-server. The live checks validate transport, current database compatibility and installation,
not that probing and the desktop connection have identical server routing.

Active inference cancellation after a forced worker shutdown was not exercised; only an idle real
app-server's exit was verified. Notification Center toast integration, signed EXE packaging,
automatic startup, Windows ARM64, and additional Python/Windows versions are not locally certified.
The remote matrix evidence above is separate from the local, real-Codex and manual visual checks.
