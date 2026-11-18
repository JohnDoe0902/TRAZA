from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.api.deps import DbSession
from backend.services import health_service

router = APIRouter(tags=["health"])


@router.get("/health")
def health(db: DbSession) -> JSONResponse:
    report = health_service.check(db)
    # 503 avisa a quien vigila el servicio que algo no anda bien
    status_code = 200 if report.is_healthy else 503
    return JSONResponse(status_code=status_code, content=report.as_dict())
