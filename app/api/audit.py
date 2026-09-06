from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.models import AuditLog
from app.schemas.schemas import AuditLogOut

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("", response_model=list[AuditLogOut])
def list_audit_logs(
    material_id: str | None = None,
    match_candidate_id: str | None = None,
    limit: int = Query(100, le=1000),
    db: Session = Depends(get_db),
):
    q = db.query(AuditLog)
    if material_id:
        q = q.filter(AuditLog.material_id == material_id)
    if match_candidate_id:
        q = q.filter(AuditLog.match_candidate_id == match_candidate_id)
    return q.order_by(AuditLog.timestamp.desc()).limit(limit).all()
