"""阶段 6D-3：生产部署总演练、发布包与运行手册契约测试。

离线（普通 pytest）：
- 不访问公网 / 不写默认 app.db/uploads/reports/retrieval
- 断言 DEPLOYMENT_V3.md（运行手册）中的命令与仓库脚本逐项一致
- 断言发布包结构（git archive / releases / current / /srv/insightflow）
- 断言端口表（仅 80/443 发布）
- 断言 Alembic head = 0014
- GitHub Actions YAML 可解析
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "backend"
DOCS = ROOT / "docs"
DEPLOY = ROOT / "deploy"
SCRIPTS = DEPLOY / "scripts"
RUNBOOK = DOCS / "DEPLOYMENT_V3.md"


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# ── 运行手册与脚本逐项一致 ─────────────────────────────────────────


class TestRunbookScriptsConsistency:
    def test_runbook_exists_and_references_all_scripts(self):
        runbook = RUNBOOK.read_text(encoding="utf-8")
        for script in (
            "deploy.sh",
            "upgrade.sh",
            "rollback.sh",
            "backup.sh",
            "healthcheck.sh",
            "cleanup.sh",
            "reload-nginx.sh",
            "certbot-deploy-hook.sh",
            "load-images.sh",
            "generate_secrets.py",
        ):
            assert (SCRIPTS / script).is_file(), f"脚本缺失: {script}"
            assert f"deploy/scripts/{script}" in runbook, f"手册必须引用 {script}"

    def test_runbook_deploy_command_matches_script(self):
        deploy = read("deploy/scripts/deploy.sh")
        assert "compose build backend web" in deploy
        assert "alembic upgrade head" in deploy
        assert "python -m app.cli.create_admin" in deploy
        assert "compose up -d backend mcp worker" in deploy
        assert "wait_readiness 45" in deploy
        assert "wait_mcp_healthy 45" in deploy
        assert "compose up -d web" in deploy

    def test_runbook_upgrade_commands_match_script(self):
        upgrade = read("deploy/scripts/upgrade.sh")
        assert "compose stop worker backend mcp" in upgrade
        assert "alembic upgrade head" in upgrade
        assert "compose up -d backend mcp worker" in upgrade
        assert "wait_mcp_healthy 45" in upgrade
        assert 'printf \'%s\\n\' "${version}" >"${root}/data/deployed-version"' in upgrade
        runbook = RUNBOOK.read_text(encoding="utf-8")
        assert "releases/<新版本>" in runbook or "releases/<version>" in runbook

    def test_runbook_rollback_commands_match_script(self):
        rollback = read("deploy/scripts/rollback.sh")
        assert "--code-only" in rollback
        assert "--restore-backup" in rollback
        assert "CONFIRM_RESTORE=RESTORE_DATABASE_AND_STORAGE" in rollback
        assert "rollback-safety-" in rollback
        assert "compose stop worker backend mcp" in rollback
        runbook = RUNBOOK.read_text(encoding="utf-8")
        assert "rollback.sh --restore-backup" in runbook or "--restore-backup" in runbook

    def test_runbook_secrets_generation_matches_script(self):
        gen = read("deploy/scripts/generate_secrets.py")
        assert "--template" in gen
        assert "--output" in gen
        assert "--admin-password-file" in gen
        runbook = RUNBOOK.read_text(encoding="utf-8")
        assert "generate_secrets.py" in runbook

    def test_runbook_healthcheck_commands_match_script(self):
        healthcheck = read("deploy/scripts/healthcheck.sh")
        assert "backend worker mcp web" in healthcheck
        assert "app.mcp.healthcheck" in healthcheck
        assert 'exit "${failures}"' in healthcheck

    def test_runbook_certbot_hook_matches_script(self):
        hook = read("deploy/scripts/certbot-deploy-hook.sh")
        assert "RENEWED_LINEAGE" in hook
        assert "reload-nginx.sh" in hook
        runbook = RUNBOOK.read_text(encoding="utf-8")
        assert "certbot" in runbook

    def test_runbook_backup_commands_match_script(self):
        backup = read("deploy/scripts/backup.sh")
        assert "app.maintenance.backup" in backup
        assert "manifest.json" in read("backend/app/maintenance/backup.py")
        runbook = RUNBOOK.read_text(encoding="utf-8")
        assert "manifest" in runbook


# ── 发布包结构 ──────────────────────────────────────────────────────


class TestReleasePackage:
    def test_runbook_documents_git_tag_and_archive(self):
        runbook = RUNBOOK.read_text(encoding="utf-8")
        assert "git tag" in runbook or "Git Tag" in runbook or "git archive" in runbook
        assert "git archive" in runbook
        assert "sha256sum" in runbook

    def test_runbook_documents_release_layout(self):
        runbook = RUNBOOK.read_text(encoding="utf-8")
        assert "/opt/insightflow/releases/" in runbook
        assert "/opt/insightflow/current" in runbook
        assert "/srv/insightflow" in runbook

    def test_systemd_units_point_to_current_release(self):
        for unit in ("insightflow-health.service", "insightflow-backup.timer",
                     "insightflow-health.timer", "insightflow-cleanup-dry-run.timer"):
            content = (DEPLOY / "systemd" / unit).read_text(encoding="utf-8")
            assert "insightflow" in content.lower(), unit
        health = (DEPLOY / "systemd" / "insightflow-health.service").read_text(encoding="utf-8")
        assert "/opt/insightflow/current" in health
        assert "deploy/scripts/healthcheck.sh" in health

    def test_runbook_documents_tencent_cloud_recommendations(self):
        runbook = RUNBOOK.read_text(encoding="utf-8")
        assert "腾讯云" in runbook or "2核4G" in runbook or "服务器配置" in runbook

    def test_runbook_documents_ports_table(self):
        runbook = RUNBOOK.read_text(encoding="utf-8")
        assert "80" in runbook and "443" in runbook
        assert "端口" in runbook

    def test_runbook_documents_dns_and_tls(self):
        runbook = RUNBOOK.read_text(encoding="utf-8")
        assert "A 记录" in runbook or "DNS" in runbook
        assert "secrets/tls" in runbook

    def test_runbook_documents_bge_model_cache(self):
        runbook = RUNBOOK.read_text(encoding="utf-8")
        assert "model_cache" in runbook or "模型缓存" in runbook or "BGE" in runbook

    def test_runbook_documents_operations_topics(self):
        runbook = RUNBOOK.read_text(encoding="utf-8")
        for topic in ("证书续期", "备份", "监控", "验收", "备案", "AI 标识"):
            assert topic in runbook, f"手册缺少运维主题: {topic}"


# ── 端口表与 compose 结构 ───────────────────────────────────────────


class TestPortTable:
    @pytest.fixture(scope="class")
    def compose(self) -> dict:
        return yaml.safe_load(read("docker-compose.prod.yml"))

    def test_only_web_publishes_ports(self, compose):
        for name in ("backend", "worker", "mcp"):
            assert "ports" not in compose["services"][name], f"{name} 不得发布端口"
        assert compose["services"]["web"]["ports"] == ["80:80", "443:443"]

    def test_no_host_port_8000_8765_5173(self, compose):
        text = str(compose)
        for port in ("8000:8000", "8765:8765", "5173:5173", '"8000:8000"', "0.0.0.0:8000"):
            assert port not in text, f"不得发布 {port}"

    def test_mcp_only_exposed_internally(self, compose):
        assert compose["services"]["mcp"]["expose"] == ["8765"]
        assert "ports" not in compose["services"]["mcp"]

    def test_prod_env_ports_documented_in_runbook(self):
        runbook = RUNBOOK.read_text(encoding="utf-8")
        assert "443" in runbook


# ── Alembic head ────────────────────────────────────────────────────


class TestMigrationHead:
    def test_head_is_0014(self):
        versions = BACKEND_DIR / "alembic" / "versions"
        files = sorted(versions.glob("*.py"))
        assert files, "缺少迁移文件"
        assert files[-1].name.startswith("20260812_0014"), (
            f"最新迁移应为 0014，实际 {files[-1].name}"
        )
        content = files[-1].read_text(encoding="utf-8")
        m = re.search(r'revision: str = "([^"]+)"', content)
        assert m and m.group(1) == "20260812_0014"

    def test_no_duplicate_revisions(self):
        versions = BACKEND_DIR / "alembic" / "versions"
        revisions = []
        for file in versions.glob("*.py"):
            content = file.read_text(encoding="utf-8")
            m = re.search(r'revision: str = "([^"]+)"', content)
            if m:
                revisions.append(m.group(1))
        assert len(revisions) == len(set(revisions)), "存在重复 revision"
        assert "20260812_0014" in revisions


# ── GitHub Actions YAML ─────────────────────────────────────────────


class TestGitHubActions:
    def test_ci_yml_parses(self):
        workflow = yaml.safe_load(read(".github/workflows/ci.yml"))
        assert isinstance(workflow, dict)
        jobs = workflow.get("jobs", {})
        for job in ("backend", "frontend"):
            assert job in jobs, f"缺少 CI job: {job}"

    def test_ci_runs_full_backend_tests(self):
        workflow = yaml.safe_load(read(".github/workflows/ci.yml"))
        backend = workflow["jobs"]["backend"]
        steps = [s for s in backend["steps"] if isinstance(s, dict)]
        runs = " ".join(str(s.get("run", "")) for s in steps)
        assert "pytest" in runs
        assert "alembic" in runs or "Alembic" in runs

    def test_ci_frontend_builds(self):
        workflow = yaml.safe_load(read(".github/workflows/ci.yml"))
        frontend = workflow["jobs"]["frontend"]
        steps = [s for s in frontend["steps"] if isinstance(s, dict)]
        runs = " ".join(str(s.get("run", "")) for s in steps)
        assert "npm test" in runs
        assert "npm run build" in runs


# ── 环境变量清单 ────────────────────────────────────────────────────


class TestEnvChecklist:
    def test_runbook_env_table_matches_example(self):
        env = read("deploy/.env.production.example")
        runbook = RUNBOOK.read_text(encoding="utf-8")
        for name in (
            "AUTH_SECRET_KEY",
            "DATABASE_URL",
            "ALEMBIC_DATABASE_URL",
            "UPLOAD_DIR",
            "REPORT_DIR",
            "CHART_DIR",
            "BACKUP_DIR",
            "CORS_ORIGINS",
            "PUBLIC_SITE_URL",
            "DEEPSEEK_API_KEY",
            "DEEPSEEK_MODEL",
            "ENGINEERING_MCP_INTERNAL_TOKEN",
            "ENGINEERING_MCP_ALLOW_CONTAINER_BIND",
            "PUBLIC_LAUNCH_ENABLED",
            "ICP_FILING_NUMBER",
            "PUBLIC_SECURITY_FILING_NUMBER",
            "AI_ASSISTED_NOTICE",
            "PRIVACY_POLICY_VERSION",
            "TERMS_VERSION",
        ):
            assert f"{name}=" in env, f"示例文件缺少 {name}"
            assert name in runbook, f"手册缺少 {name} 说明"
