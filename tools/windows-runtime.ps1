# Resolve an actual Python interpreter, skipping Microsoft Store aliases.
function Get-NerfedPython {
    $candidates = @()
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
            $resolved = & $exe @prefix -c 'import sys; assert sys.version_info >= (3, 10); print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $resolved -and (Test-Path -LiteralPath ([string]$resolved))) {
                return ([string]$resolved).Trim()
            }
        } catch { }
    }
    throw 'Python 3.10+ is required. Install Python with Tcl/Tk, or set NERFED_PYTHON to python.exe.'
}
