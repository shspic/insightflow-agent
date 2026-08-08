import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_DIR / ".env")


def _get_env(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


def _parse_cors_origins(value: str) -> list[str]:
    return [origin.strip() for origin in value.split(",") if origin.strip()]


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_int(value: str, default: int) -> int:
    try:
        return int(value)
    except ValueError:
        return default


def _parse_float(value: str, default: float) -> float:
    try:
        return float(value)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    app_name: str = _get_env("APP_NAME", "InsightFlow Agent")
    env: str = _get_env("ENV", "development")
    database_url: str = _get_env("DATABASE_URL", "sqlite:///./data/app.db")
    llm_provider: str = _get_env("LLM_PROVIDER", "deepseek")
    llm_api_key: str = _get_env("DEEPSEEK_API_KEY", _get_env("LLM_API_KEY", ""))
    llm_model: str = _get_env(
        "DEEPSEEK_MODEL",
        _get_env("LLM_MODEL", "<部署时核实的可用模型名>"),
    )
    llm_base_url: str = _get_env(
        "DEEPSEEK_API_BASE",
        _get_env("LLM_BASE_URL", "https://api.deepseek.com/v1"),
    )
    llm_enabled: bool = _parse_bool(_get_env("LLM_ENABLED", "true"))
    llm_max_retries: int = _parse_int(_get_env("LLM_MAX_RETRIES", "1"), 1)
    embedding_provider: str = _get_env("EMBEDDING_PROVIDER", "local")  # 规划中，未接入真实 Embedding
    vector_store: str = _get_env("VECTOR_STORE", "chroma")  # 规划中，未接入真实 Chroma/FAISS
    rag_retrieval_mode: str = _get_env("RAG_RETRIEVAL_MODE", "auto")  # auto/tfidf/keyword，当前为 TF-IDF 算法
    rag_top_k: int = _parse_int(_get_env("RAG_TOP_K", "5"), 5)
    rag_chunk_size: int = _parse_int(_get_env("RAG_CHUNK_SIZE", "800"), 800)
    rag_chunk_overlap: int = _parse_int(_get_env("RAG_CHUNK_OVERLAP", "100"), 100)
    upload_dir: str = _get_env("UPLOAD_DIR", "./storage/uploads")
    chart_dir: str = _get_env("CHART_DIR", "./storage/charts")
    report_dir: str = _get_env("REPORT_DIR", "./storage/reports")
    cors_origins_raw: str = _get_env("CORS_ORIGINS", "http://localhost:5173")
    tesseract_cmd: str = _get_env("TESSERACT_CMD", "")
    ocr_lang: str = _get_env("OCR_LANG", "chi_sim+eng")
    auth_secret_key: str = _get_env("AUTH_SECRET_KEY", "")
    session_ttl_seconds: int = _parse_int(_get_env("SESSION_TTL_SECONDS", "604800"), 604800)
    auth_cookie_name: str = _get_env("AUTH_COOKIE_NAME", "insightflow_session")
    auth_cookie_secure: bool = _parse_bool(_get_env("AUTH_COOKIE_SECURE", "false"))
    auth_cookie_samesite: str = _get_env("AUTH_COOKIE_SAMESITE", "lax").lower()
    auth_cookie_domain: str | None = os.getenv("AUTH_COOKIE_DOMAIN") or None
    csrf_cookie_name: str = _get_env("CSRF_COOKIE_NAME", "insightflow_csrf")
    csrf_header_name: str = _get_env("CSRF_HEADER_NAME", "X-CSRF-Token")
    csrf_ttl_seconds: int = _parse_int(_get_env("CSRF_TTL_SECONDS", "3600"), 3600)
    session_last_seen_interval_seconds: int = _parse_int(
        _get_env("SESSION_LAST_SEEN_INTERVAL_SECONDS", "300"),
        300,
    )
    password_min_length: int = _parse_int(_get_env("PASSWORD_MIN_LENGTH", "10"), 10)
    login_account_limit: int = _parse_int(_get_env("LOGIN_ACCOUNT_LIMIT", "5"), 5)
    login_ip_limit: int = _parse_int(_get_env("LOGIN_IP_LIMIT", "20"), 20)
    registration_ip_limit: int = _parse_int(_get_env("REGISTRATION_IP_LIMIT", "10"), 10)
    reset_request_limit: int = _parse_int(_get_env("RESET_REQUEST_LIMIT", "3"), 3)
    auth_rate_window_seconds: int = _parse_int(_get_env("AUTH_RATE_WINDOW_SECONDS", "900"), 900)
    auth_block_seconds: int = _parse_int(_get_env("AUTH_BLOCK_SECONDS", "900"), 900)
    enable_legacy_v1_api: bool = _parse_bool(_get_env("ENABLE_LEGACY_V1_API", "true"))
    upload_max_file_size_bytes: int = _parse_int(
        _get_env("UPLOAD_MAX_FILE_SIZE_BYTES", "20971520"),
        20 * 1024 * 1024,
    )
    upload_max_batch_files: int = _parse_int(_get_env("UPLOAD_MAX_BATCH_FILES", "10"), 10)
    workspace_max_files: int = _parse_int(_get_env("WORKSPACE_MAX_FILES", "50"), 50)
    user_storage_quota_bytes: int = _parse_int(
        _get_env("USER_STORAGE_QUOTA_BYTES", "209715200"),
        200 * 1024 * 1024,
    )
    profile_sample_rows: int = _parse_int(_get_env("PROFILE_SAMPLE_ROWS", "200"), 200)
    profile_sample_values_per_column: int = _parse_int(
        _get_env("PROFILE_SAMPLE_VALUES_PER_COLUMN", "3"),
        3,
    )
    understanding_batch_max_files: int = _parse_int(
        _get_env("UNDERSTANDING_BATCH_MAX_FILES", "10"),
        10,
    )
    understanding_model_text_limit: int = _parse_int(
        _get_env("UNDERSTANDING_MODEL_TEXT_LIMIT", "6000"),
        6000,
    )
    pdf_max_pages: int = _parse_int(_get_env("PDF_MAX_PAGES", "200"), 200)
    image_max_pixels: int = _parse_int(_get_env("IMAGE_MAX_PIXELS", "20000000"), 20_000_000)
    relation_min_confidence: float = _parse_float(
        _get_env("RELATION_MIN_CONFIDENCE", "0.60"),
        0.60,
    )
    relation_high_confidence: float = _parse_float(
        _get_env("RELATION_HIGH_CONFIDENCE", "0.80"),
        0.80,
    )
    relation_max_pairs: int = _parse_int(_get_env("RELATION_MAX_PAIRS", "100"), 100)
    relation_model_max_calls: int = _parse_int(
        _get_env("RELATION_MODEL_MAX_CALLS", "5"),
        5,
    )
    workspace_context_max_files: int = _parse_int(
        _get_env("WORKSPACE_CONTEXT_MAX_FILES", "20"),
        20,
    )
    workspace_context_max_chars: int = _parse_int(
        _get_env("WORKSPACE_CONTEXT_MAX_CHARS", "30000"),
        30000,
    )
    worker_poll_interval_seconds: float = _parse_float(
        _get_env("WORKER_POLL_INTERVAL_SECONDS", "2"),
        2,
    )
    worker_lease_seconds: int = _parse_int(_get_env("WORKER_LEASE_SECONDS", "120"), 120)
    worker_heartbeat_seconds: int = _parse_int(
        _get_env("WORKER_HEARTBEAT_SECONDS", "15"),
        15,
    )
    task_max_retries: int = _parse_int(_get_env("TASK_MAX_RETRIES", "1"), 1)
    agent_max_replan_count: int = _parse_int(
        _get_env("AGENT_MAX_REPLAN_COUNT", "1"),
        1,
    )
    agent_max_review_retries: int = _parse_int(
        _get_env("AGENT_MAX_REVIEW_RETRIES", "1"),
        1,
    )
    task_max_clarification_rounds: int = _parse_int(
        _get_env("TASK_MAX_CLARIFICATION_ROUNDS", "2"),
        2,
    )
    task_event_heartbeat_seconds: int = _parse_int(
        _get_env("TASK_EVENT_HEARTBEAT_SECONDS", "15"),
        15,
    )
    task_model_call_budget: int = _parse_int(
        _get_env("TASK_MODEL_CALL_BUDGET", "12"),
        12,
    )
    task_tool_call_budget: int = _parse_int(
        _get_env("TASK_TOOL_CALL_BUDGET", "30"),
        30,
    )
    user_concurrent_tasks: int = _parse_int(_get_env("USER_CONCURRENT_TASKS", "1"), 1)
    user_daily_tasks: int = _parse_int(_get_env("USER_DAILY_TASKS", "20"), 20)
    user_daily_deepseek_calls: int = _parse_int(
        _get_env("USER_DAILY_DEEPSEEK_CALLS", "50"), 50
    )
    user_max_workspaces: int = _parse_int(_get_env("USER_MAX_WORKSPACES", "20"), 20)
    report_history_max_versions: int = _parse_int(
        _get_env("REPORT_HISTORY_MAX_VERSIONS", "10"), 10
    )
    report_export_daily_limit: int = _parse_int(
        _get_env("REPORT_EXPORT_DAILY_LIMIT", "50"), 50
    )
    system_max_running_tasks: int = _parse_int(
        _get_env("SYSTEM_MAX_RUNNING_TASKS", "2"), 2
    )
    pdf_ocr_max_pages: int = _parse_int(_get_env("PDF_OCR_MAX_PAGES", "50"), 50)
    pdf_ocr_dpi: int = _parse_int(_get_env("PDF_OCR_DPI", "150"), 150)
    pdf_ocr_max_pixels_per_page: int = _parse_int(
        _get_env("PDF_OCR_MAX_PIXELS_PER_PAGE", "12000000"), 12_000_000
    )
    pdf_ocr_timeout_seconds: int = _parse_int(
        _get_env("PDF_OCR_TIMEOUT_SECONDS", "120"), 120
    )
    pdf_ocr_min_text_chars: int = _parse_int(
        _get_env("PDF_OCR_MIN_TEXT_CHARS", "20"), 20
    )
    worker_stale_seconds: int = _parse_int(_get_env("WORKER_STALE_SECONDS", "60"), 60)
    session_retention_days: int = _parse_int(_get_env("SESSION_RETENTION_DAYS", "7"), 7)
    revoked_session_retention_days: int = _parse_int(
        _get_env("REVOKED_SESSION_RETENTION_DAYS", "7"), 7
    )
    password_reset_retention_days: int = _parse_int(
        _get_env("PASSWORD_RESET_RETENTION_DAYS", "90"), 90
    )
    task_event_retention_days: int = _parse_int(
        _get_env("TASK_EVENT_RETENTION_DAYS", "180"), 180
    )
    agent_run_retention_days: int = _parse_int(
        _get_env("AGENT_RUN_RETENTION_DAYS", "180"), 180
    )
    workspace_delete_grace_days: int = _parse_int(
        _get_env("WORKSPACE_DELETE_GRACE_DAYS", "30"), 30
    )
    superseded_asset_retention_days: int = _parse_int(
        _get_env("SUPERSEDED_ASSET_RETENTION_DAYS", "30"), 30
    )
    backup_dir: str = _get_env("BACKUP_DIR", "./backups")
    debug: bool = _parse_bool(_get_env("DEBUG", "false"))
    trust_proxy_headers: bool = _parse_bool(_get_env("TRUST_PROXY_HEADERS", "false"))
    trusted_proxy_ips: str = _get_env("TRUSTED_PROXY_IPS", "")
    enable_hsts: bool = _parse_bool(_get_env("ENABLE_HSTS", "false"))
    sqlite_busy_timeout_ms: int = _parse_int(
        _get_env("SQLITE_BUSY_TIMEOUT_MS", "30000"),
        30000,
    )
    sqlite_journal_mode: str = _get_env("SQLITE_JOURNAL_MODE", "WAL").upper()
    database_pool_recycle_seconds: int = _parse_int(
        _get_env("DATABASE_POOL_RECYCLE_SECONDS", "1800"),
        1800,
    )
    log_level: str = _get_env("LOG_LEVEL", "INFO").lower()
    api_graceful_shutdown_seconds: int = _parse_int(
        _get_env("API_GRACEFUL_SHUTDOWN_SECONDS", "60"),
        60,
    )
    public_site_url: str = _get_env("PUBLIC_SITE_URL", "")

    @property
    def cors_origins(self) -> list[str]:
        return _parse_cors_origins(self.cors_origins_raw)


settings = Settings()


def validate_production_security(current_settings: Settings = settings) -> None:
    if current_settings.env.lower() != "production":
        return
    if len(current_settings.auth_secret_key) < 32:
        raise RuntimeError("生产环境必须配置至少 32 个字符的 AUTH_SECRET_KEY")
    if current_settings.auth_secret_key.startswith("replace_"):
        raise RuntimeError("生产环境 AUTH_SECRET_KEY 不能使用示例占位符")
    if len(set(current_settings.auth_secret_key)) < 12:
        raise RuntimeError("生产环境 AUTH_SECRET_KEY 必须具有足够随机性")
    if not current_settings.auth_cookie_secure:
        raise RuntimeError("生产环境必须启用 AUTH_COOKIE_SECURE")
    if current_settings.enable_legacy_v1_api:
        raise RuntimeError("生产环境必须关闭 ENABLE_LEGACY_V1_API")
    if current_settings.debug:
        raise RuntimeError("生产环境必须关闭 DEBUG")
    if not current_settings.trust_proxy_headers:
        raise RuntimeError("生产环境必须配置可信 HTTPS 反向代理头策略")
    trusted_proxies = {
        item.strip() for item in current_settings.trusted_proxy_ips.split(",") if item.strip()
    }
    if not trusted_proxies or trusted_proxies.intersection({"*", "0.0.0.0/0", "::/0"}):
        raise RuntimeError("生产环境 TRUSTED_PROXY_IPS 必须仅包含已知反向代理地址")
    if not current_settings.enable_hsts:
        raise RuntimeError("生产环境 HTTPS 必须启用 ENABLE_HSTS")
    if "*" in current_settings.cors_origins:
        raise RuntimeError("生产环境携带 Cookie 时 CORS_ORIGINS 不能包含 *")
    if (
        not current_settings.public_site_url.lower().startswith("https://")
        or ".example." in current_settings.public_site_url.lower()
    ):
        raise RuntimeError("生产环境 PUBLIC_SITE_URL 必须是已确认的 HTTPS 正式地址")
    if not current_settings.cors_origins or any(
        ".example." in origin.lower() for origin in current_settings.cors_origins
    ):
        raise RuntimeError("生产环境 CORS_ORIGINS 必须是已确认的正式同域地址")
    if current_settings.auth_cookie_samesite not in {"lax", "strict", "none"}:
        raise RuntimeError("生产环境 AUTH_COOKIE_SAMESITE 配置无效")
    if current_settings.log_level not in {"critical", "error", "warning", "info"}:
        raise RuntimeError("生产环境 LOG_LEVEL 配置无效")
    lowered_database = current_settings.database_url.lower()
    if any(marker in lowered_database for marker in (":memory:", "test.db", "pytest", "temporary")):
        raise RuntimeError("生产环境不能使用明显的测试数据库地址")
    if current_settings.database_url.startswith("sqlite:///"):
        sqlite_path = current_settings.database_url.removeprefix("sqlite:///")
        if re.match(r"^[A-Za-z]:[\\/]", sqlite_path):
            raise RuntimeError("生产环境不能使用 Windows 绝对数据库路径")
        if not (sqlite_path.startswith("/") or Path(sqlite_path).is_absolute()):
            raise RuntimeError("生产环境 SQLite 数据库必须使用容器内绝对持久化路径")
        if current_settings.sqlite_journal_mode != "WAL":
            raise RuntimeError("生产环境 SQLite 必须启用 WAL")
        if current_settings.sqlite_busy_timeout_ms < 1000:
            raise RuntimeError("生产环境 SQLite busy timeout 不能低于 1000ms")
    for storage_path in (
        current_settings.upload_dir,
        current_settings.chart_dir,
        current_settings.report_dir,
        current_settings.backup_dir,
    ):
        if re.match(r"^[A-Za-z]:[\\/]", storage_path):
            raise RuntimeError("生产环境不能使用 Windows 绝对 storage 路径")
        if not (storage_path.startswith("/") or Path(storage_path).is_absolute()):
            raise RuntimeError("生产环境 storage 与备份目录必须使用容器内绝对持久化路径")
    if min(
        current_settings.upload_max_file_size_bytes,
        current_settings.user_storage_quota_bytes,
        current_settings.user_daily_tasks,
        current_settings.task_model_call_budget,
        current_settings.task_tool_call_budget,
    ) <= 0:
        raise RuntimeError("生产环境文件上限与配额必须配置为正数")
    admin_password = os.getenv("ADMIN_PASSWORD", "")
    if admin_password and (
        len(admin_password) < 14
        or admin_password.lower() in {"admin", "password", "changeme", "admin123456"}
    ):
        raise RuntimeError("生产环境不能使用默认或弱管理员密码")
