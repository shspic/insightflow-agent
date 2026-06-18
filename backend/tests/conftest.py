import os
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


SAFE_TEST_ENV = {
    "APP_NAME": "InsightFlow Agent",
    "ENV": "testing",
    "DATABASE_URL": "sqlite:///:memory:",
    "LLM_PROVIDER": "deepseek",
    "LLM_API_KEY": "",
    "LLM_MODEL": "deepseek-chat",
    "LLM_BASE_URL": "",
    "LLM_ENABLED": "false",
    "EMBEDDING_PROVIDER": "local",
    "VECTOR_STORE": "local",
    "RAG_RETRIEVAL_MODE": "auto",
    "RAG_TOP_K": "5",
    "RAG_CHUNK_SIZE": "800",
    "RAG_CHUNK_OVERLAP": "100",
    "UPLOAD_DIR": "./storage/uploads",
    "CHART_DIR": "./storage/charts",
    "REPORT_DIR": "./storage/reports",
    "CORS_ORIGINS": "http://localhost:5173",
    "TESSERACT_CMD": "",
    "OCR_LANG": "chi_sim+eng",
}


for key, value in SAFE_TEST_ENV.items():
    os.environ[key] = value
