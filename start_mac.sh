#!/bin/bash
# Launch the dashboard with hot reload. Dependencies are managed by uv.
cd "$(dirname "$0")"

if ! command -v uv &> /dev/null; then
    echo "[ERROR] uv not found. Install: brew install uv"
    exit 1
fi

echo "[Launcher] Starting App (Hot Reload Mode)..."
exec uv run python reloader.py
