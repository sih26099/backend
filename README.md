# SIH 26099 Backend — AI-Driven Standardization and Harmonization of Material Codes Across CPSEs

FastAPI backend implementing Phases 1–12. Extends (does not replace) the
original prototype logic in `normalize.py` / `extract_attributes.py` — those
files are copied into `app/services/` largely unchanged; everything else is
new persistence, API, and the missing lexical-matching layer.

## IMPORTANT: what this is, honestly

This backend was built from scratch based on your written specification,
**not** by inspecting a pre-existing running application, because no backend
code was ever uploaded to this conversation — only the standalone matching
prototype (`normalize.py`, `matching_engine.py`, etc.) I had built earlier.
"Modify the existing codebase" therefore meant: extend that prototype's
logic into a real persisted, API-exposed system, which is what this is.

Your frontend repo (`sih26099/frontend`) is a separate React/Vite app whose
README says it expects a **Go backend** and currently runs on mock data
(`src/data/mockClusters.js`). This backend is Python/FastAPI, per your
explicit instruction to proceed that way. Since I could not access the
frontend's actual source files (GitHub blocks automated crawling of the file
tree), **the exact JSON field names below may not match what `Upload.jsx` /
`Results.jsx` currently expect** — you'll need to adapt one side. I'd
recommend adapting the frontend's fetch calls to this API's actual response
shapes (documented below), since this API's shapes are what actually exists
and has been tested.

---

## Quick start

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env      # optional — defaults work out of the box
uvicorn app.main:app --reload --port 8000
```

Open `http://localhost:8000/docs` for interactive Swagger UI — every endpoint
below can be tried directly from the browser.

Run tests:
```bash
pytest tests/ -v
```

---

## 1. Final architecture

```
                 ┌─────────────────────┐
                 │   React Frontend     │  (separate repo, not modified here)
                 └──────────┬───────────┘
                            │ HTTP/JSON
                 ┌──────────▼───────────┐
                 │   FastAPI app.main    │
                 │  (CORS, routing)      │
                 └──────────┬───────────┘
        ┌──────────┬────────┼────────┬───────────┬─────────┐
        ▼          ▼        ▼        ▼           ▼         ▼
   materials   matching  approvals  nmc        sync    dashboard/audit
     API         API        API     API        API         API
        │          │        │        │           │         │
        └──────────┴────────┼────────┴───────────┴─────────┘
                            ▼
                 ┌─────────────────────┐
                 │   services/ layer    │
                 │  normalize.py        │ (from prototype, unchanged)
                 │  extract_attributes  │ (from prototype, unchanged)
                 │  standardization.py  │ (new: full fields + templates)
                 │  matching.py         │ (new: lexical+semantic+technical)
                 │  approval_service.py │ (new: persisted workflow)
                 │  nmc_service.py      │ (new: NMC + legacy mapping)
                 │  ingestion.py        │ (new: upload/sync orchestration)
                 │  mock_cpse_api.py    │ (new: mock CPSE ERP endpoints)
                 └──────────┬───────────┘
                            ▼
                 ┌─────────────────────┐
                 │   SQLAlchemy models  │
                 │   (SQLite by default,│
                 │    swap DATABASE_URL │
                 │    for Postgres)     │
                 └─────────────────────┘
```

## 2. Data flow

```
CPSE file upload OR mock CPSE API sync
        │
        ▼
Column mapping (normalize.map_columns) — different CPSE column names → common schema
        │
        ▼
Full attribute extraction (standardization.extract_full_attributes)
   regex/keyword rules: category, material_type, diameter, length, width,
   height, weight, standard, schedule, connection, pressure, thread_type
        │
        ▼
Normalization (normalize.py) — units → mm, tokens → canonical form
   (1/2" = 15NB = 15mm; ASTM-F439 = ASTM F439)
        │
        ▼
Category-specific standardization template applied
   (Valve → CATEGORY-SUBCATEGORY-SIZE-MATERIAL-CONNECTION, etc.)
        │
        ▼
Persisted as MaterialRecord
        │
        ▼
Continuous duplicate check (ingestion._check_against_master)
   compares the new/updated record against the ENTIRE existing master
   from other CPSEs immediately, not just in a later batch job
        │
        ▼
Hybrid matching (matching.py): lexical + semantic + technical → MatchCandidate
        │
        ▼
Match type classification (5 types) + critical conflict check
        │
        ▼
Approval recommendation created (ApprovalRecord, status=PENDING)
        │
        ▼
Human reviewer: APPROVE / REJECT / NEEDS_REVIEW  (via /api/approvals/{id}/decide)
        │
        ├─ APPROVE → National Material Code assigned/reused (nmc_service.py)
        │            → LegacyCodeMapping created (old code NEVER deleted)
        │
        └─ every step logged to AuditLog
```

