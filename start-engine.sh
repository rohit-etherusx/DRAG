#!/usr/bin/env bash
#
# start-engine.sh — run the whole Research Engine locally: the FastAPI backend
# and the React/Vite web frontend, together, with one command.
#
#   ./start-engine.sh            launch backend + frontend (default)
#   ./start-engine.sh stop       stop both (from any terminal)
#   ./start-engine.sh status     show what's running
#   ./start-engine.sh restart    stop, then start again
#
# HOW TO STOP:
#   • Press Ctrl+C in the terminal where it's running, OR
#   • run  ./start-engine.sh stop  from another terminal.
#
# Config (override with env vars):
#   RE_API_HOST (127.0.0.1)  RE_API_PORT (8000)  RE_UI_PORT (5173)
#
set -euo pipefail

# --- configuration ----------------------------------------------------------
BACKEND_HOST="${RE_API_HOST:-127.0.0.1}"
BACKEND_PORT="${RE_API_PORT:-8000}"
FRONTEND_PORT="${RE_UI_PORT:-5173}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UI_DIR="$ROOT/ui"
RUN_DIR="$ROOT/.run"
LOG_DIR="$RUN_DIR/logs"
BE_PID_FILE="$RUN_DIR/backend.pid"
FE_PID_FILE="$RUN_DIR/frontend.pid"

# Some setups keep Node in a user-local prefix that isn't on the default PATH.
export PATH="$HOME/.local/bin:$PATH"

# --- pretty output ----------------------------------------------------------
if [ -t 1 ]; then
  BOLD=$'\033[1m'; GRN=$'\033[32m'; YEL=$'\033[33m'; RED=$'\033[31m'; CYN=$'\033[36m'; RST=$'\033[0m'
else
  BOLD=""; GRN=""; YEL=""; RED=""; CYN=""; RST=""
fi
info() { printf '%s %s\n' "${CYN}▸${RST}" "$*"; }
ok()   { printf '%s %s\n' "${GRN}✓${RST}" "$*"; }
warn() { printf '%s %s\n' "${YEL}!${RST}" "$*"; }
err()  { printf '%s %s\n' "${RED}✗${RST}" "$*" >&2; }

# --- helpers ----------------------------------------------------------------
# Kill a process and all of its descendants (uv→uvicorn, npm→vite→esbuild).
kill_tree() {
  local pid=$1 child
  for child in $(pgrep -P "$pid" 2>/dev/null || true); do
    kill_tree "$child"
  done
  kill "$pid" 2>/dev/null || true
}

