"""
PHASE 7: Human-in-the-loop Approval Workflow (persisted).

Extends the prototype's in-memory ApprovalWorkflow (approval.py) into a
database-backed service. Same semantics: AI recommends, humans decide,
every state transition is logged to AuditLog.
"""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.models import (
    MatchCandidate, ApprovalRecord, ApprovalStatus, AuditLog, MatchType
)
from app.services import nmc_service


def create_approval_for_match(db: Session, match: MatchCandidate) -> ApprovalRecord:
    approval = ApprovalRecord(match_candidate_id=match.id, status=ApprovalStatus.PENDING)
    db.add(approval)
    db.add(AuditLog(
        material_id=None,
        match_candidate_id=match.id,
        action="AI_RECOMMENDATION_CREATED",
        old_value=None,
        new_value=match.match_type.value,
        performed_by="AI_MATCHER",
        ai_confidence=match.final_confidence,
        reason=(
            f"lexical={match.lexical_similarity}% semantic={match.semantic_similarity}% "
            f"technical={match.technical_similarity}%"
        ),
    ))
    db.flush()
    return approval


def approve(db: Session, approval: ApprovalRecord, approved_by: str, reason: str = "",
            create_nmc: bool = True) -> ApprovalRecord:
    old_status = approval.status
    approval.status = ApprovalStatus.APPROVED
    approval.approved_by = approved_by
    approval.approval_date = datetime.now(timezone.utc)

    db.add(AuditLog(
        match_candidate_id=approval.match_candidate_id,
        action="APPROVED",
        old_value=old_status.value,
        new_value=ApprovalStatus.APPROVED.value,
        performed_by=approved_by,
        reason=reason,
    ))

    if create_nmc:
        match = approval.match_candidate
        material_a, material_b = match.material_a, match.material_b

        # If either material already has an NMC, reuse it (extends the cluster);
        # otherwise mint a new one.
        existing_code = material_a.national_material_code or material_b.national_material_code
        if existing_code:
            from app.models.models import NationalMaterialCode
            nmc = db.query(NationalMaterialCode).filter_by(code=existing_code).first()
        else:
            nmc = nmc_service.get_or_create_nmc(
                db,
                canonical_description=material_a.standardized_description,
                canonical_category=material_a.standardized_category,
            )

        nmc_service.assign_material_to_nmc(db, material_a, nmc, approved_by)
        nmc_service.assign_material_to_nmc(db, material_b, nmc, approved_by)

    db.flush()
    return approval


def reject(db: Session, approval: ApprovalRecord, rejected_by: str, reason: str = "") -> ApprovalRecord:
    old_status = approval.status
    approval.status = ApprovalStatus.REJECTED
    db.add(AuditLog(
        match_candidate_id=approval.match_candidate_id,
        action="REJECTED",
        old_value=old_status.value,
        new_value=ApprovalStatus.REJECTED.value,
        performed_by=rejected_by,
        reason=reason,
    ))
    db.flush()
    return approval


def mark_needs_review(db: Session, approval: ApprovalRecord, reviewer: str, reason: str = "") -> ApprovalRecord:
    old_status = approval.status
    approval.status = ApprovalStatus.NEEDS_REVIEW
    db.add(AuditLog(
        match_candidate_id=approval.match_candidate_id,
        action="MARKED_NEEDS_REVIEW",
        old_value=old_status.value,
        new_value=ApprovalStatus.NEEDS_REVIEW.value,
        performed_by=reviewer,
        reason=reason,
    ))
    db.flush()
    return approval
