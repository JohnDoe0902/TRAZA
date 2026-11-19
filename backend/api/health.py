from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.api.deps import DbSession
from backend.services import health_service

router = APIRouter(tags=["health"])


@router.get("/health")
def health(db: DbSession) -> JSONResponse:
    report = health_service.check(db)
    # 503 solo si la base cae. Con el worker caído la web sigue registrando tickets
    return JSONResponse(status_code=report.http_status, content=report.as_dict())
