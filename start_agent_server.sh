#!/usr/bin/env bash
# start_agent_server.sh — start or restart the Oracle Forge Agent HTTP server
# and the nginx proxy that exposes it on port 80.
#
# Usage:
#   ./start_agent_server.sh          # start (or restart if already running)
#   ./start_agent_server.sh stop     # stop both processes
#   ./start_agent_server.sh status   # show running status

set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="${ROOT_DIR}/agent_server.pid"
LOG_FILE="${ROOT_DIR}/agent_server.log"
AGENT_PORT="${AGENT_PORT:-8080}"
NGINX_CONTAINER="oracle-forge-proxy"
NGINX_CONF_DIR="/tmp/nginx-proxy"

# ─────────────────────────── helpers ─────────────────────────────────────────

_is_running() {
  [[ -f "${PID_FILE}" ]] && kill -0 "$(cat "${PID_FILE}")" 2>/dev/null
}

_stop_agent() {
  if _is_running; then
    echo "Stopping agent server (PID $(cat "${PID_FILE}"))…"
    kill "$(cat "${PID_FILE}")" 2>/dev/null || true
    rm -f "${PID_FILE}"
  fi
}

_stop_proxy() {
  docker rm -f "${NGINX_CONTAINER}" >/dev/null 2>&1 || true
}

_start_agent() {
  PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
  [[ -x "${PYTHON_BIN}" ]] || PYTHON_BIN="$(command -v python3)"

  cd "${ROOT_DIR}"
  nohup env AGENT_PORT="${AGENT_PORT}" PYTHONPATH="${ROOT_DIR}" \
    "${PYTHON_BIN}" agent_server.py \
    > "${LOG_FILE}" 2>&1 &
  echo $! > "${PID_FILE}"
  echo "Agent server started (PID $(cat "${PID_FILE}"), port ${AGENT_PORT})"
}

_start_proxy() {
  mkdir -p "${NGINX_CONF_DIR}"
  cat > "${NGINX_CONF_DIR}/default.conf" << 'NGINX'
server {
    listen 80;
    server_name _;
    location / {
        proxy_pass http://host.docker.internal:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 120s;
    }
}
NGINX

  docker run -d \
    --name "${NGINX_CONTAINER}" \
    -p 80:80 \
    --add-host host.docker.internal:host-gateway \
    -v "${NGINX_CONF_DIR}/default.conf:/etc/nginx/conf.d/default.conf:ro" \
    nginx:alpine >/dev/null
  echo "nginx proxy started (port 80 → ${AGENT_PORT})"
}

_wait_healthy() {
  local url="http://127.0.0.1:${AGENT_PORT}/health"
  for _ in {1..15}; do
    if curl -sf --max-time 2 "${url}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

# ─────────────────────────── commands ────────────────────────────────────────

CMD="${1:-start}"

case "${CMD}" in
  stop)
    _stop_agent
    _stop_proxy
    echo "Stopped."
    ;;

  status)
    if _is_running; then
      echo "Agent server  : RUNNING  (PID $(cat "${PID_FILE}"))"
    else
      echo "Agent server  : STOPPED"
    fi
    if docker ps --format '{{.Names}}' | grep -qx "${NGINX_CONTAINER}"; then
      echo "nginx proxy   : RUNNING  (port 80 → ${AGENT_PORT})"
    else
      echo "nginx proxy   : STOPPED"
    fi
    ;;

  start|restart)
    _stop_agent
    _stop_proxy
    _start_agent

    if ! _wait_healthy; then
      echo "ERROR: agent server did not become healthy. Check ${LOG_FILE}"
      exit 1
    fi

    _start_proxy

    echo ""
    echo "✓ Agent is running on port ${AGENT_PORT}"
    echo "  Access locally : http://localhost:${AGENT_PORT}/health"
    echo "  Public access  : See FACILITATOR_GUIDE.md (not in repo)"
    echo ""
    echo "nginx proxy running on port 80 → ${AGENT_PORT}"
    ;;

  *)
    echo "Usage: $0 [start|stop|restart|status]"
    exit 1
    ;;
esac
