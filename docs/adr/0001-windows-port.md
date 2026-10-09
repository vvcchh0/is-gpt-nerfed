# ADR 0001: retain the detection backend and add native Windows integration

Date: 2026-10-08
Status: Accepted for the first Windows port
Source: user request to analyze `is-gpt-nerfed-main`, deliver `if-gpt-nerfed-main` on Windows,
use Git, publish a fork/branch and credit the original author.

## Context

Upstream 0.5.3 already has a standard-library Python detector and a JSON snapshot API used by a
SwiftUI menu-bar app. Windows cannot import `fcntl`, execute Unix shebangs or the manifest's `sh`
commands natively, or build that SwiftUI application. Windows also gives `os.kill(pid, 0)` different
semantics, requiring a non-destructive process check. Platform-specific updates target `.app` bundles.

## Decision

Keep the bank, prompts, numerical scorer, verdict gates, ledger and JSON-RPC protocol shared.
Isolate locks, process discovery/launch and process lifetime in a platform support module. Add a
Windows-generated marketplace manifest rather than replacing the Unix source hook definitions.
Use the installer's resolved Python interpreter and encoded PowerShell hook entry points; every
runtime failure must leave the Codex hook with exit 0. Keep stable plugin copies without symlinks.

Use Tkinter and ctypes Win32 tray integration for the Windows panel, with worker threads for backend
I/O and queue dispatch to the Tk thread. Retain existing scheduling through `tick`. Disable the macOS
self-updater on Windows. Distribute a source ZIP requiring Python, with documented attribution.

## Alternatives and tradeoffs

- WSL/Git Bash: fewer port changes, but retains Unix dependencies and does not integrate with native
  desktop sessions or notifications as reliably. It does not meet the native Windows goal.
- Rewrite in .NET/WPF: a strong Windows UI, but adds build/runtime machinery and a second detection
  implementation or RPC layer. A later native UI can continue to consume the same snapshot API.
- Qt/pystray/PyInstaller: useful for richer visuals and a standalone EXE, but adds dependencies and
  binary packaging/testing. The first port prioritizes a reproducible stdlib implementation.
- Replace the checked-in manifest: simpler but would break the upstream macOS installation. Generate
  platform-specific definitions during setup and retain original identity and licenses instead.

## Acceptance

Run the upstream offline suite on native Windows, including JS/Python parity, match/mismatch,
refusals, busy threads, timeout retries, schedules and hook trust. Add Windows process/locking,
Unicode/space paths and generated-hook checks, plus demo GUI/tray smoke tests. Verify real Codex
initialization and hooks discovery without an inference turn. Preserve upstream commit ancestry,
record validation in `docs/VALIDATION.md`, and push the `windows` branch to the attributed fork.

## Consequences

Python/Tcl/Tk is required. Hook command changes require trust review and Codex restart. Tray balloons
are less integrated than registered Notification Center toasts. ModelTrace's statistical limitations
remain, and platform support does not improve classifier accuracy. No user credentials or local
probe/session records are committed. Further packaging/UI work should evolve this decision explicitly.
