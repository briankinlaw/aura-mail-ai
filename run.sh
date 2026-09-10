#!/bin/bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt
fi

# Free up port 8000 if already in use
EXISTING_PID=$(lsof -ti :8000 || true)
if [ -n "$EXISTING_PID" ]; then
    echo "Stopping existing server on port 8000 (PID: $EXISTING_PID)..."
    kill -9 $EXISTING_PID 2>/dev/null || true
    sleep 1
fi

echo "=========================================================="
echo "🚀 Launching Aura Mail AI Assistant (FastAPI + Outlook Co-Pilot)"
echo "📍 Local Web Dashboard: http://127.0.0.1:8000"
echo "=========================================================="

PYTHONPATH=. .venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
