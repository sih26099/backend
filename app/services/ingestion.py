"""
PHASE 1-2 (persist), 9 (sync orchestration), 10 (continuous duplicate check).

Wires together:
  - column mapping + normalization (existing normalize.py, reused as-is)
  - full attribute extraction (standardization.py)
  - persistence into MaterialRecord rows
  - mock CPSE API sync with incremental (last_modified_date) support
  - continuous duplicate detection: every newly ingested material is
    immediately compared against the existing material master, not just
    batch-matched later
"""

from datetime import datetime, timezone

import pandas as pd
from sqlalchemy.orm import Session

from app.models.models import MaterialRecord, SyncLog, MatchCandidate, MatchType
from app.services.normalize import map_columns
from app.services.standardization import (
    extract_full_attributes, build_standardized_description,
    build_standardized_category, build_standardized_specification,
)
from app.services.matching import MaterialView, compare_pair
from app.services import mock_cpse_api
from app.services.approval_service import create_approval_for_match


def _apply_standardization(material: MaterialRecord):
    """Runs attribute extraction + standardization on a single record and
    writes the results back onto it. Called on every create/update."""
    attrs = extract_full_attributes(material.material_description, material.specification or "")

    for field in ["category", "material_type", "standard", "connection_type",
                  "pressure_rating", "grade", "thread_type", "diameter",
                  "length", "width", "height", "weight"]:
        # extract_full_attributes uses slightly different key names for some fields
        key = {"connection_type": "connection"}.get(field, field)
        if key in attrs:
            setattr(material, field, attrs[key])

    material.technical_parameters = attrs
    material.standardized_description = build_standardized_description(
        attrs, material.material_description
    )
    material.standardized_category = build_standardized_category(attrs)
    material.standardized_specification = build_standardized_specification(attrs)


def _material_to_view(material: MaterialRecord) -> MaterialView:
    return MaterialView(
        id=material.id,
        source_cpse=material.source_cpse,
        text_for_matching=material.standardized_description or material.material_description,
        attributes=material.technical_parameters or {},
    )


def ingest_dataframe(db: Session, df: pd.DataFrame, cpse_name: str,
                      source_document: str = None, source_erp: str = None,
                      check_duplicates: bool = True) -> dict:
    """
    PHASE 1-2: Ingest a dataframe (from an uploaded CSV/Excel) into the
    material master, applying standardization to each row.

    PHASE 10: If check_duplicates=True, each newly created record is
    immediately compared against the existing master (not just other rows
    in this same upload) so duplicates never silently accumulate.
    """
    mapping = map_columns(list(df.columns))
    created, updated, duplicate_candidates = 0, 0, 0

    for _, row in df.iterrows():
        common = {raw_col: row.get(raw_col) for raw_col in mapping}
        common_named = {mapping[k]: v for k, v in common.items()}

        code = str(common_named.get("existing_material_code", "")).strip()
        desc = str(common_named.get("material_description", "")).strip()
        spec = str(common_named.get("specification", "")).strip() if common_named.get("specification") else ""

        if not desc or desc.lower() == "nan":
            continue
        if not code or code.lower() == "nan":
            import uuid
            code = f"AUTO-{uuid.uuid4().hex[:8].upper()}"

        existing = (
            db.query(MaterialRecord)
            .filter_by(source_cpse=cpse_name, existing_material_code=code)
            .first()
        )

        if existing:
            existing.material_description = desc
            existing.specification = spec or existing.specification
            existing.last_modified_date = datetime.now(timezone.utc)
            _apply_standardization(existing)
            material = existing
            updated += 1
        else:
            material = MaterialRecord(
                source_cpse=cpse_name,
                existing_material_code=code,
                material_description=desc,
                specification=spec,
                source_document=source_document,
                source_erp=source_erp,
            )
            _apply_standardization(material)
            db.add(material)
            created += 1

        db.flush()

        if check_duplicates:
            duplicate_candidates += _check_against_master(db, material)

    db.commit()
    return {
        "cpse": cpse_name,
        "created": created,
        "updated": updated,
        "duplicate_candidates_found": duplicate_candidates,
    }


