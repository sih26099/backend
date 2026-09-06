"""
PHASE 3-6: Hybrid AI Matching Engine.

Extends the prototype's matching_engine.py with the piece that was
genuinely missing: LEXICAL matching (fuzzy string/token similarity), and
combines it with semantic (embeddings) + technical attribute similarity
into a single transparent, configurable hybrid score.

    final_confidence = W_lex * lexical + W_sem * semantic + W_tech * technical

Weights come from app.core.config.settings (env-configurable), not
hardcoded constants scattered through the code.

Match types (per spec, not the prototype's 4):
    EXACT_DUPLICATE, NEAR_DUPLICATE, FUNCTIONALLY_EQUIVALENT,
    POSSIBLE_MATCH (= REVIEW_REQUIRED), DISTINCT_MATERIAL

CRITICAL: a differing critical attribute (material type, size, standard,
pressure rating, thread type) can never let a pair reach EXACT_DUPLICATE
or NEAR_DUPLICATE, no matter how high lexical/semantic scores are. This is
the "never call it a duplicate just because the LLM/embedding says so" rule.
"""

from dataclasses import dataclass, field
from itertools import combinations
from typing import Optional

import numpy as np
from rapidfuzz import fuzz

from app.core.config import settings
from app.models.models import MatchType

_EMBED_MODEL = None
_EMBEDDING_BACKEND = None


def get_embedding_model():
    """Same fallback strategy as the prototype: sentence-transformers if available
    (needs one-time internet access), else offline TF-IDF so the system always runs."""
    global _EMBED_MODEL, _EMBEDDING_BACKEND
    if _EMBED_MODEL is not None:
        return _EMBED_MODEL
    try:
        from sentence_transformers import SentenceTransformer
        _EMBED_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
        _EMBEDDING_BACKEND = "sentence-transformers"
    except Exception:
        from sklearn.feature_extraction.text import TfidfVectorizer
        _EMBED_MODEL = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4))
        _EMBEDDING_BACKEND = "tfidf"
    return _EMBED_MODEL


def compute_embeddings(texts: list[str]) -> np.ndarray:
    model = get_embedding_model()
    if _EMBEDDING_BACKEND == "sentence-transformers":
        return np.array(model.encode(texts, normalize_embeddings=True))
    matrix = model.fit_transform(texts).toarray()
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def cosine_sim_matrix(embeddings: np.ndarray) -> np.ndarray:
    return embeddings @ embeddings.T


# ---------------------------------------------------------------------------
# PHASE 3a: Lexical matching (the layer the prototype was missing)
# ---------------------------------------------------------------------------

def lexical_similarity(text_a: str, text_b: str) -> float:
    """
    Fuzzy string + token similarity, catching spelling differences,
    abbreviations, and word-order differences that pure embeddings can miss
    and that exact string matching would reject outright.

    Combines:
      - token_sort_ratio: robust to word-order differences
                          ("CPVC BALL VALVE 15MM" vs "15MM CPVC BALL VALVE")
      - token_set_ratio: robust to extra/missing words
      - partial_ratio: catches near-identical substrings

    Returns 0-1.
    """
    if not text_a or not text_b:
        return 0.0
    a, b = text_a.upper().strip(), text_b.upper().strip()

    token_sort = fuzz.token_sort_ratio(a, b) / 100.0
    token_set = fuzz.token_set_ratio(a, b) / 100.0
    partial = fuzz.partial_ratio(a, b) / 100.0

    # weighted blend: token_set is most forgiving of extra descriptive words,
    # which is common across CPSEs (one adds "WITH", "TYPE", etc.)
    return round(0.4 * token_sort + 0.4 * token_set + 0.2 * partial, 4)


# ---------------------------------------------------------------------------
# PHASE 4: Technical rule engine
# ---------------------------------------------------------------------------

# Attributes where ANY mismatch blocks duplicate-tier classification --
# these change fit/function/safety even when text reads nearly identical.
CRITICAL_ATTRS = [
    "material_type", "diameter", "standard", "pressure_rating", "thread_type",
]

# Attributes that matter but only apply a soft penalty on mismatch.
SOFT_ATTRS = ["category", "subcategory", "grade", "connection_type", "unit_of_measure"]

NUMERIC_ATTRS = {"diameter", "length", "width", "height", "weight"}


@dataclass
class AttributeComparison:
    attribute: str
    value_a: Optional[str]
    value_b: Optional[str]
    match: bool
    critical: bool


def technical_similarity(attrs_a: dict, attrs_b: dict) -> tuple[float, list[AttributeComparison]]:
    """
    Compares structured technical attributes between two materials.
    Returns (score 0-1, full comparison list for evidence display).
    Missing attributes on either side are skipped (neutral) -- real CPSE
    data is frequently incomplete, and penalizing missing data would bias
    against sparsely-populated records rather than genuinely different ones.
    """
    comparisons = []
    scores = []

    for attr in CRITICAL_ATTRS + SOFT_ATTRS:
        va, vb = attrs_a.get(attr), attrs_b.get(attr)
        if va is None or vb is None:
            continue

        if attr in NUMERIC_ATTRS:
            try:
                match = abs(float(va) - float(vb)) <= settings.SIZE_TOLERANCE_MM
            except (TypeError, ValueError):
                match = str(va).strip().lower() == str(vb).strip().lower()
        else:
            match = str(va).strip().lower() == str(vb).strip().lower()

        is_critical = attr in CRITICAL_ATTRS
        comparisons.append(AttributeComparison(attr, str(va), str(vb), match, is_critical))
        scores.append(1.0 if match else (0.0 if is_critical else 0.3))

    if not scores:
        return 0.5, comparisons  # no comparable attributes -> neutral, lean on text signals
    return round(sum(scores) / len(scores), 4), comparisons


