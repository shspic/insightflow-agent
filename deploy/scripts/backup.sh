#!/usr/bin/env bash
set -Eeuo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/common.sh"

require_command docker
require_production_env
root="$(insightflow_root)"
install -d -m 0750 "${root}/logs/backup"
log_file="${root}/logs/backup/backup-$(date -u +%Y%m%dT%H%M%SZ).log"

compose exec -T backend python -m app.maintenance.backup --output-root /app/backups \
  >"${log_file}" 2>&1
operation_log backup "每日一致性数据库与 storage 完整备份完成"
echo "备份完成；详情见 ${log_file}。脚本不会自动删除旧备份。"
