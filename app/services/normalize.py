"""
STEP 2-5: Common schema + normalization utilities.

Different CPSEs use different column names, units, and abbreviations for the
same physical thing. This module maps everything into one common schema and
normalizes units/abbreviations so downstream matching compares apples to apples.
"""

import re
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# STEP 3: Common schema
# ---------------------------------------------------------------------------

@dataclass
class Material:
    """One row of the common `materials` schema (subset relevant to matching)."""
    id: str
    cpse_name: str
    existing_material_code: str
    material_description: str

    # populated by normalization / extraction steps
    standardized_description: str = ""
    category: Optional[str] = None
    material_type: Optional[str] = None
    size_mm: Optional[float] = None
    standard: Optional[str] = None
    schedule: Optional[str] = None
    connection: Optional[str] = None
    pressure_rating: Optional[str] = None
    grade: Optional[str] = None
    technical_parameters: dict = field(default_factory=dict)

    # populated by matching/clustering steps
    cluster_id: Optional[str] = None
    national_material_code: Optional[str] = None


# ---------------------------------------------------------------------------
# STEP 3: Column-name mapping (different CPSEs, same meaning)
# ---------------------------------------------------------------------------

COLUMN_ALIASES = {
    "existing_material_code": [
        "material code", "material_code", "material number", "material_number",
        "item code", "item_code", "code",
    ],
    "material_description": [
        "description", "item description", "item_description",
        "material description", "material_description", "material name",
        "material_name",
    ],
    "specification": [
        "specification", "spec", "material specification", "tech spec",
    ],
    "size": ["size", "size1", "dimension"],
    "standard": ["standard", "std", "material standard"],
    "unit": ["unit", "uom", "unit of measure", "unit_of_measure"],
    "manufacturer": ["manufacturer", "supplier", "make"],
    "price": ["price", "unit price", "rate", "historical_price"],
    "quantity": ["quantity", "qty", "procurement_quantity"],
}


def map_columns(raw_columns: list[str]) -> dict[str, str]:
    """
    Given a CPSE file's raw column names, return {raw_column: common_field}.
    Unmatched columns are left out (they can still be stored in a raw JSON blob).
    """
    lookup = {}
    for common_field, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            lookup[alias.lower().strip()] = common_field

    mapping = {}
    for col in raw_columns:
        key = col.lower().strip()
        if key in lookup:
            mapping[col] = lookup[key]
    return mapping


# ---------------------------------------------------------------------------
# STEP 5: Unit / size normalization
# ---------------------------------------------------------------------------

# inches (as fraction or decimal) -> mm
_INCH_TO_MM = 25.4

_SIZE_PATTERNS = [
    # e.g. 1/2", 1/2 in, 1/2IN
    (re.compile(r"(\d+)\s*/\s*(\d+)\s*(?:\"|in\b|inch(?:es)?\b)", re.I),
     lambda m: (int(m.group(1)) / int(m.group(2))) * _INCH_TO_MM),
    # e.g. 0.5 inch, 0.5in, 0.5"
    (re.compile(r"(\d+(?:\.\d+)?)\s*(?:\"|in\b|inch(?:es)?\b)", re.I),
     lambda m: float(m.group(1)) * _INCH_TO_MM),
    # e.g. 15mm, 15 mm
    (re.compile(r"(\d+(?:\.\d+)?)\s*mm\b", re.I),
     lambda m: float(m.group(1))),
    # e.g. 15 NB (nominal bore, treat numerically as mm - common industry convention)
    (re.compile(r"(\d+(?:\.\d+)?)\s*NB\b", re.I),
     lambda m: float(m.group(1))),
]


def normalize_size_to_mm(text: str) -> Optional[float]:
    """Extract a size expressed in wildly different formats and return mm."""
    if not text:
        return None
    for pattern, convert in _SIZE_PATTERNS:
        m = pattern.search(text)
        if m:
            return round(convert(m), 2)
    return None


# Dictionary-based normalization for standards, materials, units
_TOKEN_NORMALIZATION = {
    # standards
    "astm-f439": "ASTM F439",
    "astmf439": "ASTM F439",
    "astm f439": "ASTM F439",
    "api5ct": "API 5CT",
    "api-5ct": "API 5CT",
    "api 5ct": "API 5CT",
    "p-110": "P110",
    "p 110": "P110",
    "sch80": "SCH 80",
    "sch-80": "SCH 80",
    "sch 80": "SCH 80",
    # units
    "kg/mtr": "kg/m",
    "mtr": "m",
    "no": "No.",
    "nos": "No.",
    # material types
    "cpvc": "CPVC",
    "pvc": "PVC",
    "ss": "Stainless Steel",
    "ms": "Mild Steel",
    "cs": "Carbon Steel",
}


def normalize_token(token: str) -> str:
    """Normalize a single technical token (standard code, unit, material abbreviation)."""
    key = token.lower().strip().replace(" ", " ")
    key_compact = key.replace(" ", "")
    if key in _TOKEN_NORMALIZATION:
        return _TOKEN_NORMALIZATION[key]
    if key_compact in _TOKEN_NORMALIZATION:
        return _TOKEN_NORMALIZATION[key_compact]
    return token.strip()


def normalize_text_tokens(text: str) -> str:
    """Run normalize_token over every whitespace/comma separated chunk found via regex hits."""
    if not text:
        return text
    result = text
    # normalize known multi-word/hyphenated tokens first (longest match wins)
    for raw, normalized in sorted(_TOKEN_NORMALIZATION.items(), key=lambda x: -len(x[0])):
        pattern = re.compile(re.escape(raw).replace(r"\ ", r"[\s-]?"), re.I)
        result = pattern.sub(normalized, result)
    return result
