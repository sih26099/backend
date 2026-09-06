"""
PHASE 12: Tests.

Focused on the behaviors that matter most for a defensible hybrid system:
  - the critical-conflict rule actually blocks false duplicates
  - unit/token normalization produces equivalent representations
  - match type classification follows the configured thresholds
  - the full upload -> match -> approve -> NMC pipeline works end to end

Run: pytest tests/ -v
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.matching import (
    lexical_similarity, technical_similarity, classify_match,
    compute_hybrid_score, critical_conflicts,
)
from app.services.standardization import extract_full_attributes, build_standardized_description
from app.services.normalize import normalize_size_to_mm, normalize_text_tokens
from app.models.models import MatchType


# ---------------------------------------------------------------------------
# Unit tests: normalization
# ---------------------------------------------------------------------------

def test_size_normalization_fraction_inch():
    assert normalize_size_to_mm('1/2"') == pytest.approx(12.7, abs=0.01)


def test_size_normalization_decimal_inch():
    assert normalize_size_to_mm("0.5 inch") == pytest.approx(12.7, abs=0.01)


def test_size_normalization_mm():
    assert normalize_size_to_mm("15mm") == 15.0


def test_size_normalization_nb():
    assert normalize_size_to_mm("15 NB") == 15.0


def test_standard_token_normalization():
    assert normalize_text_tokens("ASTM-F439") == "ASTM F439"
    assert normalize_text_tokens("ASTM F439") == "ASTM F439"


# ---------------------------------------------------------------------------
# Unit tests: lexical matching
# ---------------------------------------------------------------------------

def test_lexical_similarity_word_order_invariant():
    a = "CPVC BALL VALVE 1/2 INCH SOCKET"
    b = "15 MM CPVC BALL VALVE WITH SOCKET CONNECTION"
    score = lexical_similarity(a, b)
    assert score > 0.5, "Lexical similarity should be reasonably high despite word-order/wording differences"


def test_lexical_similarity_identical():
    a = "CPVC Y-STRAINER 15MM SOCKET"
    assert lexical_similarity(a, a) == 1.0


def test_lexical_similarity_empty():
    assert lexical_similarity("", "something") == 0.0


# ---------------------------------------------------------------------------
# Unit tests: technical attribute extraction
# ---------------------------------------------------------------------------

def test_extract_attributes_valve():
    attrs = extract_full_attributes("VALVE, CPVC, 1/2IN, 150 PSI", "CPVC BALL VALVE ASTM F439 150 PSI")
    assert attrs["material_type"] == "CPVC"
    assert attrs["category"] == "Valve"
    assert attrs["diameter"] == pytest.approx(12.7, abs=0.01)
    assert attrs["pressure_rating"] == "150 PSI"
    assert attrs["standard"] == "ASTM F439"


def test_category_specific_template_valve():
    attrs = {"category": "Valve", "material_type": "CPVC", "diameter": 15.0, "connection": "Socket X Socket"}
    desc = build_standardized_description(attrs, fallback="raw text")
    assert "VALVE" in desc
    assert "15.0MM" in desc


# ---------------------------------------------------------------------------
# CRITICAL: the conflict-detection rule (the whole point of the hybrid design)
# ---------------------------------------------------------------------------

def test_critical_conflict_blocks_duplicate_classification():
    """
    The core safety requirement: two materials with near-identical text but
    a genuinely different critical spec (pressure rating) must NEVER be
    classified as EXACT_DUPLICATE or NEAR_DUPLICATE, no matter how high the
    lexical/semantic similarity is.
    """
    attrs_a = {"material_type": "CPVC", "diameter": 15.0, "pressure_rating": "150 PSI"}
    attrs_b = {"material_type": "CPVC", "diameter": 15.0, "pressure_rating": "300 PSI"}

    tech_score, comparisons = technical_similarity(attrs_a, attrs_b)
    conflicts = critical_conflicts(comparisons)
    assert "pressure_rating" in conflicts

    # even with maximum lexical+semantic scores, a critical conflict must cap the result
    final = compute_hybrid_score(lexical=1.0, semantic=1.0, technical=tech_score)
    match_type = classify_match(final, conflicts)
    assert match_type not in (MatchType.EXACT_DUPLICATE, MatchType.NEAR_DUPLICATE), (
        f"Expected conflict to block duplicate-tier classification, got {match_type}"
    )


def test_no_conflict_high_score_reaches_exact_duplicate():
    attrs_a = {"material_type": "CPVC", "diameter": 15.0, "standard": "ASTM F439"}
    attrs_b = {"material_type": "CPVC", "diameter": 15.0, "standard": "ASTM F439"}
    tech_score, comparisons = technical_similarity(attrs_a, attrs_b)
    conflicts = critical_conflicts(comparisons)
    assert conflicts == []

    final = compute_hybrid_score(lexical=1.0, semantic=1.0, technical=tech_score)
    assert classify_match(final, conflicts) == MatchType.EXACT_DUPLICATE


def test_missing_attributes_are_neutral_not_penalized():
    """Sparse CPSE data (common in practice) shouldn't be penalized as if it
    were a genuine mismatch."""
    tech_score, comparisons = technical_similarity({}, {})
    assert tech_score == 0.5
    assert comparisons == []


# ---------------------------------------------------------------------------
# Integration test: full pipeline via the API
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """
    Isolated DB per test: the engine/session are created once at module import
    time (app.core.database), so setting DATABASE_URL via env var after import
    has no effect. Instead, wipe all tables before each test so tests don't
    see each other's data, which is sufficient for this test suite's needs.
    """
    from app.core.database import engine
    from app.models.models import Base

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    with TestClient(app) as c:
        yield c


def test_full_pipeline_upload_match_approve_nmc(client):
    oil_csv = b"""Material Code,Description,Specification
