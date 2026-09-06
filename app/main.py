"""
SIH 26099 — AI-Driven Standardization and Harmonization of Material Codes
Across CPSEs. FastAPI backend.

Run: uvicorn app.main:app --reload --port 8000
Docs: http://localhost:8000/docs
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.database import init_db
from app.api import materials, matching, approvals, nmc, sync, dashboard, audit


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="SIH 26099 — Material Code Harmonization API",
    description="Hybrid AI matching engine for standardizing CPSE material master data.",
    version="1.0.0",
    lifespan=lifespan,
)

# Wide-open CORS for the prototype -- the frontend runs on a different port
# (Vite dev server) and we don't yet know its deployed origin. Tighten this
# to an explicit allow-list before any real deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(materials.router)
app.include_router(matching.router)
app.include_router(approvals.router)
app.include_router(nmc.router)
app.include_router(sync.router)
app.include_router(dashboard.router)
app.include_router(audit.router)


@app.get("/")
def root():
    return {
        "service": "SIH 26099 Material Harmonization API",
        "status": "running",
        "docs": "/docs",
    }


@app.get("/health")
def health():
    return {"status": "ok"}
