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

    @property
    def cors_origins(self) -> list[str]:
        return _parse_cors_origins(self.cors_origins_raw)


settings = Settings()
