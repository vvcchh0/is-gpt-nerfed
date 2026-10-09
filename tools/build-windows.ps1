param([string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
try {
    $root = Split-Path -Parent $PSScriptRoot
    $pending = & git -C $root status --porcelain
    if ($LASTEXITCODE -ne 0 -or $pending) { throw 'Commit all Windows source changes first; this build archives committed HEAD only.' }
    $head = & git -C $root rev-parse --verify HEAD
    $hasPanel = & git -C $root ls-tree --name-only HEAD windows/app.py
    if ($LASTEXITCODE -ne 0 -or !$hasPanel) { throw 'Committed HEAD does not contain the Windows panel.' }
    if (!$OutputDirectory) { $OutputDirectory = Join-Path $root 'dist' }
    $output = [IO.Path]::GetFullPath($OutputDirectory)
    New-Item -ItemType Directory -Path $output -Force | Out-Null
    $zip = Join-Path $output 'IsGPTNerfed-Windows-0.5.3-port.1.zip'
    & git -C $root archive --format=zip --prefix=if-gpt-nerfed-main/ "--output=$zip" HEAD
    if ($LASTEXITCODE -ne 0) { throw 'git archive failed. Commit the Windows implementation before building.' }
    $hash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
    [IO.File]::WriteAllText(($zip + '.sha256'), ($hash + '  ' + [IO.Path]::GetFileName($zip) + "`n"), [Text.Encoding]::ASCII)
    Write-Host $zip
    Write-Host ($zip + '.sha256')
    Write-Host "Source commit: $head"
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
