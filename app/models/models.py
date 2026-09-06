"""
PHASE 1: Common Material Schema (persisted).

This supersedes the in-memory `Material` dataclass in normalize.py by giving
it a real, complete, persisted schema covering every field the SIH 26099
spec asks for -- not just the matching-relevant subset the prototype used.

The prototype's `normalize.py` dataclass is still used internally by the
matching engine as a lightweight in-memory view (see services/matching.py
for the adapter that converts between the two). We are NOT deleting
normalize.py -- we're building the persistence layer around it.
"""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Float, DateTime, ForeignKey, Text, Enum as SAEnum,
    Integer, Boolean, JSON, UniqueConstraint
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def gen_uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MaterialStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    OBSOLETE = "OBSOLETE"
    UNDER_REVIEW = "UNDER_REVIEW"


class MatchType(str, enum.Enum):
    EXACT_DUPLICATE = "EXACT_DUPLICATE"
    NEAR_DUPLICATE = "NEAR_DUPLICATE"
    FUNCTIONALLY_EQUIVALENT = "FUNCTIONALLY_EQUIVALENT"
    POSSIBLE_MATCH = "POSSIBLE_MATCH"          # aka REVIEW_REQUIRED
    DISTINCT_MATERIAL = "DISTINCT_MATERIAL"


class ApprovalStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    NEEDS_REVIEW = "NEEDS_REVIEW"


# ---------------------------------------------------------------------------
# Core material master (input side) -- full SIH 26099 field list
# ---------------------------------------------------------------------------

class MaterialRecord(Base):
    __tablename__ = "materials"

    id = Column(String, primary_key=True, default=gen_uuid)

    # --- Source identity ---
    source_cpse = Column(String, nullable=False, index=True)          # "Existing CPSE name"
    existing_material_code = Column(String, nullable=False, index=True)
    source_erp = Column(String, nullable=True)
    source_document = Column(String, nullable=True)

    # --- Description / classification ---
    material_description = Column(Text, nullable=False)
    category = Column(String, nullable=True, index=True)
    subcategory = Column(String, nullable=True)
    specification = Column(Text, nullable=True)
    technical_parameters = Column(JSON, default=dict)  # free-form extracted attrs

    # --- Physical / technical attributes ---
    diameter = Column(Float, nullable=True)     # normalized to mm
    length = Column(Float, nullable=True)       # normalized to mm
    width = Column(Float, nullable=True)        # normalized to mm
    height = Column(Float, nullable=True)       # normalized to mm
    weight = Column(Float, nullable=True)       # normalized to kg
    grade = Column(String, nullable=True)
    material_type = Column(String, nullable=True)
    standard = Column(String, nullable=True)
    thread_type = Column(String, nullable=True)
    connection_type = Column(String, nullable=True)
    pressure_rating = Column(String, nullable=True)
    unit_of_measure = Column(String, nullable=True)

    # --- Commercial ---
    manufacturer = Column(String, nullable=True)
    supplier = Column(String, nullable=True)
    historical_price = Column(Float, nullable=True)
    currency = Column(String, nullable=True, default="INR")
    procurement_quantity = Column(Float, nullable=True)
    purchase_order_number = Column(String, nullable=True)
    procurement_date = Column(DateTime, nullable=True)

    # --- Organizational ---
    industry = Column(String, nullable=True)
    department = Column(String, nullable=True)
    unspsc_code = Column(String, nullable=True)
    cpse_classification_code = Column(String, nullable=True)

    # --- Lifecycle / audit ---
    created_date = Column(DateTime, default=utcnow)
    last_modified_date = Column(DateTime, default=utcnow, onupdate=utcnow)
    material_status = Column(SAEnum(MaterialStatus), default=MaterialStatus.ACTIVE)

    # --- AI/standardization output (Phase 1-2 results live on the record itself) ---
    standardized_description = Column(Text, nullable=True)
    standardized_category = Column(String, nullable=True)
    standardized_subcategory = Column(String, nullable=True)
    standardized_specification = Column(Text, nullable=True)

    # --- National code assignment (set after cluster approval) ---
    national_material_code = Column(String, nullable=True, index=True)
    cluster_id = Column(String, nullable=True, index=True)

    # --- Sync bookkeeping (Phase 9-10) ---
    last_synced_at = Column(DateTime, nullable=True)
    embedding_json = Column(JSON, nullable=True)  # cached vector, avoids recompute

    __table_args__ = (
        UniqueConstraint("source_cpse", "existing_material_code", name="uq_cpse_code"),
    )


