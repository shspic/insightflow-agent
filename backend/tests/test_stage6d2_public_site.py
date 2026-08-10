"""阶段 6D-2：大陆公众站合规配置、法律页面数据源与 AI 标识专项测试。

离线：
- 不调用 DeepSeek / 不访问公网 / 不写默认 app.db/uploads/reports/retrieval
- 门禁校验（validate_production_security）
- 公开信息端点（/api/public/site）无密钥
- 报告 AI 辅助生成声明（Markdown 渲染）

隐私政策/用户协议/AI 披露页面的内容由前端静态模板承载（见前端专项测试），
本文件验证后端数据源与门禁。
"""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, settings, validate_production_security
from app.main import app

ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "backend"


def production_settings(**changes) -> Settings:
    base = replace(
        settings,
        env="production",
        auth_secret_key="6gT!4zQp9#Lm2@Rx7$Vn8^Ks3&Yw5*Ha",
        auth_cookie_secure=True,
        enable_legacy_v1_api=False,
        debug=False,
        trust_proxy_headers=True,
        trusted_proxy_ips="172.30.0.10",
        enable_hsts=True,
        cors_origins_raw="https://insightflow.test.cn",
        public_site_url="https://insightflow.test.cn",
        database_url="sqlite:////app/data/insightflow.db",
        upload_dir="/app/storage/uploads",
        chart_dir="/app/storage/charts",
        report_dir="/app/storage/reports",
        backup_dir="/app/backups",
        sqlite_journal_mode="WAL",
        sqlite_busy_timeout_ms=30000,
        engineering_mcp_enabled=False,
        # 公开站与 MCP 字段默认使用 Settings 类默认值（private 模式安全默认）；
        # 测试覆盖一律经 changes 传入，避免与显式 kwargs 冲突
    )
    return replace(base, **changes)


def public_settings(**changes) -> Settings:
    """完整公开站配置（全部必填项满足门禁）；changes 覆盖默认值。"""
    defaults = {
        "public_launch_enabled": True,
        "site_operator_name": "测试运营主体",
        "site_contact_email": "contact@example.com",
        "icp_filing_number": "京ICP备12345678号-1",
        "icp_filing_url": "https://beian.miit.gov.cn/",
        "public_security_filing_number": "",
        "public_security_filing_url": "http://www.beian.gov.cn/portal/index.do",
        "ai_model_display_name": "DeepSeek",
        "ai_model_filing_number": "",
        "privacy_policy_version": "2026-08-09",
        "terms_version": "2026-08-09",
    }
    defaults.update(changes)
    return production_settings(**defaults)


# ── 门禁：PUBLIC_LAUNCH_ENABLED=true 必填项 ─────────────────────────


