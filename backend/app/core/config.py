import os
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
    llm_api_key: str = _get_env("LLM_API_KEY", "")
    llm_model: str = _get_env("LLM_MODEL", "deepseek-chat")
    llm_base_url: str = _get_env("LLM_BASE_URL", "")
    llm_enabled: bool = _parse_bool(_get_env("LLM_ENABLED", "true"))
    llm_max_retries: int = _parse_int(_get_env("LLM_MAX_RETRIES", "1"), 1)
    embedding_provider: str = _get_env("EMBEDDING_PROVIDER", "local")
    vector_store: str = _get_env("VECTOR_STORE", "chroma")
    rag_retrieval_mode: str = _get_env("RAG_RETRIEVAL_MODE", "auto")
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
        _get_env("TASK_TOOL_CALL_BUDGET", "20"),
        20,
    )

    @property
    def cors_origins(self) -> list[str]:
        return _parse_cors_origins(self.cors_origins_raw)


settings = Settings()


def validate_production_security(current_settings: Settings = settings) -> None:
    if current_settings.env.lower() != "production":
        return
    if len(current_settings.auth_secret_key) < 32:
        raise RuntimeError("生产环境必须配置至少 32 个字符的 AUTH_SECRET_KEY")
    if not current_settings.auth_cookie_secure:
        raise RuntimeError("生产环境必须启用 AUTH_COOKIE_SECURE")
    if current_settings.enable_legacy_v1_api:
        raise RuntimeError("生产环境必须关闭 ENABLE_LEGACY_V1_API")
