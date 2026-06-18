#!/bin/zsh
set -u

APP_DIR="/Users/phuonganh/Desktop/BaoNgoc-MarketingStudio/hsk_marketing_studio"
VENV_DIR="$APP_DIR/venv"
VENV_PY="$VENV_DIR/bin/python"
PORT=8501
LOG_FILE="/tmp/hsk_marketing_studio_streamlit.log"
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/local/sbin:/opt/homebrew/sbin:$PATH"
export HOME="${HOME:-/Users/phuonganh}"
if [ -x /usr/local/bin/gcloud ]; then
  export GCLOUD_BIN="/usr/local/bin/gcloud"
elif [ -x /opt/homebrew/bin/gcloud ]; then
  export GCLOUD_BIN="/opt/homebrew/bin/gcloud"
fi

open_url() {
  local url="$1"
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$url" <<'PY'
import sys, webbrowser
url = sys.argv[1]
try:
    if webbrowser.open(url, new=0, autoraise=True):
        raise SystemExit(0)
except Exception:
    pass
raise SystemExit(1)
PY
    return 0
  fi
  if open "$url" >/dev/null 2>&1; then
    return 0
  fi
  if open -a "Google Chrome" "$url" >/dev/null 2>&1; then
    return 0
  fi
  open -a "Safari" "$url" >/dev/null 2>&1
}

wait_for_server() {
  local url="http://localhost:${PORT}"
  for _ in {1..60}; do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

kill_port() {
  local pids
  pids="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)"
  if [ -n "$pids" ]; then
    echo "$pids" | xargs kill >/dev/null 2>&1 || true
    sleep 2
    pids="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)"
    if [ -n "$pids" ]; then
      echo "$pids" | xargs kill -9 >/dev/null 2>&1 || true
    fi
  fi
  pids="$(pgrep -f 'hsk_marketing_studio.*streamlit' 2>/dev/null || true)"
  if [ -n "$pids" ]; then
    echo "$pids" | xargs kill >/dev/null 2>&1 || true
    sleep 1
    pids="$(pgrep -f 'hsk_marketing_studio.*streamlit' 2>/dev/null || true)"
    if [ -n "$pids" ]; then
      echo "$pids" | xargs kill -9 >/dev/null 2>&1 || true
    fi
  fi
}

cd "$APP_DIR" || exit 1
source "$VENV_DIR/bin/activate"

if lsof -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  kill_port
fi

if [ ! -x "$VENV_PY" ]; then
  echo "Khong tim thay virtualenv tai $VENV_PY"
  exit 1
fi

nohup /bin/zsh -lc "cd '$APP_DIR' && source '$VENV_DIR/bin/activate' && exec '$VENV_PY' -m streamlit run app.py --server.port '$PORT' --server.headless true" >"$LOG_FILE" 2>&1 &

if wait_for_server; then
  open_url "http://localhost:${PORT}"
else
  echo "Streamlit chua khoi dong xong. Xem log: $LOG_FILE"
  tail -n 50 "$LOG_FILE"
  exit 1
fi
