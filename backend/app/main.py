from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.files import router as files_router
from app.api.health import router as health_router
from app.core.config import BACKEND_DIR, settings

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

chart_dir = BACKEND_DIR / settings.chart_dir
chart_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static/charts", StaticFiles(directory=chart_dir), name="charts")

app.include_router(health_router)
app.include_router(files_router)
