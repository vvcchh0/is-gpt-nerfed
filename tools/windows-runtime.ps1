# Resolve an actual Python interpreter, skipping Microsoft Store aliases.
$script:NerfedRuntimeAppRoot = Split-Path -Parent $PSScriptRoot
function Get-NerfedPython {
    # Capture the helper's location when dot-sourced; inside a function PSScriptRoot
    # can refer to the calling install/bin script instead.
    param([string]$AppRoot = $script:NerfedRuntimeAppRoot, [switch]$SkipBundled)
    $candidates = @()
    if (!$SkipBundled) {
        $bundled = Join-Path $AppRoot 'runtime/python.exe'
        if (Test-Path -LiteralPath $bundled -PathType Leaf) { $candidates += ,@($bundled) }
    }
    if ($env:NERFED_PYTHON) { $candidates += ,@($env:NERFED_PYTHON) }
    foreach ($name in @('py', 'python', 'python3')) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command) {
            if ($name -eq 'py') { $candidates += ,@($command.Source, '-3') }
            else { $candidates += ,@($command.Source) }
        }
    }
    foreach ($candidate in $candidates) {
        $exe = $candidate[0]
        $prefix = @($candidate | Select-Object -Skip 1)
        try {
            # Embedded Python otherwise uses the locale encoding for redirected stdout.
            # Force UTF-8 on both sides, and restore the caller's console setting.
            $previousEncoding = [Console]::OutputEncoding
            try {
                [Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
                $resolved = & $exe @prefix -X utf8 -c 'import sys; assert sys.version_info >= (3, 10); print(sys.executable)' 2>$null
            } finally { [Console]::OutputEncoding = $previousEncoding }
            if ($LASTEXITCODE -eq 0 -and $resolved -and (Test-Path -LiteralPath ([string]$resolved))) {
                return ([string]$resolved).Trim()
            }
        } catch { }
    }
    if ($SkipBundled) { throw 'Legacy Tk requires an installed Python 3.10+ with Tcl/Tk. The bundled embeddable runtime does not include Tk.' }
    throw 'Python 3.10+ is required. Re-extract the portable ZIP including runtime, install Python, or set NERFED_PYTHON to python.exe.'
}
