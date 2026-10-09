param([string]$OutputDirectory, [string]$SourceDirectory)
$ErrorActionPreference = 'Stop'
try {
    if (!$SourceDirectory) { $SourceDirectory = Split-Path -Parent $PSScriptRoot }
    $root = [IO.Path]::GetFullPath($SourceDirectory)
    if (!$OutputDirectory) { $OutputDirectory = Join-Path $root 'dist/compiled' }
    $output = [IO.Path]::GetFullPath($OutputDirectory)
    [IO.Directory]::CreateDirectory($output) | Out-Null
    $framework = Join-Path $env:SystemRoot 'Microsoft.NET/Framework64/v4.0.30319'
    $compiler = Join-Path $framework 'csc.exe'
    if (!(Test-Path -LiteralPath $compiler -PathType Leaf)) { throw 'The .NET Framework 4.x x64 compiler is required only on the build machine.' }
    $wpf = Join-Path $framework 'WPF'
    $references = @('System.dll', 'System.Core.dll', 'System.Xaml.dll', 'System.Xml.dll', 'System.Windows.Forms.dll', 'System.Drawing.dll', 'System.Web.Extensions.dll') | ForEach-Object { Join-Path $framework $_ }
    $references += @('PresentationFramework.dll', 'PresentationCore.dll', 'WindowsBase.dll', 'UIAutomationTypes.dll') | ForEach-Object { Join-Path $wpf $_ }
    foreach ($reference in $references) { if (!(Test-Path -LiteralPath $reference)) { throw "Missing build reference: $reference" } }
    $referenceArgs = @($references | ForEach-Object { '/reference:' + $_ })
    $native = Join-Path $root 'windows/native.cs'
    $info = Join-Path $root 'windows/AssemblyInfo.cs'
    $dll = Join-Path $output 'IsGPTNerfed.Panel.dll'
    $resourceArgs = @('/resource:' + (Join-Path $root 'windows/native.xaml') + ',Nerfed.Native.xaml')
    foreach ($state in @('ok', 'warn', 'alert')) { $resourceArgs += '/resource:' + (Join-Path $root "macos/Resources/face-$state.png") + ",Nerfed.face-$state.png" }
    & $compiler /nologo /utf8output /optimize+ /platform:x64 /target:library ('/out:' + $dll) @referenceArgs @resourceArgs $native $info
    if ($LASTEXITCODE -ne 0) { throw 'Panel DLL compilation failed.' }
    # Generate the executable's native icon at build time, from the original bundled face.
    Add-Type -AssemblyName System.Drawing
    $iconPath = Join-Path $output 'IsGPTNerfed.build.ico'
    $bitmap = New-Object Drawing.Bitmap((Join-Path $root 'macos/Resources/face-ok.png'))
    $small = New-Object Drawing.Bitmap($bitmap, (New-Object Drawing.Size(48, 48)))
    $handle = $small.GetHicon()
    $icon = [Drawing.Icon]::FromHandle($handle)
    try { $stream = [IO.File]::Create($iconPath); try { $icon.Save($stream) } finally { $stream.Dispose() } } finally { $icon.Dispose(); $small.Dispose(); $bitmap.Dispose() }
    $exe = Join-Path $output 'IsGPTNerfed.exe'
    & $compiler /nologo /utf8output /optimize+ /platform:x64 /target:winexe ('/out:' + $exe) @referenceArgs ('/reference:' + $dll) ('/win32manifest:' + (Join-Path $root 'windows/app.manifest')) ('/win32icon:' + $iconPath) (Join-Path $root 'windows/Program.cs') $info
    if ($LASTEXITCODE -ne 0) { throw 'Windows EXE compilation failed.' }
    Copy-Item -LiteralPath (Join-Path $root 'windows/IsGPTNerfed.exe.config') -Destination (Join-Path $output 'IsGPTNerfed.exe.config')
    # Only this generated single file is removed; no recursive output cleanup.
    Remove-Item -LiteralPath $iconPath
    Write-Host "Compiled: $exe"
    Write-Host "Compiled: $dll"
} catch {
    [Console]::Error.WriteLine($_.Exception.ToString())
    exit 1
}
