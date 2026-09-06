"""
STEP 4: Technical Attribute Extraction.

Turns a raw description like:
    "ELBOW,90°, CPVC, ASTM F439, SCH 80, 1/2", SOC X SOC"
into structured fields:
    category=Elbow, angle=90, material_type=CPVC, standard=ASTM F439,
    schedule=SCH 80, size_mm=12.7, connection=Socket x Socket

Uses regex + keyword dictionaries. This is the "cheap, fast, deterministic"
layer described in the plan; an LLM call can be layered on top later for
attributes these rules miss, but is NOT required for the prototype to work.
"""

import re
from app.services.normalize import normalize_size_to_mm, normalize_text_tokens

CATEGORY_KEYWORDS = {
    "elbow": "Elbow",
    "strainer": "Strainer",
    "valve": "Valve",
    "nipple": "Nipple",
    "tee": "Tee",
    "coupling": "Coupling",
    "flange": "Flange",
    "gasket": "Gasket",
    "bolt": "Bolt",
    "pipe": "Pipe",
    "reducer": "Reducer",
    "union": "Union",
}

MATERIAL_TYPE_KEYWORDS = {
    "cpvc": "CPVC",
    "pvc": "PVC",
    "stainless steel": "Stainless Steel",
    "ss316": "SS316",
    "ss304": "SS304",
    "carbon steel": "Carbon Steel",
    "mild steel": "Mild Steel",
    "brass": "Brass",
    "bronze": "Bronze",
    "cast iron": "Cast Iron",
}

STANDARD_PATTERN = re.compile(
    r"\b(ASTM[\s-]?[A-Z]?\d+|API[\s-]?\d[A-Z]*|BS[\s-]?\d+|IS[\s-]?\d+|DIN[\s-]?\d+)\b",
    re.I,
)

SCHEDULE_PATTERN = re.compile(r"\bSCH[\s-]?(\d+)\b", re.I)

ANGLE_PATTERN = re.compile(r"(\d{1,3})\s*(?:°|deg(?:ree)?s?)\b", re.I)

CONNECTION_PATTERN = re.compile(
    r"\b(SOC(?:KET)?)\s*[xX×]\s*(SOC(?:KET)?|THD|NPT|FLG|FLANGE)\b", re.I
)

GRADE_PATTERN = re.compile(r"\b([A-Z]{1,3}[\s-]?\d{2,4})\b")

MESH_PATTERN = re.compile(r"(\d+)\s*MESH\b", re.I)

PRESSURE_PATTERN = re.compile(r"(\d+)\s*PSI\b", re.I)


def extract_attributes(description: str, specification: str = "") -> dict:
    """Extract structured technical attributes from free-text description/spec."""
    text = f"{description} {specification}"
    text_lower = text.lower()
    attrs = {}

    # Category
    for kw, label in CATEGORY_KEYWORDS.items():
        if kw in text_lower:
            attrs["category"] = label
            break

    # Material type
    for kw, label in MATERIAL_TYPE_KEYWORDS.items():
        if kw in text_lower:
            attrs["material_type"] = label
            break

    # Standard
    m = STANDARD_PATTERN.search(text)
    if m:
        attrs["standard"] = normalize_text_tokens(m.group(1).upper())

    # Schedule
    m = SCHEDULE_PATTERN.search(text)
    if m:
        attrs["schedule"] = f"SCH {m.group(1)}"

    # Angle
    m = ANGLE_PATTERN.search(text)
    if m:
        attrs["angle"] = f"{m.group(1)}°"

    # Connection type
    m = CONNECTION_PATTERN.search(text)
    if m:
        attrs["connection"] = f"{m.group(1).title()} x {m.group(2).title()}"

    # Size (mm)
    size_mm = normalize_size_to_mm(text)
    if size_mm is not None:
        attrs["size_mm"] = size_mm

    # Mesh (for strainers)
    m = MESH_PATTERN.search(text)
    if m:
        attrs["mesh"] = f"{m.group(1)} MESH"

    # Pressure rating
    m = PRESSURE_PATTERN.search(text)
    if m:
        attrs["pressure_rating"] = f"{m.group(1)} PSI"

    return attrs


def build_standardized_description(attrs: dict, fallback: str) -> str:
    """
    STEP 6: Standardize the description using extracted attributes.
    Produces a canonical string like:
        "CPVC Y-STRAINER, 12.7 MM, SOCKET CONNECTION"
    Falls back to the normalized raw text if attributes are too sparse.
    """
    parts = []
    if attrs.get("material_type"):
        parts.append(attrs["material_type"])
    if attrs.get("category"):
        parts.append(attrs["category"].upper())
    if attrs.get("size_mm") is not None:
        parts.append(f"{attrs['size_mm']} MM")
    if attrs.get("connection"):
        parts.append(f"{attrs['connection'].upper()} CONNECTION")
    if attrs.get("schedule"):
        parts.append(attrs["schedule"])
    if attrs.get("standard"):
        parts.append(attrs["standard"])
    if attrs.get("pressure_rating"):
        parts.append(attrs["pressure_rating"])

    if len(parts) >= 2:
        return ", ".join(parts)
    return normalize_text_tokens(fallback).upper()