# ---------------------------------------------------------------------------
# Match candidates (AI output) -- Phase 3-6
# ---------------------------------------------------------------------------

class MatchCandidate(Base):
    __tablename__ = "match_candidates"

    id = Column(String, primary_key=True, default=gen_uuid)
    material_a_id = Column(String, ForeignKey("materials.id"), nullable=False)
    material_b_id = Column(String, ForeignKey("materials.id"), nullable=False)

    # Hybrid scoring breakdown (Phase 5) -- transparent, always stored
    lexical_similarity = Column(Float, nullable=False)
    semantic_similarity = Column(Float, nullable=False)
    technical_similarity = Column(Float, nullable=False)
    final_confidence = Column(Float, nullable=False)

    match_type = Column(SAEnum(MatchType), nullable=False)
    critical_conflicts = Column(JSON, default=list)   # list of attr names that differ
    evidence = Column(JSON, default=dict)              # full comparison breakdown for UI

    created_date = Column(DateTime, default=utcnow)

    material_a = relationship("MaterialRecord", foreign_keys=[material_a_id])
    material_b = relationship("MaterialRecord", foreign_keys=[material_b_id])


# ---------------------------------------------------------------------------
# Human approval workflow -- Phase 7
# ---------------------------------------------------------------------------

class ApprovalRecord(Base):
    __tablename__ = "approvals"

    id = Column(String, primary_key=True, default=gen_uuid)
    match_candidate_id = Column(String, ForeignKey("match_candidates.id"), nullable=False)

    status = Column(SAEnum(ApprovalStatus), default=ApprovalStatus.PENDING)
    approved_by = Column(String, nullable=True)
    approval_date = Column(DateTime, nullable=True)
    reason = Column(Text, nullable=True)

    created_date = Column(DateTime, default=utcnow)

    match_candidate = relationship("MatchCandidate")


# ---------------------------------------------------------------------------
# National Material Code + legacy mapping -- Phase 8
# ---------------------------------------------------------------------------

class NationalMaterialCode(Base):
    __tablename__ = "national_material_codes"

    id = Column(String, primary_key=True, default=gen_uuid)
    code = Column(String, nullable=False, unique=True, index=True)  # e.g. NMC-000001
    canonical_description = Column(Text, nullable=True)
    canonical_category = Column(String, nullable=True)
    created_date = Column(DateTime, default=utcnow)
    status = Column(String, default="ACTIVE")


class LegacyCodeMapping(Base):
    """
    Never-deleted mapping: old CPSE code -> National Material Code.
    Historical mappings are kept even if superseded (is_active=False) so the
    full history stays traceable, per the "never destroy original codes" rule.
    """
    __tablename__ = "legacy_code_mappings"

    id = Column(String, primary_key=True, default=gen_uuid)
    source_cpse = Column(String, nullable=False)
    existing_material_code = Column(String, nullable=False)
    material_id = Column(String, ForeignKey("materials.id"), nullable=False)
    national_material_code = Column(String, ForeignKey("national_material_codes.code"), nullable=False)
    is_active = Column(Boolean, default=True)
    created_date = Column(DateTime, default=utcnow)
    superseded_date = Column(DateTime, nullable=True)


# ---------------------------------------------------------------------------
# Audit trail -- cross-cutting, referenced by every mutating action
# ---------------------------------------------------------------------------

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String, primary_key=True, default=gen_uuid)
    material_id = Column(String, nullable=True, index=True)
    match_candidate_id = Column(String, nullable=True, index=True)
    action = Column(String, nullable=False)         # e.g. AI_RECOMMENDATION_CREATED, APPROVED, REJECTED, SYNCED
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    performed_by = Column(String, nullable=False)    # "AI_MATCHER" or a username
    ai_confidence = Column(Float, nullable=True)
    reason = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=utcnow, index=True)


# ---------------------------------------------------------------------------
# CPSE sync bookkeeping -- Phase 9-10
# ---------------------------------------------------------------------------

class SyncLog(Base):
    __tablename__ = "sync_logs"

    id = Column(String, primary_key=True, default=gen_uuid)
    cpse_name = Column(String, nullable=False)
    sync_started_at = Column(DateTime, default=utcnow)
    sync_completed_at = Column(DateTime, nullable=True)
    records_fetched = Column(Integer, default=0)
    records_created = Column(Integer, default=0)
    records_updated = Column(Integer, default=0)
    duplicate_candidates_found = Column(Integer, default=0)
    status = Column(String, default="RUNNING")   # RUNNING, SUCCESS, FAILED
    error_message = Column(Text, nullable=True)
    last_modified_cursor = Column(DateTime, nullable=True)  # for incremental sync
