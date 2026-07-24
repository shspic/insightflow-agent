#!/usr/bin/env bash
set -Eeuo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/common.sh"

require_production_env
[[ "$(id -u)" -eq 0 ]] || {
  echo "证书部署 hook 必须以 root 运行" >&2
  exit 2
}
[[ -n "${RENEWED_LINEAGE:-}" ]] || {
  echo "缺少 Certbot 的 RENEWED_LINEAGE" >&2
  exit 2
}
root="$(insightflow_root)"
install -d -m 0700 "${root}/secrets/tls"
install -m 0644 "${RENEWED_LINEAGE}/fullchain.pem" "${root}/secrets/tls/fullchain.pem"
install -m 0600 "${RENEWED_LINEAGE}/privkey.pem" "${root}/secrets/tls/privkey.pem"
"${SCRIPT_DIR}/reload-nginx.sh"
