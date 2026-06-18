#!/bin/zsh
set -u

APP_DIR="/Users/phuonganh/Desktop/BaoNgoc-MarketingStudio/hsk_marketing_studio"
PORT=8501
RUNNER="$APP_DIR/scripts/run_macos_app.command"
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/local/sbin:/opt/homebrew/sbin:$PATH"

if lsof -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  open "http://localhost:${PORT}" >/dev/null 2>&1 || /bin/zsh -lc 'python3 - <<'"'"'PY'"'"'
import webbrowser
webbrowser.open("http://localhost:8501", new=0, autoraise=True)
PY'
  exit 0
fi

exec /bin/zsh "$RUNNER"
