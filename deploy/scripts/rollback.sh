#!/usr/bin/env bash
set -Eeuo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/common.sh"

require_command docker
require_command python3
require_production_env

mode="${1:-}"
backend_image="${2:-}"
web_image="${3:-}"
backup_name="${4:-}"
root="$(insightflow_root)"

if [[ "${mode}" == "--code-only" ]]; then
  [[ -n "${backend_image}" && -n "${web_image}" ]] || {
    echo "用法：rollback.sh --code-only <backend-image> <web-image>" >&2
    exit 2
  }
  export INSIGHTFLOW_BACKEND_IMAGE="${backend_image}"
  export INSIGHTFLOW_WEB_IMAGE="${web_image}"
  compose up -d backend mcp worker
  wait_readiness 45
  wait_mcp_healthy 45
  compose up -d web
  operation_log deploy "仅代码回滚 backend=${backend_image} web=${web_image}"
  echo "仅代码回滚完成；前提是当前数据库与旧代码兼容。"
  exit 0
fi

if [[ "${mode}" != "--restore-backup" || -z "${backend_image}" || -z "${web_image}" || -z "${backup_name}" ]]; then
  echo "用法：rollback.sh --restore-backup <backend-image> <web-image> <backup-directory-name>" >&2
  exit 2
fi
[[ "${CONFIRM_RESTORE:-}" == "RESTORE_DATABASE_AND_STORAGE" ]] || {
  echo "完整恢复必须设置 CONFIRM_RESTORE=RESTORE_DATABASE_AND_STORAGE" >&2
  exit 2
}
[[ "${backup_name}" != */* && "${backup_name}" != *".."* ]] || {
  echo "备份名称只能是 backups 下的单个目录名" >&2
  exit 2
}
backup_dir="${root}/backups/${backup_name}"
[[ -f "${backup_dir}/database.sqlite3" && -f "${backup_dir}/storage.zip" && -f "${backup_dir}/manifest.json" ]] || {
  echo "备份不完整：${backup_dir}" >&2
  exit 2
}

compose exec -T backend python -m app.maintenance.backup --verify "/app/backups/${backup_name}"
compose stop worker backend mcp

safety_dir="${root}/backups/rollback-safety-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "${safety_dir}"
[[ "${root}/data/insightflow.db" == "${root}/"* ]] || exit 2
[[ "${root}/storage" == "${root}/"* ]] || exit 2
mv -- "${root}/data/insightflow.db" "${safety_dir}/insightflow.db.before-rollback"
mv -- "${root}/storage" "${safety_dir}/storage.before-rollback"
install -d -m 0750 -o 10001 -g 10001 "${root}/storage"
cp -- "${backup_dir}/database.sqlite3" "${root}/data/insightflow.db"

python3 - "${backup_dir}/storage.zip" "${root}" <<'PY'
import sys
import zipfile
from pathlib import Path

archive_path = Path(sys.argv[1]).resolve()
target = Path(sys.argv[2]).resolve()
with zipfile.ZipFile(archive_path) as archive:
    for name in archive.namelist():
        path = Path(name)
        if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != "storage":
            raise SystemExit(f"拒绝不安全的备份成员：{name}")
    archive.extractall(target)
PY

chown -R 10001:10001 "${root}/data" "${root}/storage"
export INSIGHTFLOW_BACKEND_IMAGE="${backend_image}"
export INSIGHTFLOW_WEB_IMAGE="${web_image}"
compose up -d backend mcp worker
wait_readiness 45
wait_mcp_healthy 45
compose up -d web
operation_log deploy "数据库与 storage 恢复回滚 backup=${backup_name}"
echo "完整恢复回滚完成。升级前现场保存在 ${safety_dir}，未被删除。"
