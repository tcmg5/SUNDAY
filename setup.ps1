<#
  JARVIS setup for Windows.

  Run it by right-clicking this file and choosing "Run with PowerShell".
  If Windows refuses because scripts are disabled, open PowerShell in this
  folder and run:

      Set-ExecutionPolicy -Scope Process -Bypass -Force
      .\setup.ps1

  That relaxes the policy for one session only and changes nothing permanently.
#>
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Say($text, $colour = "Gray") { Write-Host $text -ForegroundColor $colour }

Say "" ; Say "  J.A.R.V.I.S. setup" "Cyan"
Say "  ---------------------------------------------" "DarkCyan"

# ---- 1. Find a usable Python ------------------------------------------
$python = $null
foreach ($candidate in @("python", "python3", "py")) {
    try {
        $version = & $candidate --version 2>&1
        if ($version -match "Python (\d+)\.(\d+)") {
            if ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -ge 9) {
                $python = $candidate
                Say "  Python: $version" "Green"
                break
            }
        }
    } catch { }
}
if (-not $python) {
    Say "  Python 3.9 or newer was not found." "Red"
    Say ""
    Say "  Install it from https://python.org/downloads - and on the first"
    Say "  screen of the installer, tick 'Add python.exe to PATH'." "Yellow"
    Say "  Then run this script again."
    Read-Host "`n  Press Enter to close"
    exit 1
}

# ---- 2. Virtual environment -------------------------------------------
if (-Not (Test-Path .venv)) {
    Say "  Creating the virtual environment..."
    & $python -m venv .venv
}
$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-Not (Test-Path $venvPython)) {
    Say "  The virtual environment did not build correctly." "Red"
    Read-Host "`n  Press Enter to close"
    exit 1
}

# ---- 3. Dependencies ---------------------------------------------------
Say "  Installing packages. This takes several minutes - Qt and Whisper"
Say "  are large downloads. Leave it running." "DarkGray"
& $venvPython -m pip install --quiet --upgrade pip
& $venvPython -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Say "  Package installation failed. The output above says which one." "Red"
    Read-Host "`n  Press Enter to close"
    exit 1
}
Say "  Packages installed." "Green"

# ---- 4. Config files ---------------------------------------------------
if (-Not (Test-Path config.yaml)) { Copy-Item config.example.yaml config.yaml; Say "  Created config.yaml" "Green" }
if (-Not (Test-Path .env))        { Copy-Item .env.example .env;               Say "  Created .env" "Green" }

# ---- 5. Models ---------------------------------------------------------
Say "  Downloading the wake word model..."
& $venvPython -c "import openwakeword.utils; openwakeword.utils.download_models()"

Say "  Downloading the voice..."
& $venvPython -c "from jarvis.config import load_config; from jarvis.audio.tts import ensure_piper_voice; ensure_piper_voice(load_config()['tts']['piper_voice'])"

# ---- 6. Desktop shortcut ----------------------------------------------
try {
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath("Desktop")) "JARVIS.lnk"))
    $link.TargetPath = Join-Path $PSScriptRoot ".venv\Scripts\pythonw.exe"
    $link.Arguments = "-m jarvis"
    $link.WorkingDirectory = $PSScriptRoot
    $link.Description = "JARVIS command center"
    $link.Save()
    Say "  Put a JARVIS shortcut on your desktop." "Green"
} catch {
    Say "  Could not create the desktop shortcut - use JARVIS.bat instead." "Yellow"
}

# ---- 7. Done -----------------------------------------------------------
Say ""
Say "  ---------------------------------------------" "DarkCyan"
Say "  Setup complete." "Cyan"
Say ""
$key = (Get-Content .env -Raw)
if ($key -match "sk-ant-\.\.\.") {
    Say "  ONE STEP LEFT: open .env in Notepad and replace" "Yellow"
    Say "  ANTHROPIC_API_KEY=sk-ant-... with your real key." "Yellow"
    Say "  Get one at https://console.anthropic.com" "DarkGray"
    Say ""
}
Say "  Then double-click JARVIS.bat, or the desktop shortcut."
Say "  To check everything first:  .\.venv\Scripts\python.exe -m jarvis doctor" "DarkGray"
Read-Host "`n  Press Enter to close"
