# Publish a new Woof Cleaner version to GitHub Releases. Installed copies pick it up automatically.
#
#   1. Bump __version__ in woofcleaner\__init__.py   (e.g. 0.3.0 -> 0.3.1)
#   2. .\release.ps1 -Notes "What changed"
#
# Needs: git remote 'origin' pointing at the UPDATE_REPO, and GitHub CLI logged in (gh auth login).
param(
    [string]$Notes = '',
    [switch]$Draft
)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
Set-Location $root

$version = (Select-String -Path "$root\woofcleaner\__init__.py" -Pattern '__version__ = "([^"]+)"').Matches[0].Groups[1].Value
$repo = (Select-String -Path "$root\woofcleaner\__init__.py" -Pattern 'UPDATE_REPO = "([^"]*)"').Matches[0].Groups[1].Value
$tag = "v$version"
if (-not $repo) { throw 'Set UPDATE_REPO in woofcleaner\__init__.py first.' }
$gh = (Get-Command gh -ErrorAction SilentlyContinue).Source
if (-not $gh -and (Test-Path "$env:ProgramFiles\GitHub CLI\gh.exe")) { $gh = "$env:ProgramFiles\GitHub CLI\gh.exe" }
if (-not $gh) { throw 'Install GitHub CLI: winget install GitHub.cli, then gh auth login' }
& $gh auth status *> $null
if ($LASTEXITCODE -ne 0) { throw 'Not logged in to GitHub: run  gh auth login' }
if (git status --porcelain) { throw 'Commit your changes first (git status is not clean).' }
if (git tag --list $tag) { throw "Tag $tag already exists - bump __version__ first." }

& "$root\build.ps1"

$files = @("WoofCleaner-Setup-$version.exe", 'WoofCleaner.exe', 'woof.exe')
foreach ($f in $files) { if (-not (Test-Path "$root\dist\$f")) { throw "missing dist\$f" } }
$sums = foreach ($f in $files) { '{0}  {1}' -f (Get-FileHash "$root\dist\$f" -Algorithm SHA256).Hash.ToLower(), $f }
[IO.File]::WriteAllLines("$root\dist\SHA256SUMS.txt", [string[]]$sums)

git tag -a $tag -m "Woof Cleaner $version"
git push origin HEAD $tag

$assets = ($files + 'SHA256SUMS.txt') | ForEach-Object { "$root\dist\$_" }
$ghArgs = @('release', 'create', $tag) + $assets + @('--repo', $repo, '--title', "Woof Cleaner $version")
if ($Notes) { $ghArgs += @('--notes', $Notes) } else { $ghArgs += '--generate-notes' }
if ($Draft) { $ghArgs += '--draft' }
& $gh @ghArgs
if ($LASTEXITCODE -ne 0) { throw 'gh release create failed' }
Write-Host "Published $tag - installed copies will offer the update on their next start (checks once a day)."
