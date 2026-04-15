#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLBOX_BIN="${ROOT_DIR}/bin/toolbox"
TOOLS_CONFIG="${ROOT_DIR}/mcp/tools.yaml"
LOG_FILE="${ROOT_DIR}/toolbox.log"
DUCKDB_LOG_FILE="${ROOT_DIR}/duckdb_mcp.log"
CONTAINER_NAME="${TOOLBOX_CONTAINER_NAME:-team-dab-toolbox}"
TOOLBOX_IMAGE="${TOOLBOX_IMAGE:-ubuntu:22.04}"
DOCKER_NETWORK="${DOCKER_NETWORK:-dab-net}"
TOOLBOX_URL="${TOOLBOX_URL:-http://127.0.0.1:5000}"
DAB_DATASET_ROOT="${DAB_DATASET_ROOT:-${HOME}/DataAgentBench}"
DUCKDB_MCP_URL="${DUCKDB_MCP_URL:-http://127.0.0.1:8001}"
DUCKDB_MCP_PID_FILE="${ROOT_DIR}/duckdb_mcp.pid"

read_env_value() {
  local key="$1"
  local env_file="${ROOT_DIR}/.env"
  if [[ ! -f "${env_file}" ]]; then
    return 1
  fi
  awk -F '=' -v target="${key}" '
    $1 ~ "^[[:space:]]*" target "[[:space:]]*$" {
      value = substr($0, index($0, "=") + 1)
      sub(/^[[:space:]]+/, "", value)
      sub(/[[:space:]]+$/, "", value)
      print value
      exit
    }
  ' "${env_file}"
}

if [[ -z "${TOOLBOX_URL:-}" ]]; then
  TOOLBOX_URL="$(read_env_value TOOLBOX_URL || true)"
  TOOLBOX_URL="${TOOLBOX_URL:-http://127.0.0.1:5000}"
fi

if [[ -z "${DAB_DATASET_ROOT:-}" ]]; then
  DAB_DATASET_ROOT="$(read_env_value DAB_DATASET_ROOT || true)"
  DAB_DATASET_ROOT="${DAB_DATASET_ROOT:-${HOME}/DataAgentBench}"
fi

if [[ -z "${DUCKDB_MCP_URL:-}" ]]; then
  DUCKDB_MCP_URL="$(read_env_value DUCKDB_MCP_URL || true)"
  DUCKDB_MCP_URL="${DUCKDB_MCP_URL:-http://127.0.0.1:8001}"
fi

if [[ ! -x "${TOOLBOX_BIN}" ]]; then
  echo "Toolbox binary not found or not executable: ${TOOLBOX_BIN}"
  exit 1
fi

if [[ ! -f "${TOOLS_CONFIG}" ]]; then
  echo "Toolbox config not found: ${TOOLS_CONFIG}"
  exit 1
fi

if [[ ! -d "${DAB_DATASET_ROOT}" ]]; then
  echo "Dataset root not found: ${DAB_DATASET_ROOT}"
  echo "Set DAB_DATASET_ROOT to the folder that contains query_bookreview/, query_googlelocal/, etc."
  exit 1
fi

stripped_url="${TOOLBOX_URL#http://}"
stripped_url="${stripped_url#https://}"
host_port="${stripped_url%%/*}"
port="${host_port##*:}"

