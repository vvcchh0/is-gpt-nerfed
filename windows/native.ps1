$ErrorActionPreference = 'Stop'
$exitCode = 1
$temporary = $null
$temporaryCreated = $false
$temporaryParent = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd([char[]]'\/')
$temporaryName = $null
$savedEnvironment = @{}
$showBootstrapError = ($args.Count -eq 0)
try {
    $demo = $false; $smoke = $false; $selfTest = $false
    $render = ''; $page = ''; $width = 0; $scale = 1.0
    for ($i = 0; $i -lt $args.Count; $i++) {
        switch ([string]$args[$i]) {
            '--demo' { $demo = $true }
            '--smoke-test' { $demo = $true; $smoke = $true }
            '--self-test' { $demo = $true; $selfTest = $true }
            '--render' { $i++; $render = [string]$args[$i]; $demo = $true }
            '--render-detail' { $page = 'detail' }
            '--render-settings' { $page = 'settings' }
            '--render-width' { $i++; $width = [int]$args[$i] }
            '--render-scale' { $i++; $scale = [double]::Parse([string]$args[$i], [Globalization.CultureInfo]::InvariantCulture) }
            default { throw "Unknown native panel argument: $($args[$i])" }
        }
    }
    if ($width -and ($width -lt 380 -or $width -gt 1200)) { throw 'Render width must be 380..1200.' }
    if ($scale -lt 0.5 -or $scale -gt 3) { throw 'Render scale must be 0.5..3.' }
    if ($demo) {
        # Demo, rendering and tests never read or change the user's Codex state.
        $temporaryName = 'nerfed-native-' + [Guid]::NewGuid().ToString('N')
        $temporary = [IO.Path]::GetFullPath((Join-Path $temporaryParent $temporaryName))
        if ([IO.Directory]::Exists($temporary) -or [IO.File]::Exists($temporary)) { throw 'Temporary state collision.' }
        [IO.Directory]::CreateDirectory($temporary) | Out-Null
        $temporaryCreated = $true
        foreach ($name in @('CODEX_HOME', 'NERFED_HOME', 'NERFED_NO_UPDATE_CHECK')) {
            $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
        }
        $env:CODEX_HOME = Join-Path $temporary 'codex-home'
        $env:NERFED_HOME = Join-Path $temporary 'ledger'
        $env:NERFED_NO_UPDATE_CHECK = '1'
    }
    . (Join-Path (Split-Path -Parent $PSScriptRoot) 'tools/windows-runtime.ps1')
    $python = Get-NerfedPython
    Add-Type -AssemblyName PresentationFramework, PresentationCore, WindowsBase, System.Xaml, System.Xml, System.Windows.Forms, System.Drawing, System.Web.Extensions
    $references = @(
        [Windows.Window].Assembly.Location,
        [Windows.Media.Visual].Assembly.Location,
        [Windows.Threading.Dispatcher].Assembly.Location,
        [System.Xaml.XamlReader].Assembly.Location,
        [Xml.XmlReader].Assembly.Location,
        [Windows.Forms.NotifyIcon].Assembly.Location,
        [Drawing.Icon].Assembly.Location,
        [Web.Script.Serialization.JavaScriptSerializer].Assembly.Location
    )
    Add-Type -Path (Join-Path $PSScriptRoot 'native.cs') -ReferencedAssemblies $references
    $exitCode = [Nerfed.NativePanel]::Run($python, (Split-Path -Parent $PSScriptRoot), $demo, $smoke, $selfTest, $render, $page, $width, $scale)
} catch {
    [Console]::Error.WriteLine($_.Exception.ToString())
    $exitCode = 1
    if ($showBootstrapError) {
        # Ordinary launches use a hidden helper, so stderr alone is invisible.
        # Argument-driven demo/test/render runs must never block on a dialog.
        $detail = $_.Exception.Message
        if ($detail.Length -gt 1200) { $detail = $detail.Substring(0, 1200) + '...' }
        $message = "Unable to start is-gpt-nerfed.`r`n`r`n$detail`r`n`r`nCheck that Python 3.10+ is installed (or set NERFED_PYTHON), and that windows/native.cs and native.xaml are present.`r`nRun launch.cmd --smoke-test in a terminal to see full details."
        try {
            Add-Type -AssemblyName System.Windows.Forms
            [Windows.Forms.MessageBox]::Show($message, 'is-gpt-nerfed - startup error', [Windows.Forms.MessageBoxButtons]::OK, [Windows.Forms.MessageBoxIcon]::Error) | Out-Null
        } catch {
            # Keep a visible fallback if loading the .NET UI assemblies itself failed.
            try { $shell = New-Object -ComObject WScript.Shell; $shell.Popup($message, 0, 'is-gpt-nerfed - startup error', 16) | Out-Null } catch { }
        }
    }
} finally {
    if ($temporaryCreated) {
        foreach ($name in $savedEnvironment.Keys) { [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process') }
        # Verify the final absolute target immediately before recursive deletion.
        $deleteTarget = [IO.Path]::GetFullPath($temporary)
        $deleteParent = [IO.Path]::GetDirectoryName($deleteTarget).TrimEnd([char[]]'\/')
        if ($deleteParent -ne $temporaryParent -or [IO.Path]::GetFileName($deleteTarget) -ne $temporaryName -or $temporaryName -notmatch '^nerfed-native-[0-9a-f]{32}$') {
            throw 'Refusing to clean an unexpected temporary state path.'
        }
        if ([IO.Directory]::Exists($deleteTarget)) {
            if (([IO.File]::GetAttributes($deleteTarget) -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Refusing to recursively clean a reparse point.' }
            [IO.Directory]::Delete($deleteTarget, $true)
        }
    }
}
exit $exitCode
