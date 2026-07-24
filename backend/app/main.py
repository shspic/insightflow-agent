from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.files import router as files_router
from app.api.health import router as health_router
from app.api.reports import router as reports_router
from app.api.tasks import router as tasks_router
from app.api.v2.auth import router as v2_auth_router
from app.api.v2.admin import router as v2_admin_router
from app.api.v2.file_understanding import router as v2_file_understanding_router
from app.api.v2.reports_governance import router as v2_reports_governance_router
from app.api.v2.operations import router as v2_operations_router
from app.api.v2.workspace_files import router as v2_workspace_files_router
from app.api.v2.workspace_tasks import router as v2_workspace_tasks_router
from app.api.v2.workspaces import router as v2_workspaces_router
from app.core.config import BACKEND_DIR, settings, validate_production_security
from app.services.health_service import validate_production_runtime

validate_production_security()
validate_production_runtime()
app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; frame-ancestors 'none'; object-src 'none'; "
        "base-uri 'self'; connect-src 'self'"
    )
    if settings.env.lower() == "production" and settings.enable_hsts:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

app.include_router(health_router)
app.include_router(v2_auth_router)
app.include_router(v2_admin_router)
app.include_router(v2_workspaces_router)
app.include_router(v2_file_understanding_router)
app.include_router(v2_reports_governance_router)
app.include_router(v2_operations_router)
app.include_router(v2_workspace_files_router)
app.include_router(v2_workspace_tasks_router)

if settings.enable_legacy_v1_api:
    chart_dir = BACKEND_DIR / settings.chart_dir
    chart_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static/charts", StaticFiles(directory=chart_dir), name="charts")
    app.include_router(files_router)
    app.include_router(tasks_router)
    app.include_router(reports_router)
