#!/bin/bash
# Mac-da işə sal: ./run.sh   → API http://localhost:8000, panel http://localhost:8501
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "Virtual mühit yaradılır (bir dəfəlik, 1–2 dəqiqə)…"
  python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt || exit 1
fi
.venv/bin/uvicorn backend.main:app --port 8000 &
API=$!
trap "kill $API 2>/dev/null" EXIT
.venv/bin/streamlit run ui/app.py --server.port 8501
