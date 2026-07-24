from dataclasses import replace
from pathlib import Path

import pytest

from app.core.config import settings, validate_production_security
from app.services import health_service
from app.services import security_service


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def production_settings(**changes):
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
    )
    return replace(base, **changes)


def test_production_security_accepts_hardened_single_host_settings() -> None:
    validate_production_security(production_settings())


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"auth_secret_key": "replace_with_generated_high_entropy_secret"}, "占位符"),
        ({"trusted_proxy_ips": "*"}, "TRUSTED_PROXY_IPS"),
        ({"database_url": "sqlite:///./data/app.db"}, "绝对持久化路径"),
        ({"sqlite_journal_mode": "DELETE"}, "WAL"),
        ({"auth_cookie_secure": False}, "AUTH_COOKIE_SECURE"),
        ({"enable_legacy_v1_api": True}, "ENABLE_LEGACY_V1_API"),
        ({"public_site_url": "https://insightflow.example.cn"}, "PUBLIC_SITE_URL"),
    ],
)
def test_production_security_rejects_unsafe_settings(changes, message) -> None:
    with pytest.raises(RuntimeError, match=message):
        validate_production_security(production_settings(**changes))


def test_old_or_missing_deepseek_model_is_degraded(monkeypatch) -> None:
    for model in ("", "deepseek-chat", "deepseek-reasoner"):
        monkeypatch.setattr(
            health_service,
            "settings",
            replace(
                settings,
                llm_enabled=True,
                llm_api_key="test-key-not-used",
                llm_model=model,
                llm_base_url="https://api.deepseek.com/v1",
            ),
        )
        assert health_service.model_configuration_issue()


def test_production_rejects_weak_interactive_admin_password(monkeypatch) -> None:
    monkeypatch.setattr(
        security_service,
        "settings",
        production_settings(password_min_length=14),
    )
    with pytest.raises(ValueError, match="随机性"):
        security_service.validate_password("aaaaaaaaaaaaaa")
    security_service.validate_password("If!9Qw2#Lp7@Zx4")


def test_production_compose_has_required_isolation_and_persistence() -> None:
    compose = read("docker-compose.prod.yml")
    backend_block = compose.split("  backend:", 1)[1].split("  worker:", 1)[0]
    worker_block = compose.split("  worker:", 1)[1].split("  web:", 1)[0]
    assert "ports:" not in backend_block
    assert 'command: ["python", "-m", "app.cli.run_api"]' in backend_block
    assert 'command: ["python", "-m", "app.workers.task_worker"]' in worker_block
    assert "${INSIGHTFLOW_ROOT:-/srv/insightflow}/data:/app/data" in compose
    assert "${INSIGHTFLOW_ROOT:-/srv/insightflow}/storage:/app/storage" in compose
    assert "restart: unless-stopped" in compose
    assert "max-size: 10m" in compose
    assert "mem_limit:" in compose
    assert "172.30.0.10" in compose
    assert "replicas:" not in compose


def test_nginx_has_spa_sse_upload_and_proxy_security() -> None:
    nginx = read("deploy/nginx/conf.d/default.conf")
    assert "try_files $uri $uri/ /index.html;" in nginx
    assert "client_max_body_size 25m;" in nginx
    assert "proxy_buffering off;" in nginx
    assert 'proxy_set_header Connection "";' in nginx
    assert "proxy_read_timeout 1h;" in nginx
    assert 'add_header X-Accel-Buffering "no" always;' in nginx
    assert "location /api/" in nginx
    assert "X-Forwarded-Proto https" in nginx
    assert "return 301 https://$host$request_uri;" in nginx


def test_images_do_not_copy_runtime_data_and_run_app_as_non_root() -> None:
    backend_dockerfile = read("backend/Dockerfile")
    backend_ignore = read("backend/.dockerignore")
    root_ignore = read(".dockerignore")
    assert "USER insightflow" in backend_dockerfile
    assert "tesseract-ocr-chi-sim" in backend_dockerfile
    assert "fonts-noto-cjk" in backend_dockerfile
    assert "storage/" in backend_ignore
    assert "backups/" in backend_ignore
    assert ".env.*" in backend_ignore
    assert root_ignore.startswith("*")


def test_production_environment_template_has_required_safe_defaults() -> None:
    env = read("deploy/.env.production.example")
    required = {
        "ENV=production",
        "DEBUG=false",
        "AUTH_COOKIE_SECURE=true",
        "ENABLE_LEGACY_V1_API=false",
        "TRUSTED_PROXY_IPS=172.30.0.10",
        "SQLITE_JOURNAL_MODE=WAL",
        "DEEPSEEK_MODEL=deepseek-v4-flash",
        "SYSTEM_MAX_RUNNING_TASKS=1",
    }
    assert required.issubset(set(env.splitlines()))
    assert "deepseek-chat" not in env
    assert "deepseek-reasoner" not in env
    assert "AUTH_SECRET_KEY=replace_" in env


def test_backup_and_rollback_default_to_recoverable_operations() -> None:
    backup = read("deploy/scripts/backup.sh")
    rollback = read("deploy/scripts/rollback.sh")
    cleanup = read("deploy/scripts/cleanup.sh")
    assert "app.maintenance.backup" in backup
    assert "rm " not in backup
    assert "rm " not in rollback
    assert "rollback-safety-" in rollback
    assert "CONFIRM_RESTORE=RESTORE_DATABASE_AND_STORAGE" in rollback
    assert "CONFIRM_CLEANUP=APPLY_CLEANUP" in cleanup
    assert "args=(--dry-run)" in cleanup


def test_secrets_certificates_backups_and_prod_env_are_ignored() -> None:
    gitignore = read(".gitignore")
    for pattern in (
        "deploy/.env.production",
        "deploy/certs/",
        "deploy/backups/",
        "*.pem",
        "backend/backups/",
    ):
        assert pattern in gitignore


def test_frontend_production_uses_relative_api_and_no_source_maps() -> None:
    config = read("frontend/src/api/config.js")
    vite = read("frontend/vite.config.js")
    assert 'import.meta.env.VITE_API_BASE_URL || ""' in config
    assert "sourcemap: false" in vite
