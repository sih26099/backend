from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.models import NationalMaterialCode, LegacyCodeMapping, MaterialRecord
from app.schemas.schemas import NMCMappingOut

router = APIRouter(prefix="/api/nmc", tags=["national-material-codes"])


@router.get("", response_model=list[dict])
def list_nmcs(db: Session = Depends(get_db)):
    codes = db.query(NationalMaterialCode).order_by(NationalMaterialCode.created_date.desc()).all()
    return [
        {
            "code": c.code,
            "canonical_description": c.canonical_description,
            "canonical_category": c.canonical_category,
            "created_date": c.created_date,
            "member_count": db.query(MaterialRecord).filter_by(national_material_code=c.code).count(),
        }
        for c in codes
    ]


@router.get("/{code}", response_model=NMCMappingOut)
def get_nmc_mapping(code: str, db: Session = Depends(get_db)):
    """
    PHASE 8: Full legacy code mapping for a National Material Code.
    Returns ALL mappings (active and superseded) -- original CPSE codes are
    never destroyed, so the full history is always visible here.
    """
    nmc = db.query(NationalMaterialCode).filter_by(code=code).first()
    if not nmc:
        raise HTTPException(404, "National Material Code not found")

    mappings = (
        db.query(LegacyCodeMapping)
        .filter_by(national_material_code=code)
        .order_by(LegacyCodeMapping.created_date)
        .all()
    )

    return NMCMappingOut(
        national_material_code=code,
        canonical_description=nmc.canonical_description,
        members=[
            {
                "source_cpse": m.source_cpse,
                "existing_material_code": m.existing_material_code,
                "material_id": m.material_id,
                "is_active": m.is_active,
                "created_date": m.created_date.isoformat(),
                "superseded_date": m.superseded_date.isoformat() if m.superseded_date else None,
            }
            for m in mappings
        ],
    )
