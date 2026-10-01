#!/bin/bash
# Launch the dashboard. Dependencies are managed by uv.
#   ./start_mac.sh         normal mode (use this in class)
#   ./start_mac.sh --dev   hot reload: restarts the app whenever a .py/.ini file changes
cd "$(dirname "$0")"

if ! command -v uv &> /dev/null; then
    echo "[ERROR] uv not found. Install: brew install uv"
    exit 1
fi

if [ "$1" = "--dev" ]; then
    echo "[Launcher] Starting App (Hot Reload Mode)..."
    exec uv run python reloader.py
fi
echo "[Launcher] Starting App..."
exec uv run python dashboard.py
