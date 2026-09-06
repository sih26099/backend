"""
PHASE 9: Mock CPSE API / ERP Integration Layer.

Simulates what real CPSE SAP/ERP systems would expose, WITHOUT claiming any
real SAP access. Two mock CPSE APIs (representing e.g. "CPSE-A"/"CPSE-B") are
served in-process here, with pagination and a last_modified_date filter for
incremental sync -- structurally identical to what a real integration would
need, so swapping this for real authorized CPSE APIs later means only
replacing the fetch function body, not the surrounding sync/ingestion logic.
"""

import random
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# In-memory mock CPSE datasets (stands in for two CPSE ERP systems)
# ---------------------------------------------------------------------------

def _seed_mock_data(cpse_name: str, n: int = 25) -> list[dict]:
    random.seed(hash(cpse_name) % (2**32))
    categories = [
        ("Y-STRAINER", "CPVC", ["ASTM F439"], ["1/2 IN", "15MM", "3/4 IN"]),
        ("BALL VALVE", "CPVC", ["ASTM F439"], ["1/2 IN", "15MM", "1 IN"]),
        ("ELBOW 90 DEG", "CPVC", ["ASTM F439"], ["1/2 IN", "15MM"]),
        ("GASKET", "EPDM", [], ["15MM", "20MM"]),
        ("FLANGE", "CARBON STEEL", ["ASTM A105"], ["50MM", "100MM"]),
    ]
    records = []
    base_time = datetime.now(timezone.utc) - timedelta(days=90)
    for i in range(n):
        name, material, standards, sizes = random.choice(categories)
        size = random.choice(sizes)
        std = random.choice(standards) if standards else ""
        desc = f"{name}, {material}, {size}" + (f", {std}" if std else "")
        records.append({
            "material_code": f"{cpse_name}-{10000 + i}",
            "description": desc,
            "specification": f"{material} {name} {std}".strip(),
            "unit": "No.",
            "last_modified_date": (base_time + timedelta(days=random.randint(0, 90))).isoformat(),
        })
    return records


_MOCK_CPSE_DB = {
    "CPSE-A": _seed_mock_data("CPA", n=20),
    "CPSE-B": _seed_mock_data("CPB", n=20),
}


# ---------------------------------------------------------------------------
# Mock API surface (what a real CPSE API/ERP connector would call)
# ---------------------------------------------------------------------------

class CPSEAPIError(Exception):
    pass


def fetch_materials(cpse_name: str, page: int = 1, page_size: int = 10,
                     modified_since: datetime | None = None) -> dict:
    """
    Simulates a CPSE material master API call with pagination and incremental
    sync support via `modified_since`. Raises CPSEAPIError for unknown CPSEs
    to exercise error-handling paths, just as a real integration would need to
    handle timeouts/auth errors/malformed responses.
    """
    if cpse_name not in _MOCK_CPSE_DB:
        raise CPSEAPIError(f"Unknown CPSE '{cpse_name}' or API unreachable")

    records = _MOCK_CPSE_DB[cpse_name]

    if modified_since:
        # normalize to timezone-aware for a safe comparison regardless of how
        # the cursor was stored (SQLite can round-trip datetimes as naive)
        cutoff = modified_since if modified_since.tzinfo else modified_since.replace(tzinfo=timezone.utc)
        records = [
            r for r in records
            if datetime.fromisoformat(r["last_modified_date"]) > cutoff
        ]

    total = len(records)
    start = (page - 1) * page_size
    end = start + page_size
    page_records = records[start:end]

    return {
        "cpse": cpse_name,
        "page": page,
        "page_size": page_size,
        "total_records": total,
        "has_more": end < total,
        "records": page_records,
    }


def list_available_cpse_connectors() -> list[str]:
    return list(_MOCK_CPSE_DB.keys())
