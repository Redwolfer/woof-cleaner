# Run the installer modes on separate clean Windows 11 guest snapshots.
param(
    [Parameter(Mandatory)][string]$PackageDir,
    [ValidateSet('Portable', 'CurrentUser', 'AllUsers')][string]$Mode = 'Portable',
    [string]$BaselineSetup
)
$ErrorActionPreference = 'Stop'
$package = (Resolve-Path -LiteralPath $PackageDir).Path
$version = (Get-Item -LiteralPath (Join-Path $package 'woof.exe')).VersionInfo.ProductVersion.Trim()
$installMode = $Mode -ne 'Portable'
$originalLocal = $env:LOCALAPPDATA
$originalPath = $env:PATH
if ($installMode) {
    $baseline = (Resolve-Path -LiteralPath $BaselineSetup).Path
    if ((Get-Item -LiteralPath $baseline).VersionInfo.ProductVersion.Trim() -ne '0.1.0') { throw 'Expected baseline installer 0.1.0' }
    $entries = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue
    if (($entries | Where-Object DisplayName -eq 'Woof Cleaner') -or (Test-Path "$originalLocal\WoofCleaner")) {
        throw 'Installer QA needs a clean guest. This profile already contains Woof Cleaner.'
    }
    if ((Get-Process -Name woof,WoofCleaner -ErrorAction SilentlyContinue) -or
        (Get-ScheduledTask | Where-Object TaskName -like 'Woof Cleaner*')) {
        throw 'Existing Woof process or task found in guest'
    }
}
$id = [guid]::NewGuid().ToString('N')
$work = (New-Item -Type Directory -Path (Join-Path $env:TEMP "woof-qa-$id")).FullName
$bin = Join-Path $work 'app'
$target = (New-Item -Type Directory -Path (Join-Path $work 'fixture')).FullName
$registry = "HKCU:\Software\WoofCleanerQA-$id"

function Run-Setup($exe, $arguments) {
    $process = Start-Process -FilePath $exe -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru
    if ($process.ExitCode) {throw "Setup exited with code $($process.ExitCode)"}
}
function Run-Woof {
    & (Join-Path $bin 'woof.exe') @args
    if ($LASTEXITCODE) {throw "woof exited with code $LASTEXITCODE"}
}

function Test-WoofWindow {
    $exe = Join-Path $bin 'WoofCleaner.exe'
    $launcher = Start-Process -FilePath $exe -WindowStyle Hidden -PassThru
    try {
        $deadline = (Get-Date).AddSeconds(30)
        do {
            Start-Sleep -Milliseconds 150
            $window = Get-Process -Name WoofCleaner -ErrorAction SilentlyContinue | Where-Object {
                $_.Path -eq $exe -and $_.MainWindowTitle -eq 'Woof Cleaner'
            } | Select-Object -First 1
        } until ($window -or $launcher.HasExited -or (Get-Date) -gt $deadline)
        if (!$window -or !$window.Responding) {throw 'Packaged GUI did not open a responsive main window'}
        if (!$window.CloseMainWindow() -or !$launcher.WaitForExit(10000)) {throw 'Packaged GUI did not close normally'}
    } finally {
        Get-Process -Name WoofCleaner -ErrorAction SilentlyContinue |
            Where-Object { $_.Path -eq $exe } | Stop-Process -Force -ErrorAction SilentlyContinue
    }
}

