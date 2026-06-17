#!/bin/zsh
set -euo pipefail

APP_DIR="/Users/phuonganh/Desktop/BaoNgoc-MarketingStudio/hsk_marketing_studio"
PORT=8501

if lsof -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  open "http://localhost:${PORT}"
  exit 0
fi

"$APP_DIR/scripts/run_macos_app.command"
