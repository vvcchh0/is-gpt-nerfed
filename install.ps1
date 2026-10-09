param(
    [switch]$TrustHooks,
    [switch]$NoTrust,
    [string]$CodexBin,
    [switch]$AddToPath,
    [switch]$Launch
)
$ErrorActionPreference = 'Stop'
try {
    if ($TrustHooks -and $NoTrust) { throw 'Choose either -TrustHooks or -NoTrust.' }
    . (Join-Path $PSScriptRoot 'tools/windows-runtime.ps1')
    $python = Get-NerfedPython
    $backend = Join-Path $PSScriptRoot 'plugin/skills/is-gpt-nerfed/scripts/nerfed'
    Write-Host "Python: $python"
    if ($CodexBin) {
        if (!(Test-Path -LiteralPath $CodexBin -PathType Leaf)) { throw "Codex binary not found: $CodexBin" }
        & $python -X utf8 $backend config set codex_bin $CodexBin
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    $setupArgs = @('setup')
    if ($TrustHooks) { $setupArgs += '--trust-hooks' }
    if ($NoTrust) { $setupArgs += '--no-trust' }
    & $python -X utf8 $backend @setupArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    if ($AddToPath) {
        $bin = Join-Path $PSScriptRoot 'bin'
        $current = [Environment]::GetEnvironmentVariable('Path', 'User')
        $entries = @($current -split ';' | Where-Object { $_ })
        if (!($entries | Where-Object { $_.TrimEnd('\') -ieq $bin.TrimEnd('\') })) {
            [Environment]::SetEnvironmentVariable('Path', (($entries + $bin) -join ';'), 'User')
            $env:Path += ";$bin"
            Write-Host 'Added bin to your user PATH. New terminals will see nerfed.'
        }
    }
    Write-Host 'Installed. Restart Codex to reload hooks. Run .\launch.cmd for the desktop panel.'
    if ($Launch) { & (Join-Path $PSScriptRoot 'launch.ps1') }
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