M001,"Y-STRAINER, CPVC, 1/2IN SOC","CPVC Y STRAINER SOC EPDM 40 MESH ASTM F439"
"""
    bhel_csv = b"""Material Number,Item Description,Spec
B001,"CPVC Y-STRAINER 15MM SOCKET","ASTM-F439 40 MESH"
"""
    r = client.post("/api/materials/upload?cpse_name=OIL", files={"file": ("oil.csv", oil_csv, "text/csv")})
    assert r.status_code == 200
    assert r.json()["created"] == 1

    r = client.post("/api/materials/upload?cpse_name=BHEL", files={"file": ("bhel.csv", bhel_csv, "text/csv")})
    assert r.status_code == 200
    # continuous duplicate detection should have caught this on ingest
    assert r.json()["duplicate_candidates_found"] >= 1

    r = client.get("/api/matching/candidates")
    candidates = r.json()
    assert len(candidates) >= 1

    r = client.get("/api/approvals?status=PENDING")
    approvals = r.json()
    assert len(approvals) >= 1

    approval_id = approvals[0]["id"]
    r = client.post(f"/api/approvals/{approval_id}/decide", json={
        "decision": "APPROVE", "performed_by": "test_admin"
    })
    assert r.status_code == 200
    assert r.json()["status"] == "APPROVED"

    r = client.get("/api/nmc")
    nmcs = r.json()
    assert len(nmcs) == 1
    assert nmcs[0]["member_count"] == 2

    # legacy codes must be preserved, never destroyed
    r = client.get(f"/api/nmc/{nmcs[0]['code']}")
    members = r.json()["members"]
    codes = {m["existing_material_code"] for m in members}
    assert codes == {"M001", "B001"}

    r = client.get("/api/audit")
    actions = {log["action"] for log in r.json()}
    assert "AI_RECOMMENDATION_CREATED" in actions
    assert "APPROVED" in actions
    assert "NMC_ASSIGNED" in actions


def test_rejected_match_does_not_create_nmc(client):
    a_csv = b"""Material Code,Description,Specification
A001,"VALVE CPVC 1/2IN 150 PSI","ASTM F439"
"""
    b_csv = b"""Material Code,Description,Specification
B001,"VALVE CPVC 1/2IN 150 PSI DIFFERENT","ASTM F439"
"""
    client.post("/api/materials/upload?cpse_name=CPA", files={"file": ("a.csv", a_csv, "text/csv")})
    client.post("/api/materials/upload?cpse_name=CPB", files={"file": ("b.csv", b_csv, "text/csv")})

    r = client.get("/api/approvals?status=PENDING")
    approvals = r.json()
    if approvals:
        r = client.post(f"/api/approvals/{approvals[0]['id']}/decide", json={
            "decision": "REJECT", "performed_by": "test_admin", "reason": "Not actually equivalent"
        })
        assert r.json()["status"] == "REJECTED"

    r = client.get("/api/nmc")
    assert len(r.json()) == 0, "Rejected matches must not create a National Material Code"


def test_bad_cpse_sync_handled_gracefully(client):
    r = client.post("/api/sync/DOES-NOT-EXIST")
    assert r.status_code == 200  # error is captured in the log, not a 500
    assert r.json()["status"] == "FAILED"
    assert r.json()["error_message"] is not None
