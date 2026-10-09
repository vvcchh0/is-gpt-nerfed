param([switch]$Purge, [switch]$KeepPath)
$ErrorActionPreference = 'Stop'
try {
    . (Join-Path $PSScriptRoot 'tools/windows-runtime.ps1')
    $python = Get-NerfedPython
    $teardownArgs = @('teardown')
    if ($Purge) { $teardownArgs += '--purge' }
    & $python -X utf8 (Join-Path $PSScriptRoot 'plugin/skills/is-gpt-nerfed/scripts/nerfed') @teardownArgs
    $code = $LASTEXITCODE
    if ($code -ne 0) { exit $code }
    if (!$KeepPath) {
        $bin = (Join-Path $PSScriptRoot 'bin').TrimEnd('\')
        $current = [Environment]::GetEnvironmentVariable('Path', 'User')
        $originalEntries = @($current -split ';')
        $matching = @($originalEntries | Where-Object { $_ -and $_.TrimEnd('\') -ieq $bin })
        if ($matching.Count -gt 0) {
            $entries = @($originalEntries | Where-Object { !$_.TrimEnd('\').Equals($bin, [StringComparison]::OrdinalIgnoreCase) })
            [Environment]::SetEnvironmentVariable('Path', ($entries -join ';'), 'User')
        }
    }
    exit 0
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
