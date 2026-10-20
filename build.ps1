# Builds standalone executables into .\dist (no Python needed on the target PC).
#   dist\WoofCleaner.exe  - the windowed app
#   dist\woof.exe         - command-line version (same features, prints to the console)
# Requires on the BUILD machine only: Python 3.10+ and `python -m pip install pyinstaller`.
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
Set-Location $root

python tools\make_icon.py assets\woof.ico
$env:PYTHONPATH = $root
python -m unittest discover -s tests
if ($LASTEXITCODE -ne 0) { throw 'tests failed' }

# Stamp the exe file properties with the version from woofcleaner\__init__.py
$version = (Select-String -Path "$root\woofcleaner\__init__.py" -Pattern '__version__ = "([^"]+)"').Matches[0].Groups[1].Value
$parts = @($version -split '[^\d]+' | Where-Object { $_ } | Select-Object -First 4)
while ($parts.Count -lt 4) { $parts += '0' }
New-Item -ItemType Directory -Force "$root\build" | Out-Null
$versionFile = "$root\build\version_info.txt"
(Get-Content "$root\tools\version_info.txt" -Raw).Replace('{VERSION_TUPLE}', ($parts -join ', ')).Replace('{VERSION}', $version) |
    Set-Content -Path $versionFile -Encoding UTF8

$common = @(
    '--noconfirm', '--clean', '--onefile',
    '--icon', "$root\assets\woof.ico",
    '--add-data', "$root\data\rules.ini;data",
    '--add-data', "$root\assets\woof.ico;assets",
    '--add-data', "$root\assets\woof-32.png;assets",
    '--version-file', $versionFile,
    '--paths', $root,
    '--distpath', "$root\dist", '--workpath', "$root\build", '--specpath', "$root\build"
)

python -m PyInstaller @common --windowed --name WoofCleaner "$root\woof_gui.py"
if ($LASTEXITCODE -ne 0) { throw 'GUI build failed' }
python -m PyInstaller @common --console --name woof "$root\woof_cli.py"
if ($LASTEXITCODE -ne 0) { throw 'CLI build failed' }

# Installer (optional): needs Inno Setup 6 -> winget install JRSoftware.InnoSetup
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
          "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($iscc) {
    & $iscc /Q "/DAppVersion=$version" "$root\installer\woofcleaner.iss"
    if ($LASTEXITCODE -ne 0) { throw 'installer build failed' }
} else {
    Write-Warning 'Inno Setup not found - skipping the installer (winget install JRSoftware.InnoSetup)'
}

Get-ChildItem "$root\dist\*.exe" | Select-Object Name, @{n = 'MB'; e = { [math]::Round($_.Length / 1MB, 1) } }
