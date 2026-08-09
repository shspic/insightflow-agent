"""阶段 6C 最终验收阻断补修契约测试（离线，纯文件断言）。

覆盖契约（见验收清单）：
- CI 前端启动、日志、artifact、cleanup 使用一致的 PID/日志路径
  （backend/.ci-smoke，禁止退回旧的 ../.ci-smoke）；
- cleanup 后真实检查 5173/8000 端口释放，仍监听则 step 失败；
- Dockerfile 在 USER insightflow 之前显式设置 entrypoint 可执行权限；
- docker-entrypoint.sh 保持 LF 换行、shebang=#!/bin/sh；
- 冻结黄金材料 05_项目澄清.md 的 .gitattributes 设 -text（禁止换行转换），
  文件字节必须与 manifest SHA-256 一致（跨平台 CI 防线）；
- CI backend job 在 Alembic/pytest 前安装中文字体（fontconfig + fonts-noto-cjk）
  并用 fc-match 显式验证。

不读取数据库、不启动服务、不写默认 app.db/uploads/reports/retrieval。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
import yaml

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
CI_YAML = REPO_ROOT / ".github" / "workflows" / "ci.yml"
DOCKERFILE = BACKEND_DIR / "Dockerfile"
ENTRYPOINT = BACKEND_DIR / "docker-entrypoint.sh"
GOLDEN_CASE_DIR = REPO_ROOT / "examples" / "engineering_review_v1" / "golden_case"
GOLDEN_MD_REL = "examples/engineering_review_v1/golden_case/05_项目澄清.md"
GOLDEN_MD_FILENAME = "05_项目澄清.md"

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


@pytest.fixture(scope="module")
def backend_job() -> dict:
    """ci.yml 可解析且包含 backend job。"""
    workflow = yaml.safe_load(CI_YAML.read_text(encoding="utf-8"))
    assert isinstance(workflow, dict), "ci.yml 必须可解析为 YAML 对象"
    job = workflow["jobs"].get("backend")
    assert isinstance(job, dict), "必须存在 backend job"
    return job


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


class TestGoldenFileLineEndings:
    """冻结黄金材料按字节冻结：.gitattributes 设 -text，禁止 LF 归一化。

    05_项目澄清.md 的 manifest SHA-256 基于 CRLF 字节计算；若删除 -text 规则，
    Linux CI checkout 将得到 LF 字节导致 corpus setup 失败（Windows 本地因
    core.autocrlf 转换可能暂时通过），因此必须同时断言属性规则与字节 SHA。
    """

    def test_gitattributes_declares_text_unset_for_golden_file(self):
        attrs = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")
        assert GOLDEN_MD_FILENAME in attrs, ".gitattributes 必须包含黄金文件规则"
        assert "-text" in attrs, ".gitattributes 必须设置 -text 禁止换行转换"

    def test_golden_file_text_attr_is_unset(self):
        result = subprocess.run(
            ["git", "check-attr", "text", "--", str(REPO_ROOT / GOLDEN_MD_REL)],
            capture_output=True,
            text=True,
            check=True,
        )
        assert "text: unset" in result.stdout, (
            f"黄金文件 text 属性必须为 unset，实际输出: {result.stdout.strip()}"
        )

    def test_golden_file_bytes_match_manifest(self):
        """文件字节必须与 manifest SHA-256 一致，且保持 CRLF（跨平台防线）。"""
        manifest = json.loads((GOLDEN_CASE_DIR / "manifest.json").read_text(encoding="utf-8"))
        entry = next(f for f in manifest["files"] if f["filename"] == GOLDEN_MD_FILENAME)
        data = (REPO_ROOT / GOLDEN_MD_REL).read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry["sha256"], (
            "黄金文件字节与 manifest 不一致：换行转换或内容漂移，corpus setup 将失败"
        )
        assert data.count(b"\r\n") > 0, "冻结材料必须保持 CRLF 原始字节"


class TestCIFontInstall:
    """CI backend job 必须在 Alembic/pytest 前安装中文字体并显式验证。"""

    def test_font_step_runs_before_tests(self, backend_job):
        names = [s.get("name", "") for s in backend_job["steps"] if isinstance(s, dict)]
        font_idx = next(i for i, n in enumerate(names) if "中文字体" in n)
        alembic_idx = next(i for i, n in enumerate(names) if "Alembic" in n)
        pytest_idx = next(i for i, n in enumerate(names) if "完整后端测试" in n)
        assert font_idx < alembic_idx < pytest_idx, (
            "字体安装 step 必须在 Alembic 与完整 pytest 之前"
        )

    def test_font_step_installs_fonts_without_recommends(self, backend_job):
        step = next(
            s for s in backend_job["steps"]
            if isinstance(s, dict) and "中文字体" in s.get("name", "")
        )
        run = step["run"]
        assert "apt-get install" in run
        assert "--no-install-recommends" in run
        assert "fontconfig" in run
        assert "fonts-noto-cjk" in run
        # reportlab 无法加载 Noto CJK 的 PostScript 轮廓 ttc，必须有 TrueType 轮廓字体
        assert "fonts-wqy-zenhei" in run, "必须安装 wqy-zenhei（reportlab PDF 报告需要 TrueType 轮廓）"

    def test_font_step_refreshes_cache_and_verifies_fc_match(self, backend_job):
        step = next(
            s for s in backend_job["steps"]
            if isinstance(s, dict) and "中文字体" in s.get("name", "")
        )
        run = step["run"]
        assert "fc-cache" in run, "必须刷新字体缓存"
        assert 'fc-match "Noto Sans CJK SC"' in run, "必须用 fc-match 验证中文字体"
        assert 'fc-match "WenQuanYi Zen Hei"' in run, "必须用 fc-match 验证 wqy-zenhei"
        assert "exit 1" in run, "字体不可用时必须立即失败"
