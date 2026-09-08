#!/usr/bin/env bash
# Convenience launcher: creates/activates the venv if needed, then runs the app.
set -e

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
    echo "No .venv found — creating one..."
    python3 -m venv .venv
fi

source .venv/bin/activate

if ! python -c "import fastapi" 2>/dev/null; then
    echo "Dependencies not installed yet — installing from requirements.txt..."
    pip install --upgrade pip
    pip install -r requirements.txt
fi

echo "Starting Event Crowd Monitor..."
echo "Dashboard will be available at http://localhost:8000"
python run.py
