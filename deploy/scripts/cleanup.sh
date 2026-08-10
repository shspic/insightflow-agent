#!/usr/bin/env bash
set -Eeuo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/common.sh"

require_command docker
require_production_env
root="$(insightflow_root)"
install -d -m 0750 "${root}/logs/cleanup"
mode="dry-run"
args=(--dry-run)
if [[ "${1:-}" == "--apply" ]]; then
  [[ "${CONFIRM_CLEANUP:-}" == "APPLY_CLEANUP" ]] || {
    echo "自动 apply 需要显式设置 CONFIRM_CLEANUP=APPLY_CLEANUP" >&2
    exit 2
  }
  mode="apply"
  args=(--apply --confirm APPLY_CLEANUP)
fi
log_file="${root}/logs/cleanup/cleanup-${mode}-$(date -u +%Y%m%dT%H%M%SZ).log"
if ! compose exec -T backend python -m app.maintenance.cleanup "${args[@]}" \
  >"${log_file}" 2>&1; then
  operation_log cleanup "清理失败 mode=${mode}；应用未停止"
  echo "清理失败，但未停止应用。详情见 ${log_file}" >&2
  exit 1
fi
operation_log cleanup "清理完成 mode=${mode}"
echo "清理完成；删除数量和释放空间见 ${log_file}"
