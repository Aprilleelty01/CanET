#!/usr/bin/env bash
set -euo pipefail

# One-click launcher for desktop preview, native macOS app, or iPad web app.
# Usage:
#   ./launch_app.command desktop   # default
#   ./launch_app.command macos
#   ./launch_app.command ipad
#   ./launch_app.command stop

MODE="${1:-desktop}"
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUN_DIR="$ROOT_DIR/.run"
BACKEND_PID_FILE="$RUN_DIR/backend.pid"
WEB_PID_FILE="$RUN_DIR/web.pid"
BACKEND_LOG="$RUN_DIR/backend.log"
WEB_LOG="$RUN_DIR/web.log"
BACKEND_PORT="8000"
WEB_PORT="7361"

mkdir -p "$RUN_DIR"

ensure_venv() {
  if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
    PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
    return 0
  fi

  if [[ -x "$ROOT_DIR/venv/bin/python" ]]; then
    PYTHON_BIN="$ROOT_DIR/venv/bin/python"
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

  "$PYTHON_BIN" -m pip install -q fastapi uvicorn python-multipart >/dev/null
  nohup "$PYTHON_BIN" -m uvicorn backend.main:app --app-dir "$ROOT_DIR" --host "$host" --port "$BACKEND_PORT" >"$BACKEND_LOG" 2>&1 &
  echo $! > "$BACKEND_PID_FILE"
}

wait_for_backend() {
  local attempts=0
  while [[ $attempts -lt 60 ]]; do
    if backend_health_ok; then
      return 0
    fi
    attempts=$((attempts + 1))
    sleep 1
  done
  return 1
}

start_web_server() {
  local host="$1"
  pushd "$ROOT_DIR/mobile" >/dev/null
  flutter pub get >/dev/null
  # Disable PWA cache to avoid stale, previously cached builds.
  flutter build web --pwa-strategy=none >/dev/null
  popd >/dev/null

  pushd "$ROOT_DIR/mobile/build/web" >/dev/null
  nohup "$PYTHON_BIN" -m http.server "$WEB_PORT" --bind "$host" >"$WEB_LOG" 2>&1 &
  echo $! > "$WEB_PID_FILE"
  popd >/dev/null
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
  open -a Safari "$url" || open "$url"
}

stop_all() {
  kill_if_running "$BACKEND_PID_FILE"
  kill_if_running "$WEB_PID_FILE"
  echo "Stopped app services."
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
    start_web_server "127.0.0.1"
    URL="http://127.0.0.1:${WEB_PORT}/?v=$(date +%s)"
    open_browser "$URL"
    cat <<EOF
Desktop preview is running.

Open: $URL
Backend API: http://127.0.0.1:${BACKEND_PORT}

To stop:
  ./launch_app.command stop
EOF
    ;;
  macos)
    stop_all
    start_backend "127.0.0.1"
    if ! wait_for_backend; then
      echo "Backend failed to start. Check: $BACKEND_LOG"
      exit 1
    fi
    stt_preflight
    if ! xcrun -f xcodebuild >/dev/null 2>&1; then
      start_web_server "127.0.0.1"
      URL="http://127.0.0.1:${WEB_PORT}"
      open_browser "$URL"
      cat <<EOF
Native macOS app prerequisites are missing (xcodebuild not found).
Started desktop web preview instead.

Open: $URL
Backend API: http://127.0.0.1:${BACKEND_PORT}

To enable native macOS app later:
  1) Install Xcode from App Store
  2) sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer
  3) sudo xcodebuild -runFirstLaunch

To stop:
  ./launch_app.command stop
EOF
      exit 0
    fi

    cat <<EOF
Starting native macOS app...

Backend API: http://127.0.0.1:${BACKEND_PORT}
If app opens but cannot translate, wait 3-5 seconds and tap "Auto Connect" on Home.

To stop backend later:
  ./launch_app.command stop
EOF
    pushd "$ROOT_DIR/mobile" >/dev/null
    flutter pub get
    flutter run -d macos
    popd >/dev/null
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
    start_web_server "0.0.0.0"
    URL="http://${LAN_IP}:${WEB_PORT}/?v=$(date +%s)"
    open_browser "$URL" || true
    cat <<EOF
iPad web app mode is running.

On iPad (same Wi-Fi), open:
  $URL

Backend API:
  http://${LAN_IP}:${BACKEND_PORT}

Tip: In iPad Safari, tap Share -> Add to Home Screen.

To stop:
  ./launch_app.command stop
EOF
    ;;
  *)
    echo "Unknown mode: $MODE"
    echo "Usage: ./launch_app.command [desktop|macos|ipad|stop]"
    exit 1
    ;;
esac
