from datetime import date

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_roles
from app.models.user import ROLE_ADMIN, ROLE_CAJA, User
from app.services import report_service

router = APIRouter(prefix="/api/reports", tags=["Reportes"])


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), _: User = Depends(require_roles(ROLE_ADMIN, ROLE_CAJA))):
    return report_service.dashboard(db)


@router.get("/finance")
def finance(date_from: date, date_to: date, db: Session = Depends(get_db), _: User = Depends(require_roles(ROLE_ADMIN))):
    return report_service.finance(db, date_from, date_to)


@router.get("/sales.csv", response_class=Response)
def sales_csv(date_from: date, date_to: date, db: Session = Depends(get_db), _: User = Depends(require_roles(ROLE_ADMIN))):
    content = report_service.sales_csv(db, date_from, date_to)
    return Response(content, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="ventas_{date_from}_{date_to}.csv"'})
