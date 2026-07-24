#!/usr/bin/env bash
set -Eeuo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/common.sh"

require_command docker
require_production_env
root="$(insightflow_root)"
failures=0

check() {
  local label="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    echo "[正常] ${label}"
  else
    echo "[异常] ${label}"
    failures=$((failures + 1))
  fi
}

running_services="$(compose ps --status running --services 2>/dev/null || true)"
for service in backend worker web; do
  if grep -qx "${service}" <<<"${running_services}"; then
    echo "[正常] 容器运行：${service}"
  else
    echo "[异常] 容器未运行：${service}"
    failures=$((failures + 1))
  fi
done

check "API liveness" compose exec -T backend python -c \
  "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=5)"
check "API readiness" compose exec -T backend python -c \
  "import json,urllib.request; d=json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/health/ready',timeout=5)); raise SystemExit(0 if d['status'] in {'ready','degraded'} else 1)"
check "Alembic 当前为 head" compose exec -T backend python -c \
  "from app.db.session import SessionLocal; from app.services.health_service import database_revisions; d=SessionLocal(); c,h=database_revisions(d); d.close(); raise SystemExit(0 if c==h else 1)"
check "storage 可写" compose exec -T backend python -c \
  "from app.services.health_service import _storage_check; raise SystemExit(0 if _storage_check()['status']=='ok' else 1)"
check "Worker 心跳" compose exec -T worker python -m app.workers.healthcheck
check "Nginx 配置" compose exec -T web nginx -t

disk_percent="$(df -P "${root}" | awk 'NR==2 {gsub(/%/,\"\",$5); print $5}')"
if [[ -n "${disk_percent}" && "${disk_percent}" -lt 85 ]]; then
  echo "[正常] 磁盘使用率 ${disk_percent}%"
else
  echo "[异常] 磁盘使用率达到 ${disk_percent:-未知}%"
  failures=$((failures + 1))
fi
free -h | sed -n '1,2p'

if find "${root}/backups" -mindepth 2 -maxdepth 2 -name manifest.json -mtime -2 -print -quit \
  | grep -q .; then
  echo "[正常] 最近 48 小时存在备份"
else
  echo "[异常] 最近 48 小时未发现备份"
  failures=$((failures + 1))
fi

if command -v openssl >/dev/null 2>&1 \
  && openssl x509 -checkend 1209600 -noout -in "${root}/secrets/tls/fullchain.pem" \
  >/dev/null 2>&1; then
  echo "[正常] TLS 证书有效期超过 14 天"
else
  echo "[异常] TLS 证书将在 14 天内到期、不可读或 openssl 不可用"
  failures=$((failures + 1))
fi

echo "健康检查完成：${failures} 项异常"
exit "${failures}"
