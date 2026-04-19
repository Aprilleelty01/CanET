#!/usr/bin/env bash
set -euo pipefail

# One-click launcher for the Streamlit webpage UI.
# Usage:
#   ./launch_webpage.command desktop   # default
#   ./launch_webpage.command ipad
#   ./launch_webpage.command stop

MODE="${1:-desktop}"
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUN_DIR="$ROOT_DIR/.run"
BACKEND_PID_FILE="$RUN_DIR/webpage_backend.pid"
STREAMLIT_PID_FILE="$RUN_DIR/webpage_streamlit.pid"
BACKEND_LOG="$RUN_DIR/webpage_backend.log"
STREAMLIT_LOG="$RUN_DIR/webpage_streamlit.log"
BACKEND_PORT="8000"
STREAMLIT_PORT="8510"

mkdir -p "$RUN_DIR"

ensure_venv() {
  if [[ -x "$ROOT_DIR/venv/bin/python" ]]; then
    PYTHON_BIN="$ROOT_DIR/venv/bin/python"
    return 0
  fi

  if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
    PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
    return 0
  fi

  if command -v python3 >/dev/null 2>&1; then
    echo "Project virtualenv not found. Creating .venv and installing requirements..."
    python3 -m venv "$ROOT_DIR/.venv"
    "$ROOT_DIR/.venv/bin/python" -m pip install --upgrade pip >/dev/null
    "$ROOT_DIR/.venv/bin/python" -m pip install -r "$ROOT_DIR/requirements.txt"
    PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
    return 0
  fi

  echo "Project virtualenv not found (.venv or venv), and python3 is unavailable."
  echo "Please create one manually:"
  echo "  python3 -m venv .venv"
  echo "  . .venv/bin/activate"
  echo "  pip install -r requirements.txt"
  exit 1
}

ensure_venv

kill_if_running() {
  local pid_file="$1"
  if [[ -f "$pid_file" ]]; then
    local pid
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
    rm -f "$pid_file"
  fi
}

backend_health_ok() {
  curl -fsS "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null 2>&1
}

start_backend() {
  local host="$1"
  if backend_health_ok; then
    echo "Reusing existing backend on :${BACKEND_PORT}."
    return 0
  fi
  local attempts=0
  while [[ $attempts -lt 10 ]]; do
    if backend_health_ok; then
      echo "Reusing existing backend on :${BACKEND_PORT}."
      return 0
    fi
    attempts=$((attempts + 1))
    sleep 1
  done

  if backend_health_ok; then
    echo "Reusing existing backend on :${BACKEND_PORT}."
    return 0
  fi

  local listener_pid
  listener_pid="$(lsof -tiTCP:"$BACKEND_PORT" -sTCP:LISTEN 2>/dev/null | head -n1 || true)"
  if [[ -n "$listener_pid" ]]; then
    kill "$listener_pid" 2>/dev/null || true
    sleep 1
  fi

  nohup bash -lc "cd '$ROOT_DIR/backend' && env PYTHONPATH='$ROOT_DIR:${PYTHONPATH:-}' '$PYTHON_BIN' -m uvicorn main:app --host '$host' --port '$BACKEND_PORT'" >"$BACKEND_LOG" 2>&1 &
  echo $! > "$BACKEND_PID_FILE"
}

start_streamlit() {
  local host="$1"
  nohup env PYTHONPATH="$ROOT_DIR:${PYTHONPATH:-}" \
    "$PYTHON_BIN" -m streamlit run "$ROOT_DIR/webpage/streamlit_app.py" \
    --server.headless true --server.address "$host" --server.port "$STREAMLIT_PORT" \
    >"$STREAMLIT_LOG" 2>&1 &
  echo $! > "$STREAMLIT_PID_FILE"
}
cd "$ROOT_DIR"

wait_for_backend() {
  local attempts=0
  while [[ $attempts -lt 60 ]]; do
    if curl -fsS "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null 2>&1; then
      return 0
    fi
    attempts=$((attempts + 1))
    sleep 1
  done
  return 1
}

wait_for_streamlit() {
  local host="$1"
  local attempts=0
  local url="http://${host}:${STREAMLIT_PORT}"
  while [[ $attempts -lt 60 ]]; do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    attempts=$((attempts + 1))
    sleep 1
  done
  return 1
}

find_lan_ip() {
  ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "127.0.0.1"
}

