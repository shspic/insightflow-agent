from app.core.config import settings


def test_config_imports_with_safe_defaults() -> None:
    assert settings.app_name
    assert settings.env == "testing"
    assert settings.database_url
    assert settings.upload_dir
    assert settings.chart_dir
    assert settings.report_dir
    assert settings.cors_origins


def test_config_does_not_use_real_api_key() -> None:
    assert settings.llm_api_key == ""
    assert not settings.llm_enabled
