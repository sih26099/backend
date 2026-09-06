"""
PHASE 1-2 (extended): Full technical attribute extraction + category-specific
standardization templates.

Builds on app.services.extract_attributes (copied from the prototype) by:
  1. Adding extraction for fields the prototype didn't cover: length, width,
     height, weight, thread_type (the prototype only had size/diameter).
  2. Replacing the single hardcoded standardized-description format with
     CONFIGURABLE, category-specific templates (spec requirement: "Do NOT
     force one template onto every material category").
"""

import re
from typing import Optional

from app.services.extract_attributes import (
    extract_attributes as _base_extract_attributes,
    CATEGORY_KEYWORDS,
    MATERIAL_TYPE_KEYWORDS,
)
from app.services.normalize import normalize_text_tokens

# ---------------------------------------------------------------------------
# Additional attribute patterns beyond the prototype's coverage
# ---------------------------------------------------------------------------

_LENGTH_PATTERN = re.compile(r"(?:L|LENGTH)[\s:=]*(\d+(?:\.\d+)?)\s*(mm|cm|m|in|inch)\b", re.I)
_WIDTH_PATTERN = re.compile(r"(?:W|WIDTH)[\s:=]*(\d+(?:\.\d+)?)\s*(mm|cm|m|in|inch)\b", re.I)
_HEIGHT_PATTERN = re.compile(r"(?:H|HEIGHT)[\s:=]*(\d+(?:\.\d+)?)\s*(mm|cm|m|in|inch)\b", re.I)
_WEIGHT_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(kg|g|gram|lb)\b", re.I)
_THREAD_PATTERN = re.compile(r"\b(NPT|BSP|BSPT|UNC|UNF|METRIC\s*THREAD)\b", re.I)

_UNIT_TO_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4, "inch": 25.4}
_WEIGHT_TO_KG = {"kg": 1.0, "g": 0.001, "gram": 0.001, "lb": 0.4536}


def _dim_to_mm(value: str, unit: str) -> float:
    return round(float(value) * _UNIT_TO_MM.get(unit.lower(), 1.0), 2)


def _weight_to_kg(value: str, unit: str) -> float:
    return round(float(value) * _WEIGHT_TO_KG.get(unit.lower(), 1.0), 4)


def extract_full_attributes(description: str, specification: str = "") -> dict:
    """
    Superset of the prototype's extract_attributes(): adds length/width/height/
    weight/thread_type, and renames size_mm -> diameter to match the full schema
    (diameter is the term used across the SIH field list; size_mm was the
    prototype's shorthand for pipe-fitting nominal size specifically).
    """
    text = f"{description} {specification}"
    base = _base_extract_attributes(description, specification)

    attrs = dict(base)
    if "size_mm" in attrs:
        attrs["diameter"] = attrs.pop("size_mm")

    m = _LENGTH_PATTERN.search(text)
    if m:
        attrs["length"] = _dim_to_mm(m.group(1), m.group(2))

    m = _WIDTH_PATTERN.search(text)
    if m:
        attrs["width"] = _dim_to_mm(m.group(1), m.group(2))

    m = _HEIGHT_PATTERN.search(text)
    if m:
        attrs["height"] = _dim_to_mm(m.group(1), m.group(2))

    m = _WEIGHT_PATTERN.search(text)
    if m:
        attrs["weight"] = _weight_to_kg(m.group(1), m.group(2))

    m = _THREAD_PATTERN.search(text)
    if m:
        attrs["thread_type"] = m.group(1).upper()

    return attrs


# ---------------------------------------------------------------------------
# Category-specific standardization templates
# ---------------------------------------------------------------------------
# Each template is a list of attribute keys (in order) to join with "-".
# Falls back to DEFAULT_TEMPLATE for categories without a specific template.
# These are configurable/extendable -- add a new category key to support it,
# no code changes required elsewhere.

STANDARDIZATION_TEMPLATES: dict[str, list[str]] = {
    "Valve":    ["category", "subcategory", "diameter_mm", "material_type", "connection"],
    "Strainer": ["material_type", "category", "diameter_mm", "mesh"],
    "Elbow":    ["material_type", "category", "diameter_mm", "connection", "schedule"],
    "Pipe":     ["material_type", "category", "diameter_mm", "schedule", "standard"],
    "Flange":   ["category", "diameter_mm", "standard", "material_type"],
    "Gasket":   ["category", "diameter_mm", "material_type"],
}

DEFAULT_TEMPLATE = ["material_type", "category", "diameter_mm", "connection", "standard", "pressure_rating"]


def build_standardized_description(attrs: dict, fallback: str) -> str:
    """
    Applies the category-specific template if one exists for attrs['category'],
    otherwise falls back to DEFAULT_TEMPLATE. Produces e.g.:
        VALVE-BALL-15MM-CPVC-SOCKET
        CPVC-STRAINER-12.7MM-40MESH
    Falls back to normalized raw text if too few fields are populated (avoids
    "CPVC--15MM--" style templates with empty slots for sparse data).
    """
    category = attrs.get("category", "")
    template = STANDARDIZATION_TEMPLATES.get(category, DEFAULT_TEMPLATE)

    parts = []
    for key in template:
        if key == "diameter_mm":
            val = attrs.get("diameter")
            if val is not None:
                parts.append(f"{val}MM")
            continue
        val = attrs.get(key)
        if val:
            parts.append(str(val).upper().replace(" ", ""))

    if len(parts) >= 2:
        return "-".join(parts)
    return normalize_text_tokens(fallback).upper()


def build_standardized_category(attrs: dict) -> Optional[str]:
    return attrs.get("category")


def build_standardized_specification(attrs: dict) -> str:
    """Human-readable (comma-separated) version, distinct from the compact
    hyphenated standardized_description -- used for the comparison screen
    where readability matters more than compactness."""
    fields = ["material_type", "category", "diameter", "connection", "schedule",
              "standard", "pressure_rating", "thread_type", "grade"]
    parts = []
    for f in fields:
        val = attrs.get(f)
        if val is not None:
            label = "mm" if f == "diameter" else ""
            parts.append(f"{val}{label}" if label else str(val))
    return ", ".join(parts) if parts else ""