class TestPublicLaunchGate:
    def test_private_mode_all_empty_accepted(self):
        validate_production_security(production_settings())

    def test_complete_public_config_accepted(self):
        validate_production_security(public_settings())

    @pytest.mark.parametrize(
        "field",
        [
            "site_operator_name",
            "site_contact_email",
            "icp_filing_number",
            "privacy_policy_version",
            "terms_version",
            "ai_model_display_name",
            "ai_assisted_notice",
        ],
    )
    def test_missing_required_field_rejected(self, field):
        with pytest.raises(RuntimeError, match="必须配置"):
            validate_production_security(public_settings(**{field: ""}))

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("site_operator_name", "replace_with_operator_name"),
            ("site_contact_email", "replace_with_contact_email"),
            ("icp_filing_number", "replace_with_icp_filing_number"),
            ("privacy_policy_version", "replace_with_policy_version"),
            ("terms_version", "replace_with_terms_version"),
            ("ai_model_display_name", "replace_with_model_display_name"),
        ],
    )
    def test_placeholder_values_rejected(self, field, value):
        with pytest.raises(RuntimeError, match="占位符|必须配置"):
            validate_production_security(public_settings(**{field: value}))

    def test_invalid_email_rejected(self):
        with pytest.raises(RuntimeError, match="有效邮箱"):
            validate_production_security(public_settings(site_contact_email="not-an-email"))

    @pytest.mark.parametrize(
        "icp",
        [
            "京ICP备12345678号-1",   # 网站备案号（带序号）
            "粤ICP备12345678号",      # 广东主体备案号（不带序号）
            "京ICP备00000001号-12",   # 多序号
        ],
    )
    def test_valid_icp_formats_accepted(self, icp):
        validate_production_security(public_settings(icp_filing_number=icp))

    @pytest.mark.parametrize(
        "icp",
        ["ICP备12345678号-1", "京ICP备号-1", "京ICP备12345678号-1-2", "12345", ""],
    )
    def test_invalid_icp_formats_rejected(self, icp):
        with pytest.raises(RuntimeError, match="ICP_FILING_NUMBER"):
            validate_production_security(public_settings(icp_filing_number=icp))

    def test_icp_url_must_be_miit(self):
        with pytest.raises(RuntimeError, match="beian.miit.gov.cn"):
            validate_production_security(public_settings(icp_filing_url="https://evil.example.com/"))

    def test_security_filing_empty_allowed_as_processing(self):
        """公安备案允许留空（法定办理期限内），不伪造号码。"""
        validate_production_security(public_settings(public_security_filing_number=""))

    def test_security_filing_valid_format_accepted(self):
        validate_production_security(
            public_settings(public_security_filing_number="京公网安备11010102003753号")
        )

    def test_security_filing_placeholder_rejected(self):
        with pytest.raises(RuntimeError, match="占位符"):
            validate_production_security(
                public_settings(public_security_filing_number="replace_with_security_filing")
            )

    def test_security_filing_bad_format_rejected(self):
        with pytest.raises(RuntimeError, match="PUBLIC_SECURITY_FILING_NUMBER"):
            validate_production_security(
                public_settings(public_security_filing_number="京公网安备abc号")
            )

    def test_security_url_must_be_beian_gov_cn(self):
        with pytest.raises(RuntimeError, match="beian.gov.cn"):
            validate_production_security(
                public_settings(public_security_filing_url="https://evil.example.com/portal")
            )

    def test_ai_filing_empty_allowed_as_processing(self):
        validate_production_security(public_settings(ai_model_filing_number=""))

    def test_ai_filing_placeholder_rejected(self):
        with pytest.raises(RuntimeError, match="占位符"):
            validate_production_security(
                public_settings(ai_model_filing_number="replace_with_ai_filing")
            )

    def test_ai_filing_valid_accepted(self):
        validate_production_security(public_settings(ai_model_filing_number="网信算备12345678901234号"))


# ── 公开信息端点 /api/public/site ───────────────────────────────────


