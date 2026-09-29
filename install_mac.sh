#!/bin/bash
# macOS setup: installs Python deps via uv and checks optional tools.
cd "$(dirname "$0")"

if ! command -v uv &> /dev/null; then
    echo "[ERROR] uv not found. Install: brew install uv"
    exit 1
fi

echo "[1/3] Installing dependencies (uv sync)..."
uv sync || exit 1

echo "[2/3] Checking API key file..."
if [ -f "$HOME/.secrets/api_keys.env" ]; then
    echo "  [OK] ~/.secrets/api_keys.env found (OPENAI_API_KEY is read from here)."
else
    echo "  [WARNING] ~/.secrets/api_keys.env not found. Create it with OPENAI_API_KEY=..."
fi

echo "[3/3] Checking optional tools..."
if [ -d "/Library/Audio/Plug-Ins/HAL/BlackHole2ch.driver" ]; then
    echo "  [OK] BlackHole found (only needed to caption system audio)."
else
    echo "  [INFO] BlackHole not installed. Not needed for microphone input."
    echo "         To caption system audio: brew install blackhole-2ch"
fi

if [ ! -f config.ini ]; then
    cp config.ini.example config.ini
    echo "Created config.ini from config.ini.example"
fi

echo "Done. Run ./start_mac.sh"
