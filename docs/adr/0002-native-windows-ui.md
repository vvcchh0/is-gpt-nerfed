# ADR 0002: use WPF for the Windows panel and retain the Python CLI

Date: 2026-10-09
Status: Accepted; supersedes the frontend choice in [ADR 0001](0001-windows-port.md).
ADR 0001's detector, installation, attribution and shared-data decisions remain in effect.
Source: the user's Windows-panel screenshot and request for concrete interaction instructions and
a UI reconstruction based on upstream screenshots/macOS source, implemented by GPT-6.1 Sol at xhigh.

## Context and evidence

The first Tk port proves backend compatibility, but exposes a long plain-text report and hides
useful session metadata in a narrow list. A single pending probe disables refresh, diagnostics and
settings. Scheduler output is prepended to the selected session report, blurring operation state
and detector evidence. The screenshot shows this while a probe is pending.

The original [PanelView.swift](../../macos/Sources/IsGPTNerfed/PanelView.swift) and
[screenshots](https://github.com/kiyoakii/is-gpt-nerfed#readme) instead use a face/status summary,
compact session rows, inline report expansion, a separate fresh-session section and a settings page.
[Store.swift](../../macos/Sources/IsGPTNerfed/Store.swift) separates snapshot polling and pending probes.
[SettingsView.swift](../../macos/Sources/IsGPTNerfed/SettingsView.swift) exposes both session and fresh schedules.

## Decision

Use Windows PowerShell 5.1 in STA mode and the OS's .NET Framework WPF assemblies for the default
window, with native notification-area integration. XAML/style and a small frontend controller may
be separated from the launcher. The controller calls the existing Python CLI with explicit UTF-8
streams and correctly quoted arguments; it does not implement a second detector or statistical scorer.
The local host successfully loaded PresentationFramework and System.Windows.Forms before this decision.

Keep the old Tk panel available through `launch.cmd --legacy-tk`. Default `launch.cmd`, demo and smoke
launches target WPF. The native frontend requires Windows PowerShell/.NET Framework and the existing
Python backend, with no .NET SDK, browser server or additional pip dependency.

Match upstream information hierarchy, preserve original face assets, use semantic status colors,
and put session details near the row they explain. Provide a Chinese presentation while retaining
raw model IDs, configuration values and stored verdict codes. Settings use an explicit save action.
Expose the two schedules separately; `mode=nudge` is not a global switch for the fresh-session heartbeat.

Keep snapshot refresh, diagnostics and navigation responsive during long probes. Track manual
probe state by target and prevent duplicate submissions. Background scheduler messages belong in
operation feedback, never in the selected session's evidence. A failed latest attempt and the last
valid verdict remain distinct. Any unimplemented platform feature must have an honest explanation.

Demo, smoke, render and interaction tests use temporary CODEX_HOME/NERFED_HOME and synthetic data or
a fake transport. They must not submit real inference, overwrite live detector configuration,
close the user's current Tk/Codex processes, or capture real session titles in published screenshots.

## Alternatives and tradeoffs

- More Tk styling: preserves one Python frontend, but requires substantial custom widgets/layout and
  still provides a weaker native rendering and accessibility basis for the requested reconstruction.
- PySide/Qt: strong native widgets, but adds a sizeable third-party runtime and distribution work.
- Web frontend/Edge app window: flexible presentation, but needs a localhost RPC boundary, lifecycle
  and authentication policy or WebView packaging. That is unnecessary for this local native panel.
- Modern .NET/WinUI project: a good future packaging path, but requires a separate build SDK/runtime.
  Framework WPF is already available here and can consume the same CLI without a detector rewrite.

WPF is Windows-only and PowerShell-hosted code requires careful encoding, event lifetime and process
handling. The runtime compiler and XAML are reviewed as source; there is no new signed standalone EXE.
The old Tk fallback keeps a recovery path while native UI coverage matures.

## Delivery and acceptance

The implementation owner is a GPT-6.1 Sol xhigh worker; it does not redelegate. The parent owns this
decision, user-facing instructions, integration, final review, commits and acceptance. No tracker
publication is required by this request; source specifications and Git history retain the evidence chain.

Deliverables and their real dependencies:

| Deliverable | Depends on | Observable acceptance |
| --- | --- | --- |
| Interaction guide | existing CLI/Tk semantics and macOS source | [guide](../INTERACTION.zh-CN.md) explains both workflows, schedules, retry and fresh overrides |
| Native window/controller | shared snapshot/CLI contract | cards, expanded details, fresh section, settings, diagnostics and tray work with synthetic/fake data |
| Default launcher | native window/controller | Chinese/space paths, background launch, demo/smoke and explicit Tk fallback work |
| Distribution and evidence | native implementation plus checks | original suite remains passing, WPF interaction tests and native visual checks pass, source ZIP and original licenses are retained |

Acceptance includes actions reaching the correct fake backend arguments, settings persistence,
retry behavior, refresh while a long probe is pending, shutdown preventing new children, and
normal/narrow/high-scale rendering without losing controls. Verify the shipped archive's entry
points and run the existing cross-platform suite. Record actual results and remaining limits in
[VALIDATION.md](../VALIDATION.md), then commit and publish the Windows update within the existing fork.

## References

- [Microsoft WPF overview](https://learn.microsoft.com/en-us/dotnet/desktop/wpf/overview/): layout,
  XAML and Windows-only .NET Framework implementation.
- [Process.StandardOutput](https://learn.microsoft.com/en-us/dotnet/api/system.diagnostics.process.standardoutput?view=netframework-4.8):
  redirected-stream deadlock constraints; use asynchronous reads for both streams.
- [NotifyIcon](https://learn.microsoft.com/en-us/dotnet/api/system.windows.forms.notifyicon): native tray lifecycle.