try {
    if ($installMode) {
        $scope = if ($Mode -eq 'AllUsers') { '/ALLUSERS' } else { '/CURRENTUSER' }
        $setupArgs = @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART', $scope, "/DIR=""$bin""")
        Run-Setup $baseline $setupArgs
    } else {
        New-Item -Type Directory -Path $bin | Out-Null
        Copy-Item -LiteralPath (Join-Path $package 'woof.exe'),(Join-Path $package 'WoofCleaner.exe') -Destination $bin
        $env:LOCALAPPDATA = $work
    }
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot;$env:SystemRoot\System32\WindowsPowerShell\v1.0"
    $data = Join-Path $env:LOCALAPPDATA 'WoofCleaner'
    $backups = New-Item -Force -Type Directory -Path (Join-Path $data 'backups')
    $prefs = Join-Path $data 'settings.json'
    $utf8 = New-Object Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($prefs, '{"auto_check":false,"clean_selection":["fixture"],"cookie_allowlist":["example.test"]}', $utf8)
    $oldBackup = Join-Path $backups.FullName 'registry_legacy.json'
    [IO.File]::WriteAllText($oldBackup, '{}', $utf8)
    if ($installMode) {
        Run-Setup (Join-Path $package "WoofCleaner-Setup-$version.exe") $setupArgs
    }
    $saved = Get-Content -LiteralPath $prefs -Raw | ConvertFrom-Json
    if ($saved.cookie_allowlist[0] -ne 'example.test' -or $saved.clean_selection[0] -ne 'fixture' -or !(Test-Path $oldBackup)) {
        throw 'Upgrade lost fixture settings or backup'
    }
    $help = Run-Woof --help
    if (($help -join ' ') -notmatch [regex]::Escape("Woof Cleaner $version")) {throw 'Unexpected CLI version'}
    $probe = Join-Path $target 'junk.tmp'
    $rules = @('[Fixture]','ID=fixture','Default=True',"FileKey1=$target|*.tmp","RegKey1=HKCU\Software\WoofCleanerQA-$id|marker")
    [IO.File]::WriteAllLines((Join-Path $bin 'rules.ini'), [string[]]$rules, $utf8)
    Test-WoofWindow
    New-Item -Path $registry | Out-Null
    New-ItemProperty -Path $registry -Name marker -Value 'restore-me' | Out-Null
    [IO.File]::WriteAllText($probe, 'junk', $utf8)
    $preview = (Run-Woof analyze --json) -join ' ' | ConvertFrom-Json
    if ($preview.files -ne 1 -or !(Test-Path $probe)) {throw 'Analyze did not preserve fixture'}
    Run-Woof clean --yes | Out-Null
    if ((Test-Path $probe) -or (Get-ItemProperty $registry).marker) {throw 'Clean left the fixture intact'}
    $backup = Get-ChildItem -LiteralPath $backups.FullName -Filter 'registry_*.json' | Where-Object FullName -ne $oldBackup | Select-Object -First 1
    Run-Woof registry --restore $backup.FullName | Out-Null
    if ((Get-ItemProperty $registry).marker -ne 'restore-me') {throw 'Registry restore failed'}
    [IO.File]::WriteAllText($probe, 'scheduled', $utf8)
    if ($installMode) {
        Run-Woof schedule --add daily --time 23:58 | Out-Null
        $sid = (Get-Content -LiteralPath $prefs -Raw | ConvertFrom-Json).schedules[0].id
        Run-Woof schedule --run $sid | Out-Null
        $deadline = (Get-Date).AddMinutes(1)
        do {
            Start-Sleep -Milliseconds 200
            $history = (Get-Content -LiteralPath $prefs -Raw | ConvertFrom-Json).autoclean_history
        } until (($history | Where-Object trigger -eq $sid) -or (Get-Date) -gt $deadline)
        if ((Test-Path $probe) -or !($history | Where-Object trigger -eq $sid)) {throw 'Scheduled task did not record and clean fixture'}
        Run-Setup (Join-Path $bin 'unins000.exe') @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART')
        if ((Test-Path (Join-Path $bin 'woof.exe')) -or (Get-ScheduledTask -TaskName "Woof Cleaner Auto Clean $sid" -ErrorAction SilentlyContinue)) {
            throw 'Uninstall left the executable or task'
        }
        if (!(Test-Path $backup.FullName)) {throw 'Uninstall removed user backup'}
    } else {
        Run-Woof auto-clean --trigger fixture
        if (Test-Path $probe) {throw 'Automatic clean did not clean fixture'}
    }
    Write-Host "PASS $Mode $version"
} finally {
    if (Test-Path -LiteralPath $registry) {Remove-Item -LiteralPath $registry}
    $env:LOCALAPPDATA = $originalLocal
    $env:PATH = $originalPath
    $resolved = (Resolve-Path -LiteralPath $work).Path
    $expected = [IO.Path]::GetFullPath((Join-Path $env:TEMP "woof-qa-$id"))
    if (!$installMode -and $resolved -eq $expected) {Remove-Item -LiteralPath $resolved -Recurse -Force}
}