## 3. AI/ML methods used

| Layer | Method | Why |
|---|---|---|
| Lexical | RapidFuzz `token_sort_ratio` + `token_set_ratio` + `partial_ratio` (blended) | Catches word-order differences, abbreviations, extra/missing words |
| Semantic | Sentence-Transformers `all-MiniLM-L6-v2` embeddings + cosine similarity, **or** offline TF-IDF character n-grams if no internet | Catches different wording with same meaning ("CPVC BALL VALVE 1/2 INCH SOCKET" ≈ "15 MM CPVC BALL VALVE WITH SOCKET CONNECTION") |
| Technical | Rule-based structured attribute comparison with a hard critical/soft distinction | The safety layer — never lets text similarity alone declare equivalence |
| Extraction | Regex + keyword dictionaries | Deterministic, auditable, fast; no LLM dependency required for the system to function |

No LLM call is required anywhere in the pipeline for a match decision — by
design, per your explicit "do not build a fake AI demo" requirement. An LLM
could be added later purely as an additional attribute-extraction assist for
attributes the regex layer misses, without touching the scoring/classification
logic.

## 4. Database changes (all new — no prior DB existed)

Tables: `materials`, `match_candidates`, `approvals`, `national_material_codes`,
`legacy_code_mappings`, `audit_logs`, `sync_logs`.

Full field list on `materials` matches the SIH 26099 spec's required schema
(see `app/models/models.py::MaterialRecord`) — 35+ columns including all of
diameter/length/width/height/weight/manufacturer/supplier/price/PO
number/procurement date/UNSPSC/CPSE classification code/etc.

## 5. API endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/materials/upload?cpse_name=X` | Upload CSV/Excel, ingest + standardize + continuous dup check |
| GET | `/api/materials` | List materials (filter by cpse, category, nmc) |
| GET | `/api/materials/{id}` | Get one material |
| GET | `/api/materials/search/semantic?q=...` | Semantic search |
| POST | `/api/matching/run?cpse=X` | Batch hybrid matching run |
| GET | `/api/matching/candidates` | List match candidates (filter by type, min confidence) |
| GET | `/api/matching/candidates/{id}` | Get one candidate |
| POST | `/api/matching/compare` | Compare two specific materials (comparison screen) |
| GET | `/api/approvals` | List approvals (filter by status) |
| POST | `/api/approvals/{id}/decide` | APPROVE / REJECT / NEEDS_REVIEW |
| GET | `/api/nmc` | List National Material Codes |
| GET | `/api/nmc/{code}` | Full legacy mapping for one NMC |
| GET | `/api/sync/connectors` | List available mock CPSE connectors |
| POST | `/api/sync/{cpse_name}` | Trigger sync (incremental if prior sync exists) |
| GET | `/api/sync/logs` | Sync history |
| GET | `/api/dashboard/stats` | All dashboard metrics in one call |
| GET | `/api/audit` | Audit trail (filter by material/match) |

## 6. Frontend changes

None made directly — I don't have write access to `sih26099/frontend` and
couldn't fetch its source files (GitHub blocks crawling). Per the frontend's
own README, the integration points are:
- `src/pages/Upload.jsx` `handleRun` → `POST /api/materials/upload?cpse_name=...` (multipart form with `file`)
- `src/pages/Results.jsx` → `GET /api/matching/candidates` or `GET /api/dashboard/stats`, replacing the `mockClusters` import

You'll need to reconcile field names between this API's Pydantic schemas
(`app/schemas/schemas.py`) and whatever `mockClusters.js` currently defines.

## 7. How matching works

