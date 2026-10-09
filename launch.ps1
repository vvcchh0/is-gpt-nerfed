$ErrorActionPreference = 'Stop'
try {
    if ($args -contains '--legacy-tk') {
        . (Join-Path $PSScriptRoot 'tools/windows-runtime.ps1')
        $python = Get-NerfedPython
        $pythonw = Join-Path (Split-Path -Parent $python) 'pythonw.exe'
        $app = Join-Path $PSScriptRoot 'windows/app.py'
        $legacyArgs = @($args | Where-Object { $_ -ne '--legacy-tk' })
        if ($legacyArgs.Count -gt 0 -or !(Test-Path -LiteralPath $pythonw)) {
            & $python -X utf8 $app @legacyArgs
            exit $LASTEXITCODE
        }
        Start-Process -FilePath $pythonw -ArgumentList @('-X', 'utf8', ('"' + $app + '"')) -WindowStyle Hidden
        exit 0
    }
    $native = Join-Path $PSScriptRoot 'windows/native.ps1'
    if (!(Test-Path -LiteralPath $native)) { throw "Native desktop panel missing: $native" }
    $powershell = Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0/powershell.exe'
    # Demo, smoke, rendering and test runs preserve the result and exit code.
    if ($args.Count -gt 0) {
        & $powershell -NoLogo -NoProfile -STA -ExecutionPolicy Bypass -File $native @args
        exit $LASTEXITCODE
    }
    # Ordinary launches detach, with no helper console or terminal waiting for the panel.
    Start-Process -FilePath $powershell -ArgumentList @('-NoLogo', '-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden', '-File', ('"' + $native + '"')) -WindowStyle Hidden
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
