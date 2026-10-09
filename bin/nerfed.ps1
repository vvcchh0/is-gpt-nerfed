$ErrorActionPreference = 'Stop'
try {
    $root = Split-Path -Parent $PSScriptRoot
    . (Join-Path $root 'tools/windows-runtime.ps1')
    $python = Get-NerfedPython
    & $python -X utf8 (Join-Path $root 'plugin/skills/is-gpt-nerfed/scripts/nerfed') @args
    exit $LASTEXITCODE
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
