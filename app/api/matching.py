from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.models import MaterialRecord, MatchCandidate, MatchType
from app.schemas.schemas import MatchCandidateOut, ComparePairIn, CompareResultOut, AttributeComparisonOut, MaterialOut
from app.services.matching import find_matches, compare_pair, MaterialView
from app.services.approval_service import create_approval_for_match

router = APIRouter(prefix="/api/matching", tags=["matching"])


def _material_to_view(m: MaterialRecord) -> MaterialView:
    return MaterialView(
        id=m.id,
        source_cpse=m.source_cpse,
        text_for_matching=m.standardized_description or m.material_description,
        attributes=m.technical_parameters or {},
    )


@router.post("/run")
def run_batch_matching(cpse: str | None = None, db: Session = Depends(get_db)):
    """
    PHASE 3-6: Run hybrid matching (lexical + semantic + technical) across
    the full material master (or a single CPSE's records vs. everyone else),
    persisting MatchCandidate rows and creating approval recommendations for
    anything that isn't DISTINCT_MATERIAL.
    """
    q = db.query(MaterialRecord)
    if cpse:
        q = q.filter(MaterialRecord.source_cpse == cpse)
    materials = q.all()

    if len(materials) < 2:
        return {"matches_found": 0, "message": "Not enough materials to compare"}

    views = [_material_to_view(m) for m in materials]
    evidences = find_matches(views)

    created = 0
    for ev in evidences:
        exists = (
            db.query(MatchCandidate)
            .filter(
                MatchCandidate.material_a_id.in_([ev.material_a_id, ev.material_b_id]),
                MatchCandidate.material_b_id.in_([ev.material_a_id, ev.material_b_id]),
            )
            .first()
        )
        if exists:
            continue

        match = MatchCandidate(
            material_a_id=ev.material_a_id,
            material_b_id=ev.material_b_id,
            lexical_similarity=ev.lexical_similarity,
            semantic_similarity=ev.semantic_similarity,
            technical_similarity=ev.technical_similarity,
            final_confidence=ev.final_confidence,
            match_type=ev.match_type,
            critical_conflicts=ev.critical_conflicts,
            evidence={
                "attribute_comparisons": [
                    {"attribute": c.attribute, "value_a": c.value_a, "value_b": c.value_b,
                     "match": c.match, "critical": c.critical}
                    for c in ev.attribute_comparisons
                ]
            },
        )
        db.add(match)
        db.flush()
        create_approval_for_match(db, match)
        created += 1

    db.commit()
    return {"materials_compared": len(materials), "matches_found": len(evidences), "new_candidates_created": created}


@router.get("/candidates", response_model=list[MatchCandidateOut])
def list_candidates(
    match_type: str | None = None,
    min_confidence: float | None = None,
    limit: int = Query(100, le=1000),
    db: Session = Depends(get_db),
):
    q = db.query(MatchCandidate)
    if match_type:
        try:
            q = q.filter(MatchCandidate.match_type == MatchType(match_type))
        except ValueError:
            raise HTTPException(400, f"Invalid match_type: {match_type}")
    if min_confidence is not None:
        q = q.filter(MatchCandidate.final_confidence >= min_confidence)
    return q.order_by(MatchCandidate.final_confidence.desc()).limit(limit).all()


@router.get("/candidates/{candidate_id}", response_model=MatchCandidateOut)
def get_candidate(candidate_id: str, db: Session = Depends(get_db)):
    match = db.query(MatchCandidate).filter_by(id=candidate_id).first()
    if not match:
        raise HTTPException(404, "Match candidate not found")
    return match


@router.post("/compare", response_model=CompareResultOut)
def compare_two_materials(payload: ComparePairIn, db: Session = Depends(get_db)):
    """
    PHASE 11: Material comparison screen backend. Given two material IDs,
    returns the full hybrid comparison breakdown for side-by-side display.
    """
    a = db.query(MaterialRecord).filter_by(id=payload.material_a_id).first()
    b = db.query(MaterialRecord).filter_by(id=payload.material_b_id).first()
    if not a or not b:
        raise HTTPException(404, "One or both materials not found")

    evidence = compare_pair(_material_to_view(a), _material_to_view(b))

    return CompareResultOut(
        material_a=MaterialOut.model_validate(a),
        material_b=MaterialOut.model_validate(b),
        lexical_similarity=evidence.lexical_similarity,
        semantic_similarity=evidence.semantic_similarity,
        technical_similarity=evidence.technical_similarity,
        final_confidence=evidence.final_confidence,
        match_type=evidence.match_type.value,
        critical_conflicts=evidence.critical_conflicts,
        attribute_comparisons=[
            AttributeComparisonOut(
                attribute=c.attribute, value_a=c.value_a, value_b=c.value_b,
                match=c.match, critical=c.critical,
            )
            for c in evidence.attribute_comparisons
        ],
    )