def critical_conflicts(comparisons: list[AttributeComparison]) -> list[str]:
    return [c.attribute for c in comparisons if c.critical and not c.match]


# ---------------------------------------------------------------------------
# PHASE 5: Hybrid scoring (configurable weights)
# ---------------------------------------------------------------------------

@dataclass
class MatchEvidence:
    material_a_id: str
    material_b_id: str
    lexical_similarity: float
    semantic_similarity: float
    technical_similarity: float
    final_confidence: float
    match_type: MatchType
    critical_conflicts: list[str]
    attribute_comparisons: list[AttributeComparison] = field(default_factory=list)


def compute_hybrid_score(lexical: float, semantic: float, technical: float) -> float:
    """The configurable weighted blend. Weights live in settings, never hardcoded here."""
    return round(
        settings.WEIGHT_LEXICAL * lexical
        + settings.WEIGHT_SEMANTIC * semantic
        + settings.WEIGHT_TECHNICAL * technical,
        4,
    )


# ---------------------------------------------------------------------------
# PHASE 6: Match type classification (5 types, not 4)
# ---------------------------------------------------------------------------

def classify_match(final_confidence: float, conflicts: list[str]) -> MatchType:
    """
    Hard rule: any critical conflict blocks EXACT_DUPLICATE / NEAR_DUPLICATE,
    regardless of how high lexical+semantic scores are (the 150 PSI vs 300 PSI
    valve case -- ~95% text similarity, but NOT the same part).
    """
    if conflicts:
        if final_confidence >= settings.THRESHOLD_FUNCTIONALLY_EQUIVALENT:
            return MatchType.FUNCTIONALLY_EQUIVALENT
        if final_confidence >= settings.THRESHOLD_POSSIBLE_MATCH:
            return MatchType.POSSIBLE_MATCH
        return MatchType.DISTINCT_MATERIAL

    if final_confidence >= settings.THRESHOLD_EXACT_DUPLICATE:
        return MatchType.EXACT_DUPLICATE
    if final_confidence >= settings.THRESHOLD_NEAR_DUPLICATE:
        return MatchType.NEAR_DUPLICATE
    if final_confidence >= settings.THRESHOLD_FUNCTIONALLY_EQUIVALENT:
        return MatchType.FUNCTIONALLY_EQUIVALENT
    if final_confidence >= settings.THRESHOLD_POSSIBLE_MATCH:
        return MatchType.POSSIBLE_MATCH
    return MatchType.DISTINCT_MATERIAL


# ---------------------------------------------------------------------------
# Orchestration: compare a batch of materials pairwise (bulk matching run)
# ---------------------------------------------------------------------------

@dataclass
class MaterialView:
    """Lightweight view of a MaterialRecord row, decoupled from the ORM so
    this module has no SQLAlchemy dependency (keeps it independently testable,
    matching the prototype's original design intent)."""
    id: str
    source_cpse: str
    text_for_matching: str  # standardized_description or material_description
    attributes: dict


def find_matches(materials: list[MaterialView]) -> list[MatchEvidence]:
    if len(materials) < 2:
        return []

    texts = [m.text_for_matching for m in materials]
    embeddings = compute_embeddings(texts)
    sem_matrix = cosine_sim_matrix(embeddings)

    results = []
    for i, j in combinations(range(len(materials)), 2):
        a, b = materials[i], materials[j]
        if settings.CROSS_CPSE_ONLY and a.source_cpse == b.source_cpse:
            continue

        lex = lexical_similarity(a.text_for_matching, b.text_for_matching)
        sem = float(sem_matrix[i, j])
        tech, comparisons = technical_similarity(a.attributes, b.attributes)
        conflicts = critical_conflicts(comparisons)

        final = compute_hybrid_score(lex, sem, tech)
        match_type = classify_match(final, conflicts)

        if final >= settings.MIN_CONFIDENCE_TO_STORE or match_type != MatchType.DISTINCT_MATERIAL:
            results.append(MatchEvidence(
                material_a_id=a.id,
                material_b_id=b.id,
                lexical_similarity=round(lex * 100, 1),
                semantic_similarity=round(sem * 100, 1),
                technical_similarity=round(tech * 100, 1),
                final_confidence=round(final * 100, 1),
                match_type=match_type,
                critical_conflicts=conflicts,
                attribute_comparisons=comparisons,
            ))
    return results


def compare_pair(material_a: MaterialView, material_b: MaterialView) -> MatchEvidence:
    """Single-pair comparison, used by the material comparison screen (Phase 11)
    and by continuous duplicate detection (Phase 10) -- avoids recomputing
    embeddings for the whole dataset just to compare two records."""
    embeddings = compute_embeddings([material_a.text_for_matching, material_b.text_for_matching])
    sem = float(cosine_sim_matrix(embeddings)[0, 1])
    lex = lexical_similarity(material_a.text_for_matching, material_b.text_for_matching)
    tech, comparisons = technical_similarity(material_a.attributes, material_b.attributes)
    conflicts = critical_conflicts(comparisons)
    final = compute_hybrid_score(lex, sem, tech)
    match_type = classify_match(final, conflicts)

    return MatchEvidence(
        material_a_id=material_a.id,
        material_b_id=material_b.id,
        lexical_similarity=round(lex * 100, 1),
        semantic_similarity=round(sem * 100, 1),
        technical_similarity=round(tech * 100, 1),
        final_confidence=round(final * 100, 1),
        match_type=match_type,
        critical_conflicts=conflicts,
        attribute_comparisons=comparisons,
    )
