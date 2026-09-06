from collections import Counter

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.models import (
    MaterialRecord, MatchCandidate, ApprovalRecord, ApprovalStatus, MatchType,
    NationalMaterialCode, SyncLog,
)
from app.schemas.schemas import DashboardStatsOut

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats", response_model=DashboardStatsOut)
def get_dashboard_stats(db: Session = Depends(get_db)):
    total_materials = db.query(MaterialRecord).count()

    cpse_counts = dict(
        db.query(MaterialRecord.source_cpse, func.count(MaterialRecord.id))
        .group_by(MaterialRecord.source_cpse).all()
    )

    match_type_counts = dict(
        db.query(MatchCandidate.match_type, func.count(MatchCandidate.id))
        .group_by(MatchCandidate.match_type).all()
    )
    match_type_counts = {k.value if hasattr(k, "value") else k: v for k, v in match_type_counts.items()}

    approval_counts = dict(
        db.query(ApprovalRecord.status, func.count(ApprovalRecord.id))
        .group_by(ApprovalRecord.status).all()
    )
    approval_counts = {k.value if hasattr(k, "value") else k: v for k, v in approval_counts.items()}

    all_confidences = [c for (c,) in db.query(MatchCandidate.final_confidence).all()]
    buckets = {"90-100": 0, "75-89": 0, "55-74": 0, "0-54": 0}
    for c in all_confidences:
        if c >= 90:
            buckets["90-100"] += 1
        elif c >= 75:
            buckets["75-89"] += 1
        elif c >= 55:
            buckets["55-74"] += 1
        else:
            buckets["0-54"] += 1

    category_counts = dict(
        db.query(MaterialRecord.category, func.count(MaterialRecord.id))
        .filter(MaterialRecord.category.isnot(None))
        .group_by(MaterialRecord.category).all()
    )

    recent_syncs = (
        db.query(SyncLog).order_by(SyncLog.sync_started_at.desc()).limit(5).all()
    )

    total_ncs = db.query(NationalMaterialCode).count()
    materials_with_nmc = db.query(MaterialRecord).filter(MaterialRecord.national_material_code.isnot(None)).count()
    duplicate_reduction_pct = (
        round((1 - total_ncs / materials_with_nmc) * 100, 1)
        if materials_with_nmc > 0 else 0.0
    )

    return DashboardStatsOut(
        total_materials=total_materials,
        materials_by_cpse=cpse_counts,
        exact_duplicates=match_type_counts.get(MatchType.EXACT_DUPLICATE.value, 0),
        near_duplicates=match_type_counts.get(MatchType.NEAR_DUPLICATE.value, 0),
        functionally_equivalent=match_type_counts.get(MatchType.FUNCTIONALLY_EQUIVALENT.value, 0),
        possible_matches=match_type_counts.get(MatchType.POSSIBLE_MATCH.value, 0),
        pending_approvals=approval_counts.get(ApprovalStatus.PENDING.value, 0),
        approved_mappings=approval_counts.get(ApprovalStatus.APPROVED.value, 0),
        rejected_mappings=approval_counts.get(ApprovalStatus.REJECTED.value, 0),
        confidence_distribution=buckets,
        material_categories=category_counts,
        recently_synced=[
            {
                "cpse": s.cpse_name, "status": s.status,
                "records_fetched": s.records_fetched,
                "sync_completed_at": s.sync_completed_at.isoformat() if s.sync_completed_at else None,
            }
            for s in recent_syncs
        ],
        total_national_codes=total_ncs,
        duplicate_reduction_pct=duplicate_reduction_pct,
    )
