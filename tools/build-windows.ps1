param([string]$OutputDirectory, [string]$RuntimeArchive, [switch]$AllowDirty)
$ErrorActionPreference = 'Stop'
$stage = $null
$stageCreated = $false
try {
    $root = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
    $version = '0.5.3-port.3'
    $pythonVersion = '3.13.16'
    $pythonUrl = 'https://www.python.org/ftp/python/3.13.16/python-3.13.16-embed-amd64.zip'
    $pythonHash = '97dae5274cc54867065e8d5a3226e48c35017ed332a0fdb0e27d5b5821961297'
    $pending = @(& git -C $root status --porcelain)
    if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect source Git state.' }
    $dirty = $pending.Count -gt 0
    if ($dirty -and !$AllowDirty) { throw 'Commit all source changes first; release builds require clean committed HEAD. Use -AllowDirty only for local development validation.' }
    $head = [string](& git -C $root rev-parse --verify HEAD)
    if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve source HEAD.' }
    if (!$OutputDirectory) { $OutputDirectory = Join-Path $root 'dist' }
    $output = [IO.Path]::GetFullPath($OutputDirectory).TrimEnd([char[]]'\/')
    [IO.Directory]::CreateDirectory($output) | Out-Null
    $stageName = '.windows-build-' + [Guid]::NewGuid().ToString('N')
    $stage = [IO.Path]::GetFullPath((Join-Path $output $stageName))
    if (Test-Path -LiteralPath $stage) { throw 'Build staging collision.' }
    [IO.Directory]::CreateDirectory($stage) | Out-Null
    $stageCreated = $true
    $sourceParent = Join-Path $stage 'source'
    $sourceRoot = Join-Path $sourceParent 'if-gpt-nerfed-main'
    [IO.Directory]::CreateDirectory($sourceRoot) | Out-Null
    $sourceZip = Join-Path $output "IsGPTNerfed-Windows-$version-source.zip"
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    if ($dirty) {
        # Explicit development snapshot. Ignored caches, runtime downloads and Git internals stay out.
        $files = @(& git -C $root -c core.quotepath=false ls-files --cached --others --exclude-standard)
        if ($LASTEXITCODE -ne 0) { throw 'Cannot enumerate development source snapshot.' }
        foreach ($relative in $files) {
            $source = [IO.Path]::GetFullPath((Join-Path $root $relative))
            if (!$source.StartsWith($root + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw "Unexpected source path: $relative" }
            if (!(Test-Path -LiteralPath $source -PathType Leaf)) { continue }
            $target = Join-Path $sourceRoot $relative
            [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target)) | Out-Null
            Copy-Item -LiteralPath $source -Destination $target
        }
        if (Test-Path -LiteralPath $sourceZip) { Remove-Item -LiteralPath $sourceZip }
        [IO.Compression.ZipFile]::CreateFromDirectory($sourceParent, $sourceZip, [IO.Compression.CompressionLevel]::Optimal, $false)
    } else {
        & git -C $root archive --format=zip --prefix=if-gpt-nerfed-main/ "--output=$sourceZip" HEAD
        if ($LASTEXITCODE -ne 0) { throw 'git archive failed.' }
        [IO.Compression.ZipFile]::ExtractToDirectory($sourceZip, $sourceParent)
    }
    $portableParent = Join-Path $stage 'portable'
    $portable = Join-Path $portableParent 'IsGPTNerfed'
    [IO.Directory]::CreateDirectory($portable) | Out-Null
    foreach ($name in @('plugin', 'bin', '.agents', 'docs')) { Copy-Item -LiteralPath (Join-Path $sourceRoot $name) -Destination (Join-Path $portable $name) -Recurse }
    # The backend's built-in offline selftest resolves this exact original reference path.
    # Ship its data fixture, without shipping the test runner/source files.
    $fixtures = Join-Path $portable 'tests/fixtures'
    [IO.Directory]::CreateDirectory($fixtures) | Out-Null
    Copy-Item -LiteralPath (Join-Path $sourceRoot 'tests/fixtures/reference_subset.jsonl') -Destination (Join-Path $fixtures 'reference_subset.jsonl')
    foreach ($name in @('launch.ps1', 'launch.cmd', 'install.ps1', 'uninstall.ps1', 'LICENSE', 'NOTICE.md', 'README.md', 'README.zh-CN.md', 'CHANGELOG.md')) {
        $file = Join-Path $sourceRoot $name
        if (Test-Path -LiteralPath $file -PathType Leaf) { Copy-Item -LiteralPath $file -Destination (Join-Path $portable $name) }
    }
    [IO.Directory]::CreateDirectory((Join-Path $portable 'tools')) | Out-Null
    Copy-Item -LiteralPath (Join-Path $sourceRoot 'tools/windows-runtime.ps1') -Destination (Join-Path $portable 'tools/windows-runtime.ps1')
    & (Join-Path $sourceRoot 'tools/compile-windows.ps1') -SourceDirectory $sourceRoot -OutputDirectory $portable
    if ($LASTEXITCODE -ne 0) { throw 'Compiled Windows frontend build failed.' }
    if (!$RuntimeArchive) { $RuntimeArchive = Join-Path $output "runtime-cache/python-$pythonVersion-embed-amd64.zip" }
    $runtimeZip = [IO.Path]::GetFullPath($RuntimeArchive)
    if (!(Test-Path -LiteralPath $runtimeZip -PathType Leaf)) {
        [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($runtimeZip)) | Out-Null
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $pythonUrl -OutFile $runtimeZip -UseBasicParsing
    }
    $actual = (Get-FileHash -LiteralPath $runtimeZip -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $pythonHash) { throw "Python runtime SHA256 mismatch. Expected $pythonHash; found $actual. Archive was not extracted or executed." }
    $runtime = Join-Path $portable 'runtime'
    [IO.Compression.ZipFile]::ExtractToDirectory($runtimeZip, $runtime)
    # The official isolated runtime stays private to this app. No pip/site/system changes.
    $pth = @(Get-ChildItem -LiteralPath $runtime -Filter 'python*._pth' -File)
    if ($pth.Count -ne 1) { throw 'Expected one official embedded Python _pth file.' }
    $stdlibZip = @(Get-ChildItem -LiteralPath $runtime -Filter 'python*.zip' -File)
    if ($stdlibZip.Count -ne 1) { throw 'Expected one embedded standard-library ZIP.' }
    [IO.File]::WriteAllText($pth[0].FullName, ($stdlibZip[0].Name + "`r`n.`r`n..\plugin\skills\is-gpt-nerfed\scripts`r`n# Isolated application paths; site remains disabled.`r`n"), [Text.Encoding]::ASCII)
    if (!(Test-Path -LiteralPath (Join-Path $runtime 'LICENSE.txt'))) { throw 'Official Python license is missing.' }
    $fileHashes = [ordered]@{}
    foreach ($file in Get-ChildItem -LiteralPath $portable -Recurse -File | Sort-Object FullName) {
        $relative = $file.FullName.Substring($portable.Length + 1).Replace('\', '/')
        $fileHashes[$relative] = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $manifest = [ordered]@{
        version = $version; architecture = 'win-x64'; frontend = '.NET Framework 4.8 WPF'; unsigned = $true
        source_commit = $head.Trim(); source_dirty = $dirty; development_snapshot = [bool]$AllowDirty
        python = [ordered]@{ version = $pythonVersion; url = $pythonUrl; sha256 = $pythonHash; license = 'runtime/LICENSE.txt'; isolated_paths = $true }
        files = $fileHashes
    }
    $manifestJson = $manifest | ConvertTo-Json -Depth 8
    [IO.File]::WriteAllText((Join-Path $portable 'build-manifest.json'), $manifestJson, (New-Object Text.UTF8Encoding($false)))
    [IO.File]::WriteAllText((Join-Path $output "IsGPTNerfed-Windows-$version-manifest.json"), $manifestJson, (New-Object Text.UTF8Encoding($false)))
    $portableZip = Join-Path $output "IsGPTNerfed-Windows-$version-win-x64.zip"
    if (Test-Path -LiteralPath $portableZip) { Remove-Item -LiteralPath $portableZip }
    [IO.Compression.ZipFile]::CreateFromDirectory($portableParent, $portableZip, [IO.Compression.CompressionLevel]::Optimal, $false)
    foreach ($zip in @($sourceZip, $portableZip)) {
        $hash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
        [IO.File]::WriteAllText(($zip + '.sha256'), ($hash + '  ' + [IO.Path]::GetFileName($zip) + "`n"), [Text.Encoding]::ASCII)
        Write-Host $zip
        Write-Host ($zip + '.sha256')
    }
    Write-Host "Source commit: $head (dirty=$dirty)"
} catch {
    [Console]::Error.WriteLine($_.Exception.ToString())
    exit 1
} finally {
    if ($stageCreated) {
        $deleteTarget = [IO.Path]::GetFullPath($stage)
        if ([IO.Path]::GetDirectoryName($deleteTarget).TrimEnd([char[]]'\/') -ne $output -or [IO.Path]::GetFileName($deleteTarget) -ne $stageName -or $stageName -notmatch '^\.windows-build-[0-9a-f]{32}$') { throw 'Refusing unexpected build staging cleanup target.' }
        if ([IO.Directory]::Exists($deleteTarget)) {
            if (([IO.File]::GetAttributes($deleteTarget) -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Refusing recursive build cleanup of a reparse point.' }
            [IO.Directory]::Delete($deleteTarget, $true)
        }
    }
}
