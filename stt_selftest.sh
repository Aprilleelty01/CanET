#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUN_DIR="$ROOT_DIR/.run"
BACKEND_LOG="$RUN_DIR/selftest_backend.log"
BACKEND_PORT="8000"

mkdir -p "$RUN_DIR"

if [[ -x "$ROOT_DIR/venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT_DIR/venv/bin/python"
elif [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
else
  echo "Project virtualenv not found (.venv or venv)."
  exit 1
fi

started_backend=0
backend_pid=""

cleanup() {
  if [[ "$started_backend" == "1" ]] && [[ -n "$backend_pid" ]]; then
    kill "$backend_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

backend_health_ok() {
  curl -fsS "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null 2>&1
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

cd "$ROOT_DIR"

if backend_health_ok; then
  echo "[SELFTEST] Reusing existing backend on :${BACKEND_PORT}."
else
  echo "[SELFTEST] Starting temporary backend..."
  nohup bash -lc "cd '$ROOT_DIR/backend' && env PYTHONPATH='$ROOT_DIR:${PYTHONPATH:-}' '$PYTHON_BIN' -m uvicorn main:app --host 127.0.0.1 --port '$BACKEND_PORT'" >"$BACKEND_LOG" 2>&1 &
  backend_pid="$!"
  started_backend=1
  if ! wait_for_backend; then
    echo "[SELFTEST] FAIL: backend did not start. Log: $BACKEND_LOG"
    exit 1
  fi
fi

echo "[SELFTEST] /health"
curl -fsS "http://127.0.0.1:${BACKEND_PORT}/health" && echo

echo "[SELFTEST] /speech_to_text_health"
curl -fsS "http://127.0.0.1:${BACKEND_PORT}/speech_to_text_health" && echo

echo "[SELFTEST] generating /tmp/stt_test.wav"
"$PYTHON_BIN" - <<'PY'
import math
import wave
import struct
path = "/tmp/stt_test.wav"
rate = 16000
dur = 1.0
freq = 440.0
n = int(rate * dur)
with wave.open(path, "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(rate)
    for i in range(n):
        v = int(0.25 * 32767 * math.sin(2 * math.pi * freq * (i / rate)))
        w.writeframes(struct.pack("<h", v))
print(path)
PY

echo "[SELFTEST] POST /speech_to_text"
response="$(curl -fsS -F "file=@/tmp/stt_test.wav" "http://127.0.0.1:${BACKEND_PORT}/speech_to_text")"
echo "$response"

echo "[SELFTEST] done"
