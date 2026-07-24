#!/usr/bin/env bash
set -Eeuo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/common.sh"

require_command docker
require_command openssl
require_production_env
root="$(insightflow_root)"
openssl x509 -noout -in "${root}/secrets/tls/fullchain.pem" >/dev/null
openssl pkey -noout -in "${root}/secrets/tls/privkey.pem" >/dev/null
compose exec -T web nginx -t
compose exec -T web nginx -s reload
operation_log deploy "Nginx 已在证书和配置校验后平滑 reload"
echo "Nginx 已平滑 reload。"
