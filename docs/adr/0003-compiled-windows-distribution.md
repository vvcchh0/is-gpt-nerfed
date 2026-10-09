# ADR 0003: compile the Windows desktop host and bundle a private Python runtime

Date: 2026-10-09
Status: Accepted; supersedes the source-only distribution choice in [ADR 0002](0002-native-windows-ui.md).
The WPF presentation, shared detector and source-mode recovery path remain in effect.
Source: the user's request for a mature EXE/DLL release and report of a doctor warning containing
`hook crashed: PermissionError(13, '拒绝访问。')`.

## Context

Port.2 compiles its C# frontend at startup through PowerShell `Add-Type` and discovers an external
Python interpreter. This is useful for development, but lacks an application executable, compiled
assembly boundary and app-local runtime expected in a Windows release. A source ZIP remains useful
for audit and development, but should not be the only distribution.

The reported error is a single historical entry at 2026-10-09T11:18:33Z. Later hook events exist,
but the old logger retained neither file paths nor traceback frames. Those facts do not establish
the original cause or prove every affected hook recovered. Doctor currently prints a warning and
then says `all good`, which hides the distinction between passed checks and unresolved warnings.

## Decision

Compile a Windows GUI-subsystem `IsGPTNerfed.exe` and `IsGPTNerfed.Panel.dll` for x64 using the
existing .NET Framework C# compiler. The EXE owns startup, arguments, runtime resolution, isolated
offline modes and failure feedback; the DLL owns WPF presentation and CLI transport. Embed XAML
and the original face resources in the DLL. Ordinary startup must not invoke a compiler,
PowerShell host, localhost web server or download endpoint.

Bundle the official **CPython 3.13.16 Windows embeddable x64** distribution under `runtime/`.
Pin its URL and SHA-256, validate cache and downloaded bytes before extraction/execution, retain
its license, and record runtime/build/source provenance in the release manifest. Prefer this
runtime over external interpreters for the portable app and installer/CLI helpers. It is a private
application dependency, not a system Python installation. No pip or user-site packages are needed.
The source package may still use a developer-installed Python. Tk fallback uses an external
Tcl/Tk-enabled interpreter because the official embedded distribution does not include Tcl/Tk.

Keep the statistical scorer, prompts, bank and ledger formats shared with the original Python CLI.
Shipping Python modules alongside an embedded interpreter is deliberate; this release compiles
the desktop application, not the detection algorithm into a second native implementation.
Retain the original MIT license, upstream ancestry, ModelTrace provenance and source package.
Include the existing small `tests/fixtures/reference_subset.jsonl` data file in the portable
archive so its own `selftest` verifies all 18 reference outputs. It is offline data; the test
suite's Python source is not needed in the portable distribution. Formal archive acceptance
revealed that excluding it made the original self-test skip its reference comparisons.

For Windows JSON writes, reproduce temporary target-handle contention in isolated fixtures before
adding bounded retries. Persistent failures must propagate, preserve the previous JSON and clean
the unique temporary file. Keep total hook waiting below its shortest timeout. Hook exceptions
must remain fail-open and record safe location/error metadata without hook input or credentials.
Doctor must count warnings separately from hard failures, explain historical errors and later
activity without claiming recovery, and avoid an unconditional `all good` or probe instruction.

## Alternatives and consequences

- PyInstaller backend freezing would add a packaging dependency and hidden-import/data handling
  for the extensionless CLI. A private standard-library runtime preserves the already tested CLI.
- A modern .NET/WinUI rewrite would require another SDK/runtime transition. The existing WPF
  code can be compiled directly; a future migration can supersede this decision with evidence.
- A single self-extracting EXE would hide resources but introduce extraction and lifecycle work.
  A portable directory with explicit EXE/DLL/runtime boundaries is easier to inspect and update.

The release targets Windows 10/11 x64 with .NET Framework 4.8 and the OS C runtime. It is unsigned;
SmartScreen policy can still affect first launch. It does not claim MSI installation, automatic
startup, signed updates, ARM64 or physical multi-monitor DPI certification. Keep the extracted
directory while hooks reference its interpreter; moving it requires installation from the new path.

## Acceptance and traceability

Both implementation tracks use GPT-6.1 Sol xhigh without redelegation. The parent owns this
decision, integration, attribution, documentation, final checks and publishing.

| Deliverable | Dependency | Acceptance |
| --- | --- | --- |
| Compiled EXE and panel DLL | existing WPF contracts | embedded resources/version metadata, GUI startup and normal Exit, no runtime compilation |
| Private runtime and portable archive | pinned official ZIP | hash verification, no-system-Python smoke/self-test/CLI, Unicode and space paths, retained licenses |
| Hook reliability and doctor | reproducible temporary fixture | transient contention succeeds, persistent failure is bounded and retains old data, safe actionable logs and honest warning summary |
| Release evidence | clean commit and above checks | source/portable ZIP checksums, four-platform backend CI and Windows compiled acceptance, exact commit in release notes |

All development and package tests use temporary homes and fake/synthetic inference. They must not
change the user's saved schedules, hook trust, real ledger or currently running Codex/Tk processes.
Do not delete old error logs to make diagnosis appear clean. Record actual results and limits in
[VALIDATION.md](../VALIDATION.md) and the immutable version's release notes.

## Primary references

- [CPython 3.13.16 release and official checksums](https://www.python.org/downloads/release/python-31316/).
- [Python embeddable distribution](https://docs.python.org/3.13/using/windows.html#the-embeddable-package).
- [C# compiler output options](https://learn.microsoft.com/en-us/dotnet/csharp/language-reference/compiler-options/output).

Pinned archive: `https://www.python.org/ftp/python/3.13.16/python-3.13.16-embed-amd64.zip`.
SHA-256: `97dae5274cc54867065e8d5a3226e48c35017ed332a0fdb0e27d5b5821961297`.