if [[ "${host_port}" == "${port}" ]]; then
  if [[ "${TOOLBOX_URL}" == https://* ]]; then
    port="443"
  else
    port="80"
  fi
fi

docker network inspect "${DOCKER_NETWORK}" >/dev/null 2>&1 || docker network create "${DOCKER_NETWORK}" >/dev/null

for service in team-dab-postgres team-dab-mongo; do
  if docker ps -a --format '{{.Names}}' | grep -qx "${service}"; then
    docker network connect "${DOCKER_NETWORK}" "${service}" >/dev/null 2>&1 || true
  fi
done

docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true

docker run -d \
  --name "${CONTAINER_NAME}" \
  --network "${DOCKER_NETWORK}" \
  -p "${port}:5000" \
  -v "${ROOT_DIR}:/workspace" \
  -v "${DAB_DATASET_ROOT}:/datasets" \
  -w /workspace \
  "${TOOLBOX_IMAGE}" \
  ./bin/toolbox --config mcp/tools.yaml --address 0.0.0.0 --port 5000 --enable-api --ui \
  >/dev/null

health_url="${TOOLBOX_URL%/}/mcp"
startup_ok=false

for _ in {1..15}; do
  if ! docker ps --format '{{.Names}}' | grep -qx "${CONTAINER_NAME}"; then
    break
  fi

  if curl --silent --show-error --fail --max-time 2 \
    -H "Content-Type: application/json" \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
    "${health_url}" >/dev/null 2>&1; then
    startup_ok=true
    break
  fi

  sleep 1
done

docker logs "${CONTAINER_NAME}" > "${LOG_FILE}" 2>&1 || true

duckdb_stripped_url="${DUCKDB_MCP_URL#http://}"
duckdb_stripped_url="${duckdb_stripped_url#https://}"
duckdb_host_port="${duckdb_stripped_url%%/*}"
duckdb_port="${duckdb_host_port##*:}"

if [[ -f "${DUCKDB_MCP_PID_FILE}" ]]; then
  old_pid="$(cat "${DUCKDB_MCP_PID_FILE}")"
  if [[ -n "${old_pid}" ]] && kill -0 "${old_pid}" >/dev/null 2>&1; then
    kill "${old_pid}" >/dev/null 2>&1 || true
  fi
  rm -f "${DUCKDB_MCP_PID_FILE}"
fi

PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="$(command -v python3)"
fi

nohup env \
  DAB_DATASET_ROOT="${DAB_DATASET_ROOT}" \
  DUCKDB_MCP_PORT="${duckdb_port}" \
  PYTHONPATH="${ROOT_DIR}" \
  "${PYTHON_BIN}" -m agent.duckdb_mcp_server \
  >"${DUCKDB_LOG_FILE}" 2>&1 &
duckdb_pid=$!
echo "${duckdb_pid}" > "${DUCKDB_MCP_PID_FILE}"

duckdb_health_ok=false
for _ in {1..15}; do
  if ! kill -0 "${duckdb_pid}" >/dev/null 2>&1; then
    break
  fi

  if curl --silent --show-error --fail --max-time 2 \
    -H "Content-Type: application/json" \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
    "${DUCKDB_MCP_URL%/}/mcp" >/dev/null 2>&1; then
    duckdb_health_ok=true
    break
  fi

  sleep 1
done

if [[ "${startup_ok}" != "true" || "${duckdb_health_ok}" != "true" ]]; then
  echo "Toolbox failed to become healthy at ${health_url}"
  echo "Container: ${CONTAINER_NAME}"
  echo "Config: ${TOOLS_CONFIG}"
  echo "Dataset mount: ${DAB_DATASET_ROOT} -> /datasets"
  echo "Log: ${LOG_FILE}"
  if [[ -s "${LOG_FILE}" ]]; then
    echo
    echo "Recent toolbox log output:"
    tail -n 40 "${LOG_FILE}"
  fi
  if [[ -s "${DUCKDB_LOG_FILE}" ]]; then
    echo
    echo "Recent DuckDB MCP log output:"
    tail -n 40 "${DUCKDB_LOG_FILE}"
  fi
  exit 1
fi

echo "Toolbox started at ${TOOLBOX_URL}"
echo "Container: ${CONTAINER_NAME}"
echo "Config: ${TOOLS_CONFIG}"
echo "Dataset mount: ${DAB_DATASET_ROOT} -> /datasets"
echo "Log: ${LOG_FILE}"
echo "DuckDB MCP started at ${DUCKDB_MCP_URL}"
echo "DuckDB MCP log: ${DUCKDB_LOG_FILE}"