is_running() {  # is_running <pidfile>
  local pid
  [ -f "$1" ] || return 1
  pid="$(cat "$1" 2>/dev/null || true)"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

stop_one() {    # stop_one <name> <pidfile>
  if is_running "$2"; then
    local pid; pid="$(cat "$2")"
    info "stopping $1 (pid $pid)…"
    kill_tree "$pid"
  fi
  rm -f "$2"
}

stop() {
  stop_one "frontend" "$FE_PID_FILE"
  stop_one "backend"  "$BE_PID_FILE"
}

status() {
  if is_running "$BE_PID_FILE"; then
    ok   "backend  running (pid $(cat "$BE_PID_FILE"))  →  http://$BACKEND_HOST:$BACKEND_PORT"
  else
    warn "backend  not running"
  fi
  if is_running "$FE_PID_FILE"; then
    ok   "frontend running (pid $(cat "$FE_PID_FILE"))  →  http://localhost:$FRONTEND_PORT"
  else
    warn "frontend not running"
  fi
}

require() { command -v "$1" >/dev/null 2>&1 || { err "'$1' not found — $2"; exit 1; }; }

TAIL_PID=""
shutdown() {
  trap - INT TERM
  printf '\n'
  info "shutting down…"
  [ -n "$TAIL_PID" ] && kill "$TAIL_PID" 2>/dev/null || true
  stop
  ok "all stopped."
  exit 0
}

# --- start ------------------------------------------------------------------
start() {
  if is_running "$BE_PID_FILE" || is_running "$FE_PID_FILE"; then
    warn "already running. Use '$0 restart', or '$0 stop' first."
    status
    exit 0
  fi

  require uv  "install it from https://docs.astral.sh/uv/"
  require npm "install Node.js — the ui/ frontend needs it"

  mkdir -p "$LOG_DIR"

  # Sync all extras (api + tui) so this never uninstalls a dependency you
  # already had — it only ensures fastapi/uvicorn are present for the backend.
  info "syncing backend deps (fastapi + uvicorn)…"
  uv sync --all-extras >/dev/null

  if [ ! -d "$UI_DIR/node_modules" ]; then
    info "installing frontend deps (first run — this can take a minute)…"
    ( cd "$UI_DIR" && npm install >/dev/null 2>&1 )
  fi

  # --- backend ---
  info "starting backend on http://$BACKEND_HOST:$BACKEND_PORT …"
  RE_API_HOST="$BACKEND_HOST" RE_API_PORT="$BACKEND_PORT" \
    uv run research-engine-api >"$LOG_DIR/backend.log" 2>&1 &
  echo $! > "$BE_PID_FILE"

  # Wait until it answers /health so the frontend never races an empty backend.
  if command -v curl >/dev/null 2>&1; then
    local tries=0
    until curl -sf "http://$BACKEND_HOST:$BACKEND_PORT/health" >/dev/null 2>&1; do
      tries=$((tries + 1))
      if ! is_running "$BE_PID_FILE"; then
        err "backend exited on startup — see $LOG_DIR/backend.log"; stop; exit 1
      fi
      if [ "$tries" -gt 60 ]; then
        err "backend didn't become healthy in time — see $LOG_DIR/backend.log"; stop; exit 1
      fi
      sleep 0.5
    done
    ok "backend healthy"
  else
    warn "curl not found — skipping health check"; sleep 2
  fi

  # --- frontend ---
  info "starting frontend on http://localhost:$FRONTEND_PORT …"
  ( cd "$UI_DIR" && VITE_API_TARGET="http://$BACKEND_HOST:$BACKEND_PORT" \
      npm run dev -- --port "$FRONTEND_PORT" --strictPort ) >"$LOG_DIR/frontend.log" 2>&1 &
  echo $! > "$FE_PID_FILE"

  printf '\n'
  ok "Research Engine is up."
  printf '   %sWeb app%s   http://localhost:%s\n'        "$BOLD" "$RST" "$FRONTEND_PORT"
  printf '   %sAPI%s       http://%s:%s   (Swagger at /docs)\n' "$BOLD" "$RST" "$BACKEND_HOST" "$BACKEND_PORT"
  printf '   %sLogs%s      %s/backend.log · %s/frontend.log\n'  "$BOLD" "$RST" "$LOG_DIR" "$LOG_DIR"
  printf '\n   %sStop:%s press %sCtrl+C%s here, or run %s%s stop%s from another terminal.\n\n' \
         "$BOLD" "$RST" "$BOLD" "$RST" "$CYN" "$0" "$RST"

  # Stay in the foreground streaming both logs; Ctrl+C shuts everything down.
  trap shutdown INT TERM
  tail -n +1 -f "$LOG_DIR/backend.log" "$LOG_DIR/frontend.log" &
  TAIL_PID=$!
  wait "$TAIL_PID" || true
}

# --- dispatch ---------------------------------------------------------------
case "${1:-start}" in
  start)   start ;;
  stop)    stop; ok "stopped." ;;
  status)  status ;;
  restart) stop; sleep 1; start ;;
  -h|--help|help)
    grep '^#' "$0" | sed 's/^# \{0,1\}//' | sed '1d'
    ;;
  *) err "unknown command: $1"; echo "usage: $0 [start|stop|status|restart]"; exit 1 ;;
esac
