#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
python -m pip install -r requirements.txt

if [ ! -f ".env" ]; then
  cp .env.example .env
fi

echo "Privacy AI Gateway v$(cat VERSION)"
echo "Mo trinh duyet tai http://127.0.0.1:8000"
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
