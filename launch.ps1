$ErrorActionPreference = 'Stop'
try {
    . (Join-Path $PSScriptRoot 'tools/windows-runtime.ps1')
    $python = Get-NerfedPython
    $pythonw = Join-Path (Split-Path -Parent $python) 'pythonw.exe'
    $app = Join-Path $PSScriptRoot 'windows/app.py'
    if (!(Test-Path -LiteralPath $app)) { throw "Desktop panel missing: $app" }
    # Pass arguments directly for demo/smoke runs, which need a result and exit code.
    if ($args.Count -gt 0 -or !(Test-Path -LiteralPath $pythonw)) {
        & $python -X utf8 $app @args
        exit $LASTEXITCODE
    }
    Start-Process -FilePath $pythonw -ArgumentList @('-X', 'utf8', ('"' + $app + '"')) -WindowStyle Hidden
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
