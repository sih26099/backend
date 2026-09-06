import io

import pandas as pd
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.models import MaterialRecord
from app.schemas.schemas import MaterialOut, SearchResultOut
from app.services.ingestion import ingest_dataframe
from app.services.matching import MaterialView, compute_embeddings, cosine_sim_matrix

router = APIRouter(prefix="/api/materials", tags=["materials"])


@router.post("/upload")
async def upload_materials(
    file: UploadFile = File(...),
    cpse_name: str = Query(..., description="Name of the CPSE this file belongs to"),
    db: Session = Depends(get_db),
):
    """
    PHASE 1-2: Upload a CSV/Excel material master file for a given CPSE.
    Runs column mapping, normalization, attribute extraction, standardization,
    and (PHASE 10) continuous duplicate detection against the existing master.
    """
    content = await file.read()
    filename = file.filename or ""

    try:
        if filename.endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(content))
        elif filename.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(content))
        else:
            raise HTTPException(400, "Unsupported file type. Use .csv, .xlsx, or .xls")
    except Exception as e:
        raise HTTPException(400, f"Could not parse file: {e}")

    if df.empty:
        raise HTTPException(400, "Uploaded file has no rows")

    result = ingest_dataframe(db, df, cpse_name, source_document=filename)
    return result


@router.get("", response_model=list[MaterialOut])
def list_materials(
    cpse: str | None = None,
    category: str | None = None,
    national_material_code: str | None = None,
    limit: int = Query(100, le=1000),
    offset: int = 0,
    db: Session = Depends(get_db),
):
    q = db.query(MaterialRecord)
    if cpse:
        q = q.filter(MaterialRecord.source_cpse == cpse)
    if category:
        q = q.filter(MaterialRecord.category == category)
    if national_material_code:
        q = q.filter(MaterialRecord.national_material_code == national_material_code)
    return q.order_by(MaterialRecord.created_date.desc()).offset(offset).limit(limit).all()


@router.get("/{material_id}", response_model=MaterialOut)
def get_material(material_id: str, db: Session = Depends(get_db)):
    material = db.query(MaterialRecord).filter_by(id=material_id).first()
    if not material:
        raise HTTPException(404, "Material not found")
    return material


@router.get("/search/semantic", response_model=list[SearchResultOut])
def semantic_search(
    q: str = Query(..., min_length=2),
    limit: int = Query(20, le=100),
    db: Session = Depends(get_db),
):
    """
    PHASE 11: Semantic material search. A query like "CPVC ball valve 15 mm
    socket" retrieves related materials even when wording differs, using the
    same embedding backend as the matching engine (not a separate model).
    """
    materials = db.query(MaterialRecord).all()
    if not materials:
        return []

    texts = [q] + [m.standardized_description or m.material_description for m in materials]
    embeddings = compute_embeddings(texts)
    sims = cosine_sim_matrix(embeddings)[0, 1:]

    ranked = sorted(zip(materials, sims), key=lambda x: -x[1])[:limit]
    return [
        SearchResultOut(material=MaterialOut.model_validate(m), similarity=round(float(s) * 100, 1))
        for m, s in ranked
        if s > 0.1
    ]
