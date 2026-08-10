"""阶段 6D-4：发布包权限与可复现性硬化专项测试。

离线：
- 不运行 Docker / WSL / 不构建镜像 / 不访问公网
- 对仓库的 11 个部署 Shell 文件断言 Git 索引模式 100755
- 用受控临时 Git fixture 验证 verify_release_package.py 的
  可执行位 / CRLF / 排除规则 / SHA-256 行为（含 CLI 子进程）
- fixture 全部位于系统临时目录，不写入项目目录、不修改 Git 对象库
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# 11 个必须为 100755 的部署脚本（与 git update-index 清单一致）
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

# 预期的工作区改动（11 个脚本模式变更 + .gitattributes 修改 + 2 新增）
EXPECTED_CHANGES = set(SHELL_SCRIPTS) | {".gitattributes"}
EXPECTED_UNTRACKED = {"scripts/verify_release_package.py",
                      "backend/tests/test_stage6d4_release_package.py"}


def load_verify_module():
    """加载 scripts/verify_release_package.py 为模块（无包结构）。"""
    module_path = ROOT / "scripts" / "verify_release_package.py"
    spec = importlib.util.spec_from_file_location("verify_release_package", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=check,
    )


def build_fixture_repo(tmp_path: Path, *, mode: str, crlf: bool = False,
                       forbidden_files: list[str] | None = None) -> Path:
    """构建受控临时 Git fixture 仓库（含全部 11 个脚本路径）。

    mode: "all755" 全部可执行；"all644" 全部无执行位。
    crlf: deploy.sh 内容使用 CRLF（其余 LF）。
    forbidden_files: 额外写入的排除路径（如 deploy/.env.production）。
    """
    repo = tmp_path / "fixture"
    repo.mkdir(parents=True)
    run_git(repo, "init", "-q")
    run_git(repo, "config", "user.email", "fixture@example.com")
    run_git(repo, "config", "user.name", "fixture")
    run_git(repo, "config", "core.autocrlf", "false")

    for script in SHELL_SCRIPTS:
        target = repo / script
        target.parent.mkdir(parents=True, exist_ok=True)
        content = b"#!/usr/bin/env bash\nset -e\n"
        if crlf and script == "deploy/scripts/deploy.sh":
            content = content.replace(b"\n", b"\r\n")
        target.write_bytes(content)

    if forbidden_files:
        for path in forbidden_files:
            target = repo / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("x\n", encoding="utf-8")

    run_git(repo, "add", "-A")
    if mode == "all755":
        for script in SHELL_SCRIPTS:
            run_git(repo, "update-index", "--chmod=+x", script)
    run_git(repo, "commit", "-q", "-m", "init")
    return repo


def archive_ref(repo: Path, ref: str = "HEAD") -> Path:
    """git archive 到 fixture 同级的临时 tar（不写项目目录）。"""
    archive_path = repo.parent / "release.tar"
    run_git(repo, "-c", "core.autocrlf=false", "archive", "--format=tar",
            "-o", str(archive_path), ref)
    return archive_path


# ── 1. 11 个 Shell 文件索引模式 ────────────────────────────────────


class TestIndexModes:
    def test_all_shell_scripts_are_100755_in_index(self):
        result = run_git(ROOT, "ls-files", "-s", *SHELL_SCRIPTS)
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        assert len(lines) == len(SHELL_SCRIPTS), f"应列出 {len(SHELL_SCRIPTS)} 个文件"
        for line in lines:
            mode, _, _, path = line.split(maxsplit=3)
            assert mode == "100755", f"{path} 索引模式应为 100755，实际 {mode}"
            assert path in SHELL_SCRIPTS

    def test_index_mode_change_keeps_blob_unchanged(self):
        """模式变更不改变脚本内容（blob hash 与 HEAD 一致）。"""
        for script in SHELL_SCRIPTS:
            index_blob = run_git(ROOT, "rev-parse", f":{script}").stdout.strip()
            head_blob = run_git(ROOT, "rev-parse", f"HEAD:{script}").stdout.strip()
            assert index_blob == head_blob, f"{script} 的 blob 不应因 chmod 改变"

    def test_worktree_has_no_unrelated_changes(self):
        status = run_git(ROOT, "status", "--short").stdout.splitlines()
        modified = set()
        untracked = set()
        for line in status:
            code = line[:2].strip()
            path = line[3:].strip()
            if code in ("M", "A"):
                modified.add(path)
            elif code == "??":
                untracked.add(path)
        assert modified <= EXPECTED_CHANGES, f"存在无关修改: {modified - EXPECTED_CHANGES}"
        assert untracked <= EXPECTED_UNTRACKED, f"存在无关新增: {untracked - EXPECTED_UNTRACKED}"


# ── 2. .gitattributes 换行规则 ─────────────────────────────────────


class TestGitAttributes:
    def test_gitattributes_has_sh_eol_lf(self):
        content = (ROOT / ".gitattributes").read_text(encoding="utf-8")
        assert "*.sh text eol=lf" in content

    def test_index_blobs_are_lf(self):
        """暂存区 blob 必须为 LF（发布内容的事实来源）。"""
        for script in SHELL_SCRIPTS:
            index_blob = subprocess.run(
                ["git", "-C", str(ROOT), "show", f":{script}"],
                capture_output=True, check=True,
            ).stdout
            assert b"\r\n" not in index_blob, f"索引 blob 含 CRLF: {script}"

    def test_worktree_normalizes_clean(self):
        """工作区与索引在 eol=lf 规范化下必须一致（git status 无 diff）。

        Windows core.autocrlf=true 下工作区文件可能以 CRLF 检出，但 git
        规范化后与 LF blob 一致（status 干净）；提交不会把 CRLF 写入 blob，
        任何 Linux checkout 均得到 LF（eol=lf）。
        """
        diff = run_git(ROOT, "diff", "--name-only", "--", *SHELL_SCRIPTS).stdout.strip()
        assert diff == "", f"脚本存在未规范化差异: {diff}"

    def test_archive_content_is_lf(self):
        archive_path = archive_ref(ROOT)
        try:
            with tarfile.open(archive_path, "r:") as tar:
                for script in SHELL_SCRIPTS:
                    member = tar.getmember(script)
                    extracted = tar.extractfile(member)
                    assert extracted is not None
                    assert b"\r\n" not in extracted.read(), f"归档含 CRLF: {script}"
        finally:
            archive_path.unlink(missing_ok=True)


# ── 3. verify_release_package.py 行为（受控 fixture）───────────────


class TestVerifyScript:
    @pytest.fixture(scope="class")
    def verify_module(self):
        return load_verify_module()

    def test_accepts_archive_with_executable_scripts(self, tmp_path, verify_module):
        repo = build_fixture_repo(tmp_path, mode="all755")
        archive_path = archive_ref(repo)
        try:
            errors, sha = verify_module.verify_archive(archive_path)
            assert errors == [], f"正确归档不应报错: {errors}"
            assert len(sha) == 64
        finally:
            archive_path.unlink(missing_ok=True)

    def test_rejects_archive_without_executable_bit(self, tmp_path, verify_module):
        repo = build_fixture_repo(tmp_path, mode="all644")
        archive_path = archive_ref(repo)
        try:
            errors, _ = verify_module.verify_archive(archive_path)
            assert any("可执行位" in e for e in errors), f"应报告缺执行位: {errors}"
        finally:
            archive_path.unlink(missing_ok=True)

    def test_rejects_crlf_script(self, tmp_path, verify_module):
        repo = build_fixture_repo(tmp_path, mode="all755", crlf=True)
        archive_path = archive_ref(repo)
        try:
            errors, _ = verify_module.verify_archive(archive_path)
            assert any("CRLF" in e and "deploy.sh" in e for e in errors), \
                f"应报告 CRLF: {errors}"
        finally:
            archive_path.unlink(missing_ok=True)

    @pytest.mark.parametrize(
        "forbidden",
        [
            ["deploy/.env.production"],
            ["backend/data/insightflow.db"],
            ["backend/storage/uploads/x.txt"],
            ["backend/storage/reports/x.md"],
            ["backend/storage/retrieval/x.json"],
            ["model_cache/x.bin"],
            ["node_modules/x.js"],
            [".venv/x"],
            [".env"],
        ],
    )
    def test_rejects_forbidden_paths(self, tmp_path, verify_module, forbidden):
        repo = build_fixture_repo(tmp_path, mode="all755",
                                  forbidden_files=forbidden)
        archive_path = archive_ref(repo)
        try:
            errors, _ = verify_module.verify_archive(archive_path)
            assert any("排除路径" in e and forbidden[0] in e for e in errors), \
                f"应拒绝 {forbidden[0]}: {errors}"
        finally:
            archive_path.unlink(missing_ok=True)

    def test_does_not_reject_code_retrieval_path(self, tmp_path, verify_module):
        """backend/app/retrieval（代码目录）不得被排除规则误伤。"""
        repo = build_fixture_repo(tmp_path, mode="all755")
        target = repo / "backend" / "app" / "retrieval"
        target.mkdir(parents=True)
        (target / "embedding.py").write_text("x = 1\n", encoding="utf-8")
        run_git(repo, "add", "-A")
        run_git(repo, "commit", "-q", "-m", "add retrieval code")
        archive_path = archive_ref(repo)
        try:
            errors, _ = verify_module.verify_archive(archive_path)
            assert not any("排除路径" in e for e in errors), \
                f"backend/app/retrieval 不应被拒: {errors}"
        finally:
            archive_path.unlink(missing_ok=True)

    def test_sha256_stable_across_runs(self, tmp_path, verify_module):
        repo = build_fixture_repo(tmp_path, mode="all755")
        first = archive_ref(repo)
        second = archive_ref(repo)
        try:
            _, sha1 = verify_module.verify_archive(first)
            _, sha2 = verify_module.verify_archive(second)
            assert sha1 == sha2
            assert len(sha1) == 64
        finally:
            first.unlink(missing_ok=True)
            second.unlink(missing_ok=True)

    def test_cli_subprocess_exit_codes(self, tmp_path):
        """CLI 子进程：正确归档 → 0；缺执行位归档 → 1；失败返回非零。"""
        script = ROOT / "scripts" / "verify_release_package.py"

        good_repo = build_fixture_repo(tmp_path / "good", mode="all755")
        good = subprocess.run(
            [sys.executable, str(script), "--ref", "HEAD"],
            cwd=good_repo, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        assert good.returncode == 0, f"正确归档应通过: {good.stdout} {good.stderr}"

        bad_repo = build_fixture_repo(tmp_path / "bad", mode="all644")
        bad = subprocess.run(
            [sys.executable, str(script), "--ref", "HEAD"],
            cwd=bad_repo, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        assert bad.returncode != 0, "缺执行位归档应失败"
        assert "SHA-256" in bad.stdout

        missing = subprocess.run(
            [sys.executable, str(script), "--ref", "no-such-ref"],
            cwd=good_repo, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        assert missing.returncode != 0, "无效 ref 应失败"

    def test_cli_output_contains_sha256(self, tmp_path):
        script = ROOT / "scripts" / "verify_release_package.py"
        repo = build_fixture_repo(tmp_path / "sha", mode="all755")
        result = subprocess.run(
            [sys.executable, str(script), "--ref", "HEAD"],
            cwd=repo, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        assert "SHA-256: " in result.stdout
        sha = result.stdout.split("SHA-256: ", 1)[1].strip().splitlines()[0]
        assert len(sha) == 64
