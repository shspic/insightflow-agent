#!/usr/bin/env bash
set -Eeuo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/common.sh"

require_command docker
require_command curl
require_production_env

root="$(insightflow_root)"
[[ "$(id -u)" -eq 0 ]] || {
  echo "首次部署需要创建 /srv 持久化目录，请使用 sudo 运行此脚本" >&2
  exit 2
}
[[ ! -e "${root}/data/insightflow.db" ]] || {
  echo "数据库已存在；首次部署脚本拒绝重复执行，请改用 upgrade.sh" >&2
  exit 2
}
[[ -f "${root}/secrets/tls/fullchain.pem" && -f "${root}/secrets/tls/privkey.pem" ]] || {
  echo "HTTPS 证书尚未放入 ${root}/secrets/tls，拒绝启动正式站点" >&2
  exit 2
}

install -d -m 0750 -o 10001 -g 10001 \
  "${root}/data" "${root}/storage" "${root}/storage/uploads" \
  "${root}/storage/charts" "${root}/storage/reports" \
  "${root}/backups" "${root}/logs/app"
install -d -m 0750 "${root}/logs/deploy" "${root}/logs/backup" \
  "${root}/logs/cleanup" "${root}/logs/nginx"
install -d -m 0700 "${root}/secrets" "${root}/secrets/tls" "${root}/secrets/acme"

compose config --quiet
compose build backend web
compose run --rm --no-deps backend alembic upgrade head

echo "现在通过现有安全 CLI 创建管理员；密码不会写入部署日志。"
compose run --rm --no-deps backend python -m app.cli.create_admin

compose up -d backend worker
wait_readiness 45
compose up -d web
compose exec -T web nginx -t

printf '%s\n' "${INSIGHTFLOW_VERSION:-initial}" >"${root}/data/deployed-version"
operation_log deploy "首次部署完成 version=${INSIGHTFLOW_VERSION:-initial}"
echo "首次部署完成。请访问正式域名登录，并由管理员创建第一个邀请码。"
