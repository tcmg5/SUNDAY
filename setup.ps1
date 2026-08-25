# One-shot setup for Windows. Run in PowerShell from the project folder.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "── JARVIS setup ──────────────────────────────────" -ForegroundColor Cyan

if (-Not (Test-Path .venv)) {
    Write-Host "Creating virtual environment..."
    python -m venv .venv
}
& .\.venv\Scripts\Activate.ps1

Write-Host "Installing Python packages (a few minutes — whisper and Qt are large)..."
python -m pip install --quiet --upgrade pip
pip install -r requirements.txt

if (-Not (Test-Path config.yaml)) { Copy-Item config.example.yaml config.yaml; Write-Host "Created config.yaml" }
if (-Not (Test-Path .env)) { Copy-Item .env.example .env; Write-Host "Created .env — put your ANTHROPIC_API_KEY in it" }

Write-Host "`nDownloading the wake word model..."
python -c "import openwakeword.utils; openwakeword.utils.download_models()"

Write-Host "Downloading the voice..."
python -c "from jarvis.config import load_config; from jarvis.audio.tts import ensure_piper_voice; ensure_piper_voice(load_config()['tts']['piper_voice'])"

Write-Host "`n──────────────────────────────────────────────────" -ForegroundColor Cyan
Write-Host "Done. Next:"
Write-Host "  1. Put your Anthropic API key in .env"
Write-Host "  2. .\.venv\Scripts\Activate.ps1"
Write-Host "  3. python -m jarvis doctor"
Write-Host "  4. python -m jarvis"
