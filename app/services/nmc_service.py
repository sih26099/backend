"""
PHASE 8: Common National Material Code + Legacy Code Rationalization.

Generates/assigns NMC-XXXXXX codes to approved material clusters and
maintains the full legacy mapping (old CPSE code -> NMC), which is NEVER
deleted -- superseded mappings are marked inactive, not removed, so full
history stays traceable per the spec's explicit requirement.
"""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.models import (
    NationalMaterialCode, LegacyCodeMapping, MaterialRecord, AuditLog
)


def _next_nmc_sequence(db: Session) -> int:
    count = db.query(NationalMaterialCode).count()
    return count + 1


def get_or_create_nmc(db: Session, canonical_description: str = None,
                       canonical_category: str = None) -> NationalMaterialCode:
    seq = _next_nmc_sequence(db)
    code = f"NMC-{seq:06d}"
    # extremely unlikely collision guard (concurrent creation) -- bump until free
    while db.query(NationalMaterialCode).filter_by(code=code).first():
        seq += 1
        code = f"NMC-{seq:06d}"

    nmc = NationalMaterialCode(
        code=code,
        canonical_description=canonical_description,
        canonical_category=canonical_category,
    )
    db.add(nmc)
    db.flush()
    return nmc


def assign_material_to_nmc(db: Session, material: MaterialRecord,
                            nmc: NationalMaterialCode, performed_by: str) -> LegacyCodeMapping:
    """
    Assigns a material to a National Material Code, creating a legacy mapping
    entry. If the material already has an active mapping to a DIFFERENT nmc,
    that old mapping is marked inactive (superseded) -- never deleted.
    """
    existing = (
        db.query(LegacyCodeMapping)
        .filter_by(material_id=material.id, is_active=True)
        .first()
    )
    if existing and existing.national_material_code != nmc.code:
        existing.is_active = False
        existing.superseded_date = datetime.now(timezone.utc)
        db.add(AuditLog(
            material_id=material.id,
            action="NMC_MAPPING_SUPERSEDED",
            old_value=existing.national_material_code,
            new_value=nmc.code,
            performed_by=performed_by,
            reason="Reassigned to a different national material code",
        ))

    mapping = LegacyCodeMapping(
        source_cpse=material.source_cpse,
        existing_material_code=material.existing_material_code,
        material_id=material.id,
        national_material_code=nmc.code,
        is_active=True,
    )
    db.add(mapping)

    material.national_material_code = nmc.code
    db.add(AuditLog(
        material_id=material.id,
        action="NMC_ASSIGNED",
        old_value=None,
        new_value=nmc.code,
        performed_by=performed_by,
    ))
    db.flush()
    return mapping


def get_legacy_mappings_for_nmc(db: Session, nmc_code: str) -> list[LegacyCodeMapping]:
    """Full history (active and superseded) for a given NMC -- used by the
    'maintain the complete mapping' requirement and the audit trail UI."""
    return (
        db.query(LegacyCodeMapping)
        .filter_by(national_material_code=nmc_code)
        .order_by(LegacyCodeMapping.created_date)
        .all()
    )
