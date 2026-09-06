from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.models import SyncLog
from app.schemas.schemas import SyncLogOut
from app.services import ingestion, mock_cpse_api

router = APIRouter(prefix="/api/sync", tags=["cpse-sync"])


@router.get("/connectors")
def list_connectors():
    """Available mock CPSE API connectors (Phase 9). Swap for real authorized
    CPSE endpoints later without changing anything downstream."""
    return {"connectors": mock_cpse_api.list_available_cpse_connectors()}


@router.post("/{cpse_name}", response_model=SyncLogOut)
def sync_cpse_now(cpse_name: str, db: Session = Depends(get_db)):
    """
    PHASE 9: Trigger a sync against a (mock) CPSE API. Uses incremental sync
    (last_modified_date cursor) if a prior successful sync exists.
    PHASE 10: Each ingested record is checked against the existing master.
    """
    return ingestion.sync_cpse(db, cpse_name)


@router.get("/logs", response_model=list[SyncLogOut])
def sync_history(cpse: str | None = None, limit: int = Query(50, le=500), db: Session = Depends(get_db)):
    q = db.query(SyncLog)
    if cpse:
        q = q.filter(SyncLog.cpse_name == cpse)
    return q.order_by(SyncLog.sync_started_at.desc()).limit(limit).all()
