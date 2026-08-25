<#
    JARVIS one-step installer for Windows.

    Downloads the release, verifies its SHA-256 against the hash published with
    that release, clears the mark-of-the-web that makes SmartScreen block it,
    and starts the installer.

    The hash check is the point. It is what lets you click past a SmartScreen
    warning knowing the file is the one the build pipeline produced, rather
    than clicking past it and hoping.

    Usage:
        .\install.ps1                # latest release
        .\install.ps1 -Version 1.0.0 # a specific one
#>
[CmdletBinding()]
param(
    [string]$Version = "",
    [string]$Repo = "tcmg5/SUNDAY"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # makes Invoke-WebRequest far faster

function Step($text) { Write-Host "`n  $text" -ForegroundColor Cyan }
function Ok($text)   { Write-Host "  $text" -ForegroundColor Green }
function Bad($text)  { Write-Host "  $text" -ForegroundColor Red }

Write-Host "`n  J.A.R.V.I.S. installer" -ForegroundColor Cyan
Write-Host "  ------------------------------------------------" -ForegroundColor DarkCyan

# ---- 1. Find the release -----------------------------------------------
Step "Looking up the release..."
$api = if ($Version) {
    "https://api.github.com/repos/$Repo/releases/tags/v$Version"
} else {
    "https://api.github.com/repos/$Repo/releases/latest"
}
try {
    $release = Invoke-RestMethod -Uri $api -Headers @{ "User-Agent" = "jarvis-installer" }
} catch {
    Bad "Could not reach GitHub: $($_.Exception.Message)"
    exit 1
}

$asset = $release.assets | Where-Object { $_.name -like "JARVIS-Setup-*.exe" } | Select-Object -First 1
if (-Not $asset) { Bad "That release has no installer attached."; exit 1 }
Ok "Found $($release.tag_name): $($asset.name) ($([math]::Round($asset.size / 1MB)) MB)"

# The expected hash comes from the release itself, published by the same run
# that built the file.
$expected = ""
$sums = $release.assets | Where-Object { $_.name -eq "SHA256SUMS.txt" } | Select-Object -First 1
if ($sums) {
    $text = (Invoke-WebRequest -Uri $sums.browser_download_url -UseBasicParsing).Content
    foreach ($line in $text -split "`n") {
        if ($line -match "^([0-9A-Fa-f]{64})\s+$([regex]::Escape($asset.name))\s*$") {
            $expected = $Matches[1].ToUpper()
        }
    }
} elseif ($asset.digest -and $asset.digest.StartsWith("sha256:")) {
    # Releases built before SHA256SUMS.txt existed still carry a digest.
    $expected = $asset.digest.Substring(7).ToUpper()
}

# ---- 2. Download --------------------------------------------------------
$target = Join-Path $env:TEMP $asset.name
Step "Downloading to $target"
Write-Host "  This is a few hundred megabytes - give it a minute." -ForegroundColor DarkGray
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $target -UseBasicParsing
Ok "Downloaded."

# ---- 3. Verify ----------------------------------------------------------
Step "Verifying the download..."
$actual = (Get-FileHash $target -Algorithm SHA256).Hash.ToUpper()
Write-Host "  sha256: $actual" -ForegroundColor DarkGray

if (-Not $expected) {
    Bad "No published hash to compare against - not proceeding automatically."
    Write-Host "  Check it by hand against the release page, then run:" -ForegroundColor Yellow
    Write-Host "    $target" -ForegroundColor Yellow
    exit 1
}
if ($actual -ne $expected) {
    Bad "HASH MISMATCH - do not run this file."
    Write-Host "  expected: $expected" -ForegroundColor Red
    Write-Host "  actual  : $actual" -ForegroundColor Red
    Remove-Item $target -Force
    exit 1
}
Ok "Hash matches the published release."

# ---- 4. Unblock and run -------------------------------------------------
Step "Clearing the download flag..."
Unblock-File -Path $target
Ok "Cleared. SmartScreen may still ask - see below."

Step "Starting the installer..."
Write-Host ""
Write-Host '  If you see "Windows protected your PC":' -ForegroundColor Yellow
Write-Host "    click More info, then Run anyway." -ForegroundColor Yellow
Write-Host "    The button only appears after clicking More info." -ForegroundColor DarkGray
Write-Host "  The build is unsigned, which is why Windows asks. You just" -ForegroundColor DarkGray
Write-Host "  verified it matches what the build pipeline produced." -ForegroundColor DarkGray
Write-Host ""

Start-Process -FilePath $target -Wait

Write-Host ""
Ok "Installer finished."
Write-Host "  Launch JARVIS from the Start menu, then say 'hey JARVIS'." -ForegroundColor Cyan
Write-Host "  If it will not start: Start menu -> JARVIS diagnostics.`n" -ForegroundColor DarkGray
