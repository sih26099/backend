from datetime import datetime
from typing import Optional, Any

from pydantic import BaseModel, ConfigDict


class MaterialOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_cpse: str
    existing_material_code: str
    source_erp: Optional[str] = None
    source_document: Optional[str] = None

    material_description: str
    category: Optional[str] = None
    subcategory: Optional[str] = None
    specification: Optional[str] = None
    technical_parameters: Optional[dict] = None

    diameter: Optional[float] = None
    length: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    weight: Optional[float] = None
    grade: Optional[str] = None
    material_type: Optional[str] = None
    standard: Optional[str] = None
    thread_type: Optional[str] = None
    connection_type: Optional[str] = None
    pressure_rating: Optional[str] = None
    unit_of_measure: Optional[str] = None

    manufacturer: Optional[str] = None
    supplier: Optional[str] = None
    historical_price: Optional[float] = None
    currency: Optional[str] = None
    procurement_quantity: Optional[float] = None
    purchase_order_number: Optional[str] = None
    procurement_date: Optional[datetime] = None

    industry: Optional[str] = None
    department: Optional[str] = None
    unspsc_code: Optional[str] = None
    cpse_classification_code: Optional[str] = None

    created_date: datetime
    last_modified_date: datetime
    material_status: str

    standardized_description: Optional[str] = None
    standardized_category: Optional[str] = None
    standardized_subcategory: Optional[str] = None
    standardized_specification: Optional[str] = None

    national_material_code: Optional[str] = None
    cluster_id: Optional[str] = None


class AttributeComparisonOut(BaseModel):
    attribute: str
    value_a: Optional[str] = None
    value_b: Optional[str] = None
    match: bool
    critical: bool


class MatchCandidateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    material_a_id: str
    material_b_id: str
    lexical_similarity: float
    semantic_similarity: float
    technical_similarity: float
    final_confidence: float
    match_type: str
    critical_conflicts: list[str]
    evidence: Optional[dict] = None
    created_date: datetime


class ApprovalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    match_candidate_id: str
    status: str
    approved_by: Optional[str] = None
    approval_date: Optional[datetime] = None
    reason: Optional[str] = None
    created_date: datetime


class ApprovalDecisionIn(BaseModel):
    decision: str  # "APPROVE" | "REJECT" | "NEEDS_REVIEW"
    performed_by: str
    reason: Optional[str] = None


class ComparePairIn(BaseModel):
    material_a_id: str
    material_b_id: str


class CompareResultOut(BaseModel):
    material_a: MaterialOut
    material_b: MaterialOut
    lexical_similarity: float
    semantic_similarity: float
    technical_similarity: float
    final_confidence: float
    match_type: str
    critical_conflicts: list[str]
    attribute_comparisons: list[AttributeComparisonOut]


class DashboardStatsOut(BaseModel):
    total_materials: int
    materials_by_cpse: dict[str, int]
    exact_duplicates: int
    near_duplicates: int
    functionally_equivalent: int
    possible_matches: int
    pending_approvals: int
    approved_mappings: int
    rejected_mappings: int
    confidence_distribution: dict[str, int]
    material_categories: dict[str, int]
    recently_synced: list[dict]
    total_national_codes: int
    duplicate_reduction_pct: float


class SearchResultOut(BaseModel):
    material: MaterialOut
    similarity: float


class SyncLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    cpse_name: str
    sync_started_at: datetime
    sync_completed_at: Optional[datetime] = None
    records_fetched: int
    records_created: int
    records_updated: int
    duplicate_candidates_found: int
    status: str
    error_message: Optional[str] = None


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    material_id: Optional[str] = None
    match_candidate_id: Optional[str] = None
    action: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    performed_by: str
    ai_confidence: Optional[float] = None
    reason: Optional[str] = None
    timestamp: datetime


class NMCMappingOut(BaseModel):
    national_material_code: str
    canonical_description: Optional[str] = None
    members: list[dict]  # [{source_cpse, existing_material_code, material_id, is_active}]
