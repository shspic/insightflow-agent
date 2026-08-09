#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
PROD_ENV="${INSIGHTFLOW_ENV_FILE:-${REPO_ROOT}/deploy/.env.production}"
COMPOSE_FILE="${REPO_ROOT}/docker-compose.prod.yml"

export INSIGHTFLOW_ENV_FILE="${PROD_ENV}"

compose() {
  docker compose --env-file "${PROD_ENV}" -f "${COMPOSE_FILE}" "$@"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "缺少命令：$1" >&2
    exit 2
  }
}

require_production_env() {
  [[ -f "${PROD_ENV}" ]] || {
    echo "生产环境文件不存在：${PROD_ENV}" >&2
    exit 2
  }
  if grep -Eq '=(replace_|your_)|example\.(cn|com)' "${PROD_ENV}"; then
    echo "生产环境文件仍包含占位符，请先完成配置：${PROD_ENV}" >&2
    exit 2
  fi
  grep -qx 'ENV=production' "${PROD_ENV}" || {
    echo "生产环境必须配置 ENV=production" >&2
    exit 2
  }
  grep -qx 'DEBUG=false' "${PROD_ENV}" || {
    echo "生产环境必须配置 DEBUG=false" >&2
    exit 2
  }
  grep -qx 'ENABLE_LEGACY_V1_API=false' "${PROD_ENV}" || {
    echo "生产环境必须关闭 Legacy V1" >&2
    exit 2
  }
  grep -qx 'AUTH_COOKIE_SECURE=true' "${PROD_ENV}" || {
    echo "生产环境必须启用 Secure Cookie" >&2
    exit 2
  }
}

insightflow_root() {
  local value
  value="$(sed -n 's/^INSIGHTFLOW_ROOT=//p' "${PROD_ENV}" | tail -n 1)"
  value="${value:-/srv/insightflow}"
  if [[ "${value}" != /* || "${value}" == "/" || "${value}" == *".."* ]]; then
    echo "INSIGHTFLOW_ROOT 必须是安全的绝对目录，不能为 / 或包含 .." >&2
    exit 2
  fi
  printf '%s\n' "${value%/}"
}

operation_log() {
  local category="$1"
  local message="$2"
  local root
  root="$(insightflow_root)"
  install -d -m 0750 "${root}/logs/${category}"
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${message}" \
    >>"${root}/logs/${category}/operations.log"
}

wait_readiness() {
  local attempts="${1:-30}"
  local index
  for ((index = 1; index <= attempts; index++)); do
    if compose exec -T backend python -c \
      "import json,urllib.request; d=json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/health/ready',timeout=5)); raise SystemExit(0 if d['status'] in {'ready','degraded'} else 1)" \
      >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  echo "readiness 在等待窗口内未通过" >&2
  return 1
}

# 等待 MCP 容器真实可用（内部工具发现；不使用真实用户 capability token）
wait_mcp_healthy() {
  local attempts="${1:-30}"
  local index
  for ((index = 1; index <= attempts; index++)); do
    if compose exec -T mcp python -m app.mcp.healthcheck \
      --url http://127.0.0.1:8765/mcp >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  echo "MCP 健康检查在等待窗口内未通过" >&2
  return 1
}
