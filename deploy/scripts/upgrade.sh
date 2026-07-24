#!/usr/bin/env bash
set -Eeuo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/common.sh"

require_command docker
require_production_env
version="${1:-}"
[[ -n "${version}" ]] || {
  echo "用法：upgrade.sh <release-version>" >&2
  exit 2
}
root="$(insightflow_root)"
[[ -e "${root}/data/insightflow.db" ]] || {
  echo "数据库不存在；请先执行首次部署" >&2
  exit 2
}

compose config --quiet
"${SCRIPT_DIR}/backup.sh"

if [[ "${SKIP_BUILD:-0}" == "1" ]]; then
  echo "使用已通过 docker load 或国内镜像仓库取得的镜像。"
else
  compose build backend web
fi

compose stop worker backend
if ! compose run --rm --no-deps backend alembic upgrade head; then
  operation_log deploy "升级迁移失败 version=${version}；backend/worker 保持停止"
  echo "Alembic 升级失败。请保持停写并按 rollback.sh 的备份恢复模式处理。" >&2
  exit 1
fi

compose up -d backend worker
if ! wait_readiness 45; then
  operation_log deploy "升级 readiness 失败 version=${version}"
  echo "新版本 readiness 未通过；不要继续对外切换，按运行手册回滚。" >&2
  exit 1
fi
compose up -d web
compose exec -T web nginx -t
printf '%s\n' "${version}" >"${root}/data/deployed-version"
operation_log deploy "升级完成 version=${version}"
echo "升级完成：${version}"
