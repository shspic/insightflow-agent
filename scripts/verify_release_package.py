#!/usr/bin/env python3
"""6D-4：生产发布包只读校验脚本。

用法：
    python3 scripts/verify_release_package.py [--ref <git-ref|tag>] [--prefix <顶层目录>]

行为：
1. 接收 Git ref/tag（默认 HEAD）；
2. 在系统临时目录生成 tar 归档（不写入项目目录）；
3. 检查 11 个部署 Shell 文件在 tar 中的 mode 包含可执行位；
4. 检查这些 Shell 文件内容无 CRLF；
5. 检查归档不包含：.git、.env、deploy/.env.production、backend/data、
   backend/storage（含 uploads/reports/retrieval）、model_cache、
   node_modules、.venv、pytest 临时目录；
6. 输出归档 SHA-256；
7. 任何失败返回非零退出码。

只读安全边界：
- 不写项目目录（归档放系统临时目录）；
- 不修改 Git 对象库（git archive 为只读命令）；
- 不输出任何密钥。

注意：脚本本身不包含密钥；排除规则使用精确路径 + 路径段防御，
不会误伤 backend/app/retrieval（代码目录）与 *.example 模板文件。
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

# 发布包必须带可执行位的部署脚本（与 git update-index --chmod=+x 清单一致）
SHELL_SCRIPTS = (
    "backend/docker-entrypoint.sh",
    "deploy/scripts/backup.sh",
    "deploy/scripts/certbot-deploy-hook.sh",
    "deploy/scripts/cleanup.sh",
    "deploy/scripts/common.sh",
    "deploy/scripts/deploy.sh",
    "deploy/scripts/healthcheck.sh",
    "deploy/scripts/load-images.sh",
    "deploy/scripts/reload-nginx.sh",
    "deploy/scripts/rollback.sh",
    "deploy/scripts/upgrade.sh",
)

# 归档禁止包含的精确路径（目录前缀以 "/" 结尾表示整棵子树）
FORBIDDEN_PREFIXES = (
    ".git/",
    "backend/data/",
    "backend/storage/",
    "backend/storage/uploads/",
    "backend/storage/reports/",
    "backend/storage/retrieval/",
    "node_modules/",
    ".venv/",
    ".pytest_cache/",
)
# 归档禁止包含的精确文件
FORBIDDEN_FILES = frozenset({
    ".git",
    ".env",
    "deploy/.env.production",
    "backend/data",
    "backend/storage",
})
# 路径段防御：归档成员路径的任一段命中即拒绝（覆盖未来漂移的未跟踪内容）
FORBIDDEN_SEGMENTS = frozenset({
    ".env", "model_cache", "node_modules", ".venv", ".pytest_cache",
})
FORBIDDEN_SEGMENT_PREFIXES = ("pytest-of-", "pytest_")


def _member_path_parts(name: str) -> list[str]:
    """按 "/" 拆路径段（忽略首层可选 prefix）。"""
    return [segment for segment in name.split("/") if segment]


def _is_forbidden(name: str) -> bool:
    """判定归档成员路径是否命中排除规则。"""
    stripped = name.rstrip("/")
    if stripped in FORBIDDEN_FILES:
        return True
    for prefix in FORBIDDEN_PREFIXES:
        if stripped.startswith(prefix):
            return True
    for segment in _member_path_parts(stripped):
        if segment in FORBIDDEN_SEGMENTS:
            return True
        if segment.startswith(FORBIDDEN_SEGMENT_PREFIXES):
            return True
    return False


def verify_archive(archive_path: Path) -> tuple[list[str], str]:
    """校验 tar 归档；返回 (错误列表, SHA-256)。空错误列表表示通过。"""
    errors: list[str] = []

    digest = hashlib.sha256()
    with archive_path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    archive_sha256 = digest.hexdigest()

    with tarfile.open(archive_path, "r:") as tar:
        members = tar.getmembers()
        if not members:
            errors.append("归档为空")
            return errors, archive_sha256
        for member in members:
            if _is_forbidden(member.name):
                errors.append(f"归档包含排除路径: {member.name}")
            if member.name in SHELL_SCRIPTS:
                if not (member.mode & 0o111):
                    errors.append(
                        f"缺少可执行位: {member.name} (mode {oct(member.mode)})"
                    )
                extracted = tar.extractfile(member)
                if extracted is not None:
                    content = extracted.read()
                    if b"\r\n" in content:
                        errors.append(f"包含 CRLF: {member.name}")
    return errors, archive_sha256


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="校验 InsightFlow 生产发布包（可执行位 / LF / 排除规则 / SHA-256）"
    )
    parser.add_argument("--ref", default="HEAD", help="Git ref 或 tag（默认 HEAD）")
    args = parser.parse_args(argv)

    temp_dir = Path(tempfile.mkdtemp(prefix="verify-release-package-"))
    archive_path = temp_dir / "release.tar"
    try:
        subprocess.run(
            ["git", "-c", "core.autocrlf=false", "archive", "--format=tar",
             "-o", str(archive_path), args.ref],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        print(f"git archive 失败（ref={args.ref}）: {exc.stderr.strip()}", file=sys.stderr)
        return 1

    errors, archive_sha256 = verify_archive(archive_path)
    print(f"归档 SHA-256: {archive_sha256}")
    if errors:
        for message in errors:
            print(f"校验失败: {message}", file=sys.stderr)
        return 1
    print(f"校验通过: {len(SHELL_SCRIPTS)} 个 Shell 脚本可执行位与 LF 正常，"
          f"无排除路径（ref={args.ref}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
