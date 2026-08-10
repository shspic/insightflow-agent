#!/usr/bin/env bash
set -Eeuo pipefail

[[ "$#" -ge 1 ]] || {
  echo "用法：load-images.sh <image-tar> [image-tar ...]" >&2
  exit 2
}
for archive in "$@"; do
  [[ -f "${archive}" ]] || {
    echo "镜像归档不存在：${archive}" >&2
    exit 2
  }
  docker load --input "${archive}"
done
echo "镜像加载完成。请核对镜像标签后以 SKIP_BUILD=1 执行 upgrade.sh。"