stt_preflight() {
  local url="http://127.0.0.1:${BACKEND_PORT}/speech_to_text_health"
  local payload
  if ! payload="$(curl -fsS "$url" 2>/dev/null)"; then
    echo "[STT] 預檢失敗：未能連線 speech_to_text_health"
    return 0
  fi

  local status_line
  status_line="$(printf '%s' "$payload" | "$PYTHON_BIN" -c 'import sys,json
try:
 d=json.load(sys.stdin)
 r=str(d.get("ready", False)).lower()
 m=d.get("mode","unknown")
 msg=d.get("message","")
 print(f"{r}|{m}|{msg}")
except Exception:
 print("false|unknown|invalid json")')"

  local ready mode msg
  ready="${status_line%%|*}"
  mode="${status_line#*|}"
  mode="${mode%%|*}"
  msg="${status_line##*|}"

  if [[ "$ready" == "true" ]]; then
    echo "[STT] 已就緒：$mode${msg:+ | $msg}"
  else
    echo "[STT] 未就緒：$mode${msg:+ | $msg}"
    echo "[STT] 提示：可先設定 WHISPER_CPP_MODEL 啟用離線 whisper.cpp，或用 HF 後備。"
  fi
}

open_browser() {
  local url="$1"
  if [[ "${NO_OPEN_BROWSER:-0}" == "1" ]]; then
    echo "NO_OPEN_BROWSER=1，略過自動開啟瀏覽器。"
    return 0
  fi
  if command -v open >/dev/null 2>&1; then
    if open -Ra "Google Chrome" >/dev/null 2>&1; then
      open -a "Google Chrome" "$url"
      return 0
    fi

    if open -Ra "Safari" >/dev/null 2>&1; then
      open -a "Safari" "$url"
      return 0
    fi

    open "$url"
    return 0
  fi

  echo "Open manually: $url"
}

if [[ "${DRY_RUN:-0}" == "1" ]]; then
  cat <<EOF
Python: $PYTHON_BIN
Will run: $PYTHON_BIN -m uvicorn backend.main:app --host 127.0.0.1 --port $BACKEND_PORT
Will run: $PYTHON_BIN -m streamlit run webpage/streamlit_app.py --server.headless true --server.address 127.0.0.1 --server.port $STREAMLIT_PORT
Browser priority: Safari -> Google Chrome -> default
EOF
  exit 0
fi

stop_all() {
  kill_if_running "$BACKEND_PID_FILE"
  kill_if_running "$STREAMLIT_PID_FILE"
  echo "Stopped webpage services."
}

case "$MODE" in
  stop)
    stop_all
    exit 0
    ;;
  desktop)
    stop_all
    start_backend "127.0.0.1"
    if ! wait_for_backend; then
      echo "Backend failed to start. Check: $BACKEND_LOG"
      exit 1
    fi
    stt_preflight
    start_streamlit "127.0.0.1"
    if ! wait_for_streamlit "127.0.0.1"; then
      echo "Streamlit failed to start. Check: $STREAMLIT_LOG"
      exit 1
    fi
    URL="http://127.0.0.1:${STREAMLIT_PORT}"
    open_browser "$URL" || true
    cat <<EOF
Webpage launcher is running.

Open: $URL
Backend API: http://127.0.0.1:${BACKEND_PORT}

To stop:
  ./launch_webpage.command stop
EOF
    ;;
  ipad)
    stop_all
    LAN_IP="$(find_lan_ip)"
    start_backend "0.0.0.0"
    if ! wait_for_backend; then
      echo "Backend failed to start. Check: $BACKEND_LOG"
      exit 1
    fi
    stt_preflight
    start_streamlit "0.0.0.0"
    if ! wait_for_streamlit "127.0.0.1"; then
      echo "Streamlit failed to start. Check: $STREAMLIT_LOG"
      exit 1
    fi
    URL="http://${LAN_IP}:${STREAMLIT_PORT}"
    open_browser "$URL" || true
    cat <<EOF
Webpage launcher is running in iPad mode.

On iPad (same Wi-Fi), open:
  $URL

Backend API:
  http://${LAN_IP}:${BACKEND_PORT}

To stop:
  ./launch_webpage.command stop
EOF
    ;;
  *)
    echo "Unknown mode: $MODE"
    echo "Usage: ./launch_webpage.command [desktop|ipad|stop]"
    exit 1
    ;;
esac
