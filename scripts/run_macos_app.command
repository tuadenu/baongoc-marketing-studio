#!/bin/zsh
set -euo pipefail

APP_DIR="/Users/phuonganh/Desktop/BaoNgoc-MarketingStudio/hsk_marketing_studio"
PORT=8501

cd "$APP_DIR"
source venv/bin/activate

if lsof -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  open "http://localhost:${PORT}"
  exit 0
fi

streamlit run app.py --server.port "$PORT" >/tmp/hsk_marketing_studio_streamlit.log 2>&1 &
sleep 3
open "http://localhost:${PORT}"
