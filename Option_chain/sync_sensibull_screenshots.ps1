<#
Copies every Sensibull screenshot taken by the GitHub workflow into a local folder.
Run it as often as you like: it only adds screenshots you do not have yet.

  .\Option_chain\sync_sensibull_screenshots.ps1
  .\Option_chain\sync_sensibull_screenshots.ps1 -Destination D:\Sensibull

The screenshots live on the `sensibull-screenshots` branch of the repository.
A hidden copy of that branch is kept in %LOCALAPPDATA%, and new files are copied
from it into -Destination. Files you delete from -Destination are not touched in
the repository, and nothing is ever deleted or overwritten in -Destination.
#>
param(
    [string]$Destination = (Join-Path $env:USERPROFILE "OneDrive\Pictures\OpenBoard\Sensibull"),
    [string]$Repository = "https://github.com/Nandhagopalac/5paisa.git"
)

$ErrorActionPreference = "Stop"
$cache = Join-Path $env:LOCALAPPDATA "SensibullScreenshotsCache"

if (Test-Path (Join-Path $cache ".git")) {
    git -C $cache pull --ff-only --quiet
} else {
    git clone --branch sensibull-screenshots --single-branch --quiet $Repository $cache
}
if ($LASTEXITCODE -ne 0) { throw "Could not download the screenshots from GitHub." }

New-Item -ItemType Directory -Force -Path $Destination | Out-Null
# /XO skips files you already have. Exit codes 0-7 mean success for robocopy.
robocopy $cache $Destination *.png /E /XD .git /XO /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Copying the screenshots failed (robocopy code $LASTEXITCODE)." }

$count = (Get-ChildItem -Path $Destination -Filter *.png -Recurse).Count
Write-Host "Done. $count screenshots are now in $Destination"
