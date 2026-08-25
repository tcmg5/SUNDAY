#!/usr/bin/env bash
# One-shot setup for macOS and Linux.
set -euo pipefail
cd "$(dirname "$0")"

echo "── JARVIS setup ──────────────────────────────────"

# PortAudio is a C library; sounddevice is only a binding to it.
if [[ "$OSTYPE" == "darwin"* ]]; then
  if ! brew list portaudio &>/dev/null 2>&1; then
    echo "Installing portaudio (needed for the microphone)..."
    brew install portaudio
  fi
elif command -v apt-get &>/dev/null; then
  echo "Installing system audio libraries (may prompt for sudo)..."
  sudo apt-get update -qq
  sudo apt-get install -y portaudio19-dev python3-dev libxcb-cursor0 espeak-ng
fi

if [ ! -d .venv ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi
source .venv/bin/activate

echo "Installing Python packages (a few minutes — whisper and Qt are large)..."
pip install --quiet --upgrade pip
pip install -r requirements.txt

[ -f config.yaml ] || { cp config.example.yaml config.yaml; echo "Created config.yaml"; }
[ -f .env ] || { cp .env.example .env; echo "Created .env — put your ANTHROPIC_API_KEY in it"; }

echo
echo "Downloading the wake word model..."
python -c "import openwakeword.utils; openwakeword.utils.download_models()" 2>/dev/null || true

echo "Downloading the voice..."
python -c "
from jarvis.config import load_config
from jarvis.audio.tts import ensure_piper_voice
ensure_piper_voice(load_config()['tts']['piper_voice'])
" || echo "  (voice will download on first run instead)"

echo
echo "──────────────────────────────────────────────────"
echo "Done. Next:"
echo "  1. Put your Anthropic API key in .env"
echo "  2. source .venv/bin/activate"
echo "  3. python -m jarvis doctor      # verify everything"
echo "  4. python -m jarvis             # go"