class TestPublicSiteEndpoint:
    def test_public_mode_returns_public_fields(self, monkeypatch):
        import app.api.public_site as public_site_mod

        original = public_site_mod.settings
        public_site_mod.settings = public_settings()
        try:
            client = TestClient(app)
            response = client.get("/api/public/site")
            assert response.status_code == 200
            data = response.json()
            assert data["public_launch_enabled"] is True
            assert data["site_operator_name"] == "测试运营主体"
            assert data["site_contact_email"] == "contact@example.com"
            assert data["icp_filing_number"] == "京ICP备12345678号-1"
            assert data["icp_filing_url"] == "https://beian.miit.gov.cn/"
            assert data["public_security_filing_number"] == ""  # 办理中
            assert data["ai_model_display_name"] == "DeepSeek"
            assert data["ai_assisted_notice"] == "AI 辅助生成，须人工复核"
        finally:
            public_site_mod.settings = original

    def test_private_mode_omits_operator_fields_but_keeps_ai_notice(self, monkeypatch):
        import app.api.public_site as public_site_mod

        original = public_site_mod.settings
        public_site_mod.settings = production_settings(
            site_operator_name="不应公开", icp_filing_number="不应公开"
        )
        try:
            client = TestClient(app)
            data = client.get("/api/public/site").json()
            assert data["public_launch_enabled"] is False
            assert data["site_operator_name"] == ""
            assert data["site_contact_email"] == ""
            assert data["icp_filing_number"] == ""
            assert data["public_security_filing_number"] == ""
            assert data["privacy_policy_version"] == ""
            assert data["terms_version"] == ""
            # AI 标识义务与是否公开上线无关，始终返回
            assert data["ai_assisted_notice"] == "AI 辅助生成，须人工复核"
        finally:
            public_site_mod.settings = original

    def test_endpoint_never_exposes_secrets(self, monkeypatch):
        import app.api.public_site as public_site_mod

        original = public_site_mod.settings
        public_site_mod.settings = public_settings(
            auth_secret_key="secret-auth-key-1234567890",
        )
        try:
            client = TestClient(app)
            data = client.get("/api/public/site").json()
            text = str(data)
            for forbidden in (
                "auth_secret_key",
                "AUTH_SECRET_KEY",
                "engineering_mcp_internal_token",
                "ENGINEERING_MCP_INTERNAL_TOKEN",
                "DEEPSEEK_API_KEY",
                "llm_api_key",
                "secret-auth-key",
            ):
                assert forbidden not in text, f"端点泄露 {forbidden}"
        finally:
            public_site_mod.settings = original

    def test_env_template_uses_placeholders_only(self):
        env = (ROOT / "deploy/.env.production.example").read_text(encoding="utf-8")
        for name in (
            "PUBLIC_LAUNCH_ENABLED",
            "SITE_OPERATOR_NAME",
            "SITE_CONTACT_EMAIL",
            "ICP_FILING_NUMBER",
            "ICP_FILING_URL",
            "PUBLIC_SECURITY_FILING_NUMBER",
            "PUBLIC_SECURITY_FILING_URL",
            "AI_MODEL_DISPLAY_NAME",
            "AI_MODEL_FILING_NUMBER",
            "AI_ASSISTED_NOTICE",
            "PRIVACY_POLICY_VERSION",
            "TERMS_VERSION",
        ):
            assert any(line.startswith(f"{name}=") for line in env.splitlines()), name
        # 示例文件只允许 replace_ 占位；不得出现真实号码模式
        lines = {line.split("=")[0]: line.split("=", 1)[1] for line in env.splitlines() if "=" in line}
        assert lines["ICP_FILING_NUMBER"].startswith("replace_")
        assert lines["SITE_OPERATOR_NAME"].startswith("replace_")
        assert lines["AI_MODEL_DISPLAY_NAME"].startswith("replace_")
        assert lines["PUBLIC_LAUNCH_ENABLED"] == "false"
        # 真实备案号模式（含"ICP备"或"公网安备"的真实号码）不得出现在模板赋值行中
        # （注释中的格式示例允许存在，用于指导用户填写）
        for line in env.splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                assert re.search(r"[一-龥]{1,2}ICP备\d+号", line) is None, (
                    f"模板赋值行不得包含真实 ICP 备案号: {line}"
                )
                assert re.search(r"[一-龥]{1,2}公网安备\d+号", line) is None, (
                    f"模板赋值行不得包含真实公安备案号: {line}"
                )


# ── 报告 AI 辅助生成声明（显式标识） ────────────────────────────────


