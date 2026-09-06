from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.models import ApprovalRecord, ApprovalStatus
from app.schemas.schemas import ApprovalOut, ApprovalDecisionIn
from app.services import approval_service

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


@router.get("", response_model=list[ApprovalOut])
def list_approvals(
    status: str | None = None,
    limit: int = Query(100, le=1000),
    db: Session = Depends(get_db),
):
    q = db.query(ApprovalRecord)
    if status:
        try:
            q = q.filter(ApprovalRecord.status == ApprovalStatus(status))
        except ValueError:
            raise HTTPException(400, f"Invalid status: {status}")
    return q.order_by(ApprovalRecord.created_date.desc()).limit(limit).all()


@router.get("/{approval_id}", response_model=ApprovalOut)
def get_approval(approval_id: str, db: Session = Depends(get_db)):
    approval = db.query(ApprovalRecord).filter_by(id=approval_id).first()
    if not approval:
        raise HTTPException(404, "Approval not found")
    return approval


@router.post("/{approval_id}/decide", response_model=ApprovalOut)
def decide_approval(approval_id: str, payload: ApprovalDecisionIn, db: Session = Depends(get_db)):
    """
    PHASE 7: Human decision endpoint. decision = APPROVE | REJECT | NEEDS_REVIEW.
    APPROVE triggers National Material Code assignment (Phase 8) for both
    materials in the match candidate.
    """
    approval = db.query(ApprovalRecord).filter_by(id=approval_id).first()
    if not approval:
        raise HTTPException(404, "Approval not found")
    if approval.status != ApprovalStatus.PENDING:
        raise HTTPException(400, f"Approval already resolved with status {approval.status.value}")

    decision = payload.decision.upper()
    if decision == "APPROVE":
        approval_service.approve(db, approval, payload.performed_by, payload.reason or "")
    elif decision == "REJECT":
        approval_service.reject(db, approval, payload.performed_by, payload.reason or "")
    elif decision == "NEEDS_REVIEW":
        approval_service.mark_needs_review(db, approval, payload.performed_by, payload.reason or "")
    else:
        raise HTTPException(400, "decision must be APPROVE, REJECT, or NEEDS_REVIEW")

    db.commit()
    db.refresh(approval)
    return approval
