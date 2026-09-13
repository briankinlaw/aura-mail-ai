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

# Check for local trusted development TLS certificate (Phase 2.1 Fail-Closed Invariant)
CERT_FILE="${AURA_SSL_CERT:-$HOME/.aura_certs/localhost.pem}"
KEY_FILE="${AURA_SSL_KEY:-$HOME/.aura_certs/localhost-key.pem}"

if [ ! -f "$CERT_FILE" ] || [ ! -f "$KEY_FILE" ]; then
    echo "=========================================================="
    echo "❌ FATAL: Missing local TLS certificate or private key."
    echo "Aura Mail AI canonical origin https://localhost:8000 requires HTTPS."
    echo "Expected certificate: $CERT_FILE"
    echo "Expected private key:  $KEY_FILE"
    echo ""
    echo "💡 To generate local development certificates with mkcert:"
    echo "   mkdir -p ~/.aura_certs"
    echo "   mkcert -install"
    echo "   mkcert -key-file ~/.aura_certs/localhost-key.pem -cert-file ~/.aura_certs/localhost.pem localhost 127.0.0.1"
    echo ""
    echo "Alternatively, export AURA_SSL_CERT and AURA_SSL_KEY environment variables."
    echo "=========================================================="
    exit 1
fi

SSL_FLAGS="--ssl-certfile $CERT_FILE --ssl-keyfile $KEY_FILE"

echo "=========================================================="
echo "🚀 Launching Aura Mail AI Assistant (FastAPI + Outlook Co-Pilot)"
echo "📍 Canonical HTTPS Origin: https://localhost:8000"
echo "📍 Taskpane URL: https://localhost:8000/add-in/taskpane.html"
echo "=========================================================="

PYTHONPATH=. .venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 $SSL_FLAGS --reload