def _check_against_master(db: Session, new_material: MaterialRecord) -> int:
    """
    PHASE 10: Compare a single new/updated material against all existing
    materials from OTHER CPSEs, creating MatchCandidate + approval rows for
    anything above the review threshold. Returns count of candidates found.

    Note: O(n) per new record. Fine at prototype/demo scale (hundreds-low
    thousands of records); a real deployment would replace the linear scan
    with an approximate-nearest-neighbor vector index (e.g. pgvector) while
    keeping this function's interface unchanged.
    """
    others = (
        db.query(MaterialRecord)
        .filter(MaterialRecord.source_cpse != new_material.source_cpse)
        .filter(MaterialRecord.id != new_material.id)
        .all()
    )
    if not others:
        return 0

    new_view = _material_to_view(new_material)
    found = 0

    for other in others:
        other_view = _material_to_view(other)
        evidence = compare_pair(new_view, other_view)

        if evidence.match_type == MatchType.DISTINCT_MATERIAL:
            continue

        # avoid duplicate MatchCandidate rows for the same pair
        exists = (
            db.query(MatchCandidate)
            .filter(
                MatchCandidate.material_a_id.in_([new_material.id, other.id]),
                MatchCandidate.material_b_id.in_([new_material.id, other.id]),
            )
            .first()
        )
        if exists:
            continue

        match = MatchCandidate(
            material_a_id=new_material.id,
            material_b_id=other.id,
            lexical_similarity=evidence.lexical_similarity,
            semantic_similarity=evidence.semantic_similarity,
            technical_similarity=evidence.technical_similarity,
            final_confidence=evidence.final_confidence,
            match_type=evidence.match_type,
            critical_conflicts=evidence.critical_conflicts,
            evidence={
                "attribute_comparisons": [
                    {
                        "attribute": c.attribute, "value_a": c.value_a,
                        "value_b": c.value_b, "match": c.match, "critical": c.critical,
                    }
                    for c in evidence.attribute_comparisons
                ]
            },
        )
        db.add(match)
        db.flush()
        create_approval_for_match(db, match)
        found += 1

    return found


def sync_cpse(db: Session, cpse_name: str, page_size: int = 25) -> SyncLog:
    """
    PHASE 9: Pull all pages from a mock CPSE API, incrementally (using the
    last successful sync's cursor if one exists), map into the common schema,
    and ingest. Records a SyncLog row regardless of success/failure.
    """
    last_sync = (
        db.query(SyncLog)
        .filter_by(cpse_name=cpse_name, status="SUCCESS")
        .order_by(SyncLog.sync_completed_at.desc())
        .first()
    )
    modified_since = last_sync.last_modified_cursor if last_sync else None

    sync_log = SyncLog(cpse_name=cpse_name, status="RUNNING")
    db.add(sync_log)
    db.flush()

    try:
        page = 1
        all_records = []
        latest_cursor = modified_since

        while True:
            response = mock_cpse_api.fetch_materials(
                cpse_name, page=page, page_size=page_size, modified_since=modified_since
            )
            all_records.extend(response["records"])
            for r in response["records"]:
                ts = datetime.fromisoformat(r["last_modified_date"])
                if latest_cursor is None or ts > latest_cursor:
                    latest_cursor = ts
            if not response["has_more"]:
                break
            page += 1

        df = pd.DataFrame([
            {"Material Code": r["material_code"], "Description": r["description"],
             "Specification": r["specification"]}
            for r in all_records
        ]) if all_records else pd.DataFrame(columns=["Material Code", "Description", "Specification"])

        result = ingest_dataframe(db, df, cpse_name, source_erp="MOCK_CPSE_API")

        sync_log.records_fetched = len(all_records)
        sync_log.records_created = result["created"]
        sync_log.records_updated = result["updated"]
        sync_log.duplicate_candidates_found = result["duplicate_candidates_found"]
        sync_log.last_modified_cursor = latest_cursor
        sync_log.status = "SUCCESS"
        sync_log.sync_completed_at = datetime.now(timezone.utc)

    except mock_cpse_api.CPSEAPIError as e:
        sync_log.status = "FAILED"
        sync_log.error_message = str(e)
        sync_log.sync_completed_at = datetime.now(timezone.utc)

    db.commit()
    return sync_log
