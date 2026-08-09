"""阶段 6C 最终验收阻断补修契约测试（离线，纯文件断言）。

覆盖四项契约（见验收清单）：
- CI 前端启动、日志、artifact、cleanup 使用一致的 PID/日志路径
  （backend/.ci-smoke，禁止退回旧的 ../.ci-smoke）；
- cleanup 后真实检查 5173/8000 端口释放，仍监听则 step 失败；
- Dockerfile 在 USER insightflow 之前显式设置 entrypoint 可执行权限；
- docker-entrypoint.sh 保持 LF 换行、shebang=#!/bin/sh。

不读取数据库、不启动服务、不写默认 app.db/uploads/reports/retrieval。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
CI_YAML = REPO_ROOT / ".github" / "workflows" / "ci.yml"
DOCKERFILE = BACKEND_DIR / "Dockerfile"
ENTRYPOINT = BACKEND_DIR / "docker-entrypoint.sh"

SMOKE_START_STEP = "构建并启动隔离前端（preview）"
SMOKE_CLEANUP_STEP = "停止冒烟进程并释放端口"
SMOKE_ARTIFACT_STEP = "上传冒烟证据（screenshot/trace/video 与日志，成功与失败均保留）"


@pytest.fixture(scope="module")
def ci_workflow() -> dict:
    """ci.yml 可解析且包含 playwright-smoke job。"""
    workflow = yaml.safe_load(CI_YAML.read_text(encoding="utf-8"))
    assert isinstance(workflow, dict), "ci.yml 必须可解析为 YAML 对象"
    jobs = workflow.get("jobs", {})
    smoke = [j for j in jobs.values() if str(j.get("name", "")).startswith("浏览器冒烟")]
    assert len(smoke) == 1, "必须存在 playwright-smoke job"
    return smoke[0]


def _step(workflow: dict, step_name: str) -> dict:
    for step in workflow["steps"]:
        if isinstance(step, dict) and step.get("name") == step_name:
            return step
    raise AssertionError(f"未找到 step: {step_name}")


class TestFrontendPathConsistency:
    """前端启动/健康检查/artifact/cleanup 必须全部使用 backend/.ci-smoke。"""

    def test_start_writes_pid_and_log_to_backend_ci_smoke(self, ci_workflow):
        run = _step(ci_workflow, SMOKE_START_STEP)["run"]
        # 直接运行 vite 可执行文件，$! 即实际监听进程 PID（不经过 npm wrapper）
        assert "./node_modules/.bin/vite preview" in run
        assert "../backend/.ci-smoke/frontend.log" in run
        assert "../backend/.ci-smoke/frontend.pid" in run

    def test_start_health_check_reads_same_log(self, ci_workflow):
        run = _step(ci_workflow, SMOKE_START_STEP)["run"]
        assert "cat ../backend/.ci-smoke/frontend.log" in run

    def test_start_step_must_not_regress_to_root_ci_smoke(self, ci_workflow):
        run = _step(ci_workflow, SMOKE_START_STEP)["run"]
        assert "../.ci-smoke/" not in run, "前端日志/PID 必须统一在 backend/.ci-smoke，禁止退回旧路径"

    def test_artifact_collects_backend_ci_smoke_logs(self, ci_workflow):
        paths = _step(ci_workflow, SMOKE_ARTIFACT_STEP)["with"]["path"]
        assert isinstance(paths, str)
        assert "backend/.ci-smoke/*.log" in paths

    def test_cleanup_reads_frontend_and_backend_pid(self, ci_workflow):
        run = _step(ci_workflow, SMOKE_CLEANUP_STEP)["run"]
        assert "backend/.ci-smoke/frontend.pid" in run
        assert "backend/.ci-smoke/backend.pid" in run

    def test_backend_start_uses_backend_ci_smoke(self, ci_workflow):
        run = _step(ci_workflow, "启动隔离后端")["run"]
        assert ".ci-smoke/backend.log" in run
        assert ".ci-smoke/backend.pid" in run


class TestCleanupPortCheck:
    """cleanup 必须真实检查 5173/8000 不再监听，仍监听则失败。"""

    def test_cleanup_checks_both_ports(self, ci_workflow):
        run = _step(ci_workflow, SMOKE_CLEANUP_STEP)["run"]
        assert "5173" in run
        assert "8000" in run

    def test_cleanup_verifies_listening_state_not_just_kill(self, ci_workflow):
        run = _step(ci_workflow, SMOKE_CLEANUP_STEP)["run"]
        assert "ss -ltn" in run, "必须用 ss 检查端口监听状态"
        assert "exit 1" in run, "仍监听时必须让 step 失败"

    def test_cleanup_runs_even_on_failure(self, ci_workflow):
        step = _step(ci_workflow, SMOKE_CLEANUP_STEP)
        assert step.get("if") == "always()", "cleanup 必须在冒烟失败时也执行"


class TestEntrypointPermission:
    """Dockerfile 显式固化 entrypoint 可执行权限。"""

    def test_chmod_before_user_switch(self):
        dockerfile = DOCKERFILE.read_text(encoding="utf-8")
        chmod_index = dockerfile.index("RUN chmod 0555 /app/docker-entrypoint.sh")
        user_index = dockerfile.index("USER insightflow")
        assert chmod_index < user_index, "chmod 必须在 USER insightflow 之前执行（root 阶段）"

    def test_entrypoint_executable_in_image(self):
        dockerfile = DOCKERFILE.read_text(encoding="utf-8")
        assert "COPY --chown=insightflow:insightflow docker-entrypoint.sh ./" in dockerfile
        assert "RUN chmod 0555 /app/docker-entrypoint.sh" in dockerfile


class TestEntrypointFileShape:
    """entrypoint 保持 LF、shebang=#!/bin/sh。"""

    def test_shebang_is_bin_sh(self):
        content = ENTRYPOINT.read_bytes()
        assert content.startswith(b"#!/bin/sh\n"), "第一行必须是 #!/bin/sh 且以 LF 结尾"

    def test_lf_line_endings_only(self):
        content = ENTRYPOINT.read_bytes()
        assert b"\r" not in content, "entrypoint 必须保持 LF 换行，禁止 CRLF"
