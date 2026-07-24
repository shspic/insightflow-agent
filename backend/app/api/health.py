from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.services.health_service import readiness_details


router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "app_name": settings.app_name}


@router.get("/health/ready")
def readiness_check(db: Session = Depends(get_db)) -> JSONResponse:
    result = readiness_details(db)
    return JSONResponse(
        content=result,
        status_code=200 if result["status"] in {"ready", "degraded"} else 503,
    )


@router.get("/health/details")
def health_details(request: Request, db: Session = Depends(get_db)) -> dict:
    if settings.env.lower() not in {"development", "testing"}:
        user = get_current_user(request, db)
        if user.role != "admin":
            raise HTTPException(status_code=403, detail="需要管理员权限")
    return readiness_details(db)