See "AI/ML methods" above. Concretely, for any pair of materials:
```
final_confidence = WEIGHT_LEXICAL * lexical_similarity
                  + WEIGHT_SEMANTIC * semantic_similarity
                  + WEIGHT_TECHNICAL * technical_similarity
```
Then: if any CRITICAL attribute (material_type, diameter, standard,
pressure_rating, thread_type) differs, the result is capped below
EXACT_DUPLICATE/NEAR_DUPLICATE regardless of final_confidence — it can at
best be FUNCTIONALLY_EQUIVALENT or lower.

## 8. How confidence is calculated

Fully configurable via `.env` (see `.env.example`) — weights and all five
thresholds are environment variables, not hardcoded constants, per your
explicit requirement.

## 9. How human approval works

Every match candidate above `MIN_CONFIDENCE_TO_STORE` gets an `ApprovalRecord`
(status=PENDING) with the full evidence attached. A human calls
`POST /api/approvals/{id}/decide` with APPROVE/REJECT/NEEDS_REVIEW. APPROVE
is the only action that mutates the material master (assigns an NMC).
REJECT and NEEDS_REVIEW never touch the master. All three log to `AuditLog`.

## 10. How CPSE integration works

`app/services/mock_cpse_api.py` simulates two CPSE ERP systems in-process,
with pagination and `last_modified_date`-based incremental sync — structurally
identical to what a real integration needs. `app/services/ingestion.py::sync_cpse`
is the orchestration layer; swapping mock for real authorized CPSE APIs means
replacing only `mock_cpse_api.fetch_materials`'s implementation, nothing else.

## 11. Mapping to SIH 26099 requirements

| Requirement | Status | Where |
|---|---|---|
| Full material schema | ✅ | `models.py::MaterialRecord` |
| Lexical matching | ✅ (new) | `matching.py::lexical_similarity` |
| Semantic matching | ✅ | `matching.py::compute_embeddings` |
| Technical attribute matching | ✅ | `matching.py::technical_similarity` |
| Critical conflict detection | ✅ | `matching.py::critical_conflicts`, tested explicitly |
| Configurable hybrid scoring | ✅ | `core/config.py` env vars |
| 5 match types | ✅ | `models.py::MatchType` |
| Standardization engine w/ category templates | ✅ | `standardization.py::STANDARDIZATION_TEMPLATES` |
| National Material Code | ✅ | `nmc_service.py` |
| Legacy code mapping (never destroyed) | ✅ | `LegacyCodeMapping`, tested explicitly |
| Human approval workflow | ✅ | `approval_service.py` |
| Mock CPSE API integration | ✅ | `mock_cpse_api.py` |
| Continuous duplicate detection | ✅ | `ingestion._check_against_master` |
| Dashboard | ✅ (API only — no UI built here) | `dashboard.py` |
| Material comparison screen | ✅ (API only) | `matching.py::compare_pair`, `/api/matching/compare` |
| Semantic search | ✅ | `/api/materials/search/semantic` |
| Audit trail | ✅ | `AuditLog`, populated by every mutating action |

## 12. How to run and test

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
pytest tests/ -v
```

Try it via Swagger UI at `/docs`, or:
```bash
curl -X POST "http://localhost:8000/api/materials/upload?cpse_name=OIL" \
  -F "file=@your_oil_data.csv"
curl -X POST "http://localhost:8000/api/matching/run"
curl "http://localhost:8000/api/dashboard/stats"
```

---

## Known limitations (be upfront about these in your demo)

- **O(n²) matching / O(n) continuous-dup-check**: fine for hundreds–low
  thousands of records (hackathon/demo scale). A real deployment needs an
  approximate-nearest-neighbor vector index (pgvector) — the interface
  (`MaterialView` → `find_matches`) is designed so this swap wouldn't change
  calling code.
- **Embedding backend depends on internet access** on first run (to download
  `all-MiniLM-L6-v2`). Falls back to offline TF-IDF automatically — works,
  but weaker semantic matching quality. Say this explicitly if asked.
- **SQLite by default** — fine for a demo; set `DATABASE_URL` to Postgres for
  anything beyond that.
- **Frontend integration is unverified** — I could not access the actual
  frontend source files, so the API contract above is my best-specified
  guess at what's needed, not a verified match to `Results.jsx`/`Upload.jsx`.
