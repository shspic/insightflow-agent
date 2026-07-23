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
from app.api.v2.workspace_files import router as v2_workspace_files_router
from app.api.v2.workspace_tasks import router as v2_workspace_tasks_router
from app.api.v2.workspaces import router as v2_workspaces_router
from app.core.config import BACKEND_DIR, settings, validate_production_security

validate_production_security()
app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(v2_auth_router)
app.include_router(v2_admin_router)
app.include_router(v2_workspaces_router)
app.include_router(v2_file_understanding_router)
app.include_router(v2_workspace_files_router)
app.include_router(v2_workspace_tasks_router)

if settings.enable_legacy_v1_api:
    chart_dir = BACKEND_DIR / settings.chart_dir
    chart_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static/charts", StaticFiles(directory=chart_dir), name="charts")
    app.include_router(files_router)
    app.include_router(tasks_router)
    app.include_router(reports_router)