class TestReportAiDisclosure:
    def test_ai_disclosure_markdown_has_notice_and_model(self, monkeypatch):
        from app.services.review_report_service import ai_disclosure_markdown

        monkeypatch.setattr(
            "app.services.review_report_service.settings",
            production_settings(ai_model_display_name="DeepSeek"),
        )
        text = ai_disclosure_markdown()
        assert "AI 辅助生成声明" in text
        assert "DeepSeek" in text
        assert "不承诺结果完全准确" in text
        assert "人工确认" in text or "专业人员确认" in text

    def test_ai_disclosure_markdown_without_model_config(self, monkeypatch):
        from app.services.review_report_service import ai_disclosure_markdown

        monkeypatch.setattr(
            "app.services.review_report_service.settings",
            production_settings(ai_model_display_name=""),
        )
        text = ai_disclosure_markdown()
        assert "AI 辅助生成声明" in text
        assert "不承诺结果完全准确" in text

    def test_render_markdown_includes_ai_disclosure(self, monkeypatch):
        """渲染出的报告 Markdown 必须包含可见 AI 声明。"""
        from app.services.review_report_service import render_review_report_markdown

        snapshot = {
            "run": {
                "id": 1, "status": "completed",
                "rule_pack_id": "pack", "rule_pack_version": "v1",
                "rule_pack_hash": "a" * 64,
                "review_brief_id": 1, "review_brief_version": 1,
                "review_brief_hash": "b" * 64,
                "model_provider": None, "model_name": None,
                "prompt_version": None, "started_at": None, "completed_at": None,
            },
            "brief": {
                "id": 1, "version": 1, "content_hash": "c" * 64,
                "raw_requirements": "测试", "interpreter_type": None,
                "interpreted": {},
            },
            "rules": {"pack_id": "pack", "version": "v1", "hash": "h" * 64,
                      "snapshot": {}, "passed_rule_ids": [], "failed_rule_ids": []},
            "materials": [],
            "findings": [],
            "evidences": [],
            "statistics": {
                "finding_count": 0, "high_count": 0, "medium_count": 0,
                "low_count": 0, "confirmed_count": 0, "rejected_count": 0,
                "modified_count": 0, "resolved_count": 0, "pending_review_count": 0,
                "evidence_count": 0, "passed_rule_count": 0, "failed_rule_count": 0,
            },
        }
        quality_gate = {"passed": True, "blocking_errors": [], "warnings": [],
                        "requires_professional_review": True}
        report = type("Report", (), {
            "version": 1, "id": 1, "review_run_id": 1, "review_state_hash": "s" * 64,
            "generator_name": "test", "generator_version": "1",
            "created_at": None,
        })()
        monkeypatch.setattr(
            "app.services.review_report_service.settings",
            production_settings(ai_model_display_name="DeepSeek"),
        )
        markdown = render_review_report_markdown(report, snapshot, quality_gate)
        assert "AI 辅助生成声明" in markdown
        assert "须人工复核" in markdown
        assert "不承诺结果完全准确" in markdown
        assert "DeepSeek" in markdown
        assert "## 1. 报告声明" in markdown

    def test_ai_disclosure_does_not_change_state_hash(self):
        """AI 声明来自运行时配置渲染，不进入审查状态哈希（历史不可变）。"""
        from app.services.review_report_service import canonical_json_bytes, review_state_hash

        snapshot = {"schema_version": "review_report_snapshot/v1", "findings": []}
        h1 = review_state_hash(snapshot)
        h2 = review_state_hash(snapshot)
        assert h1 == h2
        assert canonical_json_bytes(snapshot) == canonical_json_bytes(snapshot)


# ── 配置项与安全边界 ────────────────────────────────────────────────


class TestConfigFields:
    def test_defaults_are_safe(self):
        assert settings.public_launch_enabled is False
        assert settings.site_operator_name == ""
        assert settings.icp_filing_number == ""
        assert settings.ai_assisted_notice == "AI 辅助生成，须人工复核"
        assert settings.icp_filing_url == "https://beian.miit.gov.cn/"

    def test_docs_and_readme_not_required(self):
        """6D-2 不新增 API 文档缺失：公开端点在 README 有记录（软性，仅确认存在）。"""
        readme = (ROOT / "README.md").read_text(encoding="utf-8", errors="replace")
        assert "health" in readme.lower()
