"""
FastAPI application. This is what the mobile app talks to.

Auth: every request must send `X-API-Key: <AGNES_API_KEY>`.
Docs: http://localhost:8000/docs
"""
import sqlite3
from pathlib import Path
from typing import List
from fastapi import FastAPI, Depends, Header, HTTPException, Query, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .config import API_KEY, DB_PATH, LLM_ENABLED
from .schemas import (
    HealthOut, CandidateOut, ProductDetailOut, SubstituteRequest,
    SubstituteOut, RecommendRequest, DashboardOut,
    ChatRequest, ChatResponse,
)
from . import consolidation, recommender
from .normalizer import normalize
from .llm import assess_substitution
from .chat import handle_chat
from .db import schema, init_db

init_db()


# ---------- auth dependency ----------

def require_api_key(x_api_key: str = Header(None, alias="X-API-Key")):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return x_api_key


# ---------- app ----------

app = FastAPI(
    title="Agnes — AI Supply Chain Manager",
    version="0.1.0",
    description=(
        "Backend API for the Agnes mobile app. "
        "Consolidation analysis, LLM reasoning, and evidence-trail "
        "sourcing recommendations for CPG raw materials."
    ),
)

# Mobile apps call from arbitrary origins — permit broadly in dev.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- static files ----------

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@app.get("/", include_in_schema=False)
def serve_index():
    return FileResponse(STATIC_DIR / "index.html")


# Mount static files AFTER the root route
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------- routes ----------

@app.get("/api/v1/health", response_model=HealthOut, tags=["system"])
def health():
    return HealthOut(status="ok", llm_enabled=LLM_ENABLED, db_path=DB_PATH)


@app.get("/api/v1/candidates",
         response_model=List[CandidateOut],
         dependencies=[Depends(require_api_key)],
         tags=["analysis"])
def candidates(limit: int = Query(20, ge=1, le=200)):
    """Top consolidation candidates ranked by fragmentation score."""
    rows = consolidation.consolidation_candidates(limit=limit)
    return [
        CandidateOut(
            product_id=r["product_id"], sku=r["sku"],
            n_companies=r["n_companies"], n_suppliers=r["n_suppliers"],
            n_boms=r["n_boms"], fragmentation_score=r["fragmentation_score"],
        ) for r in rows
    ]


@app.get("/api/v1/products/{product_id}",
         response_model=ProductDetailOut,
         dependencies=[Depends(require_api_key)],
         tags=["analysis"])
def product(product_id: int):
    detail = consolidation.product_detail(product_id)
    if not detail:
        raise HTTPException(404, f"product {product_id} not found")
    norm = normalize(detail["sku"] or "")
    return ProductDetailOut(
        **detail,
        canonical_name=norm["canonical_name"],
        canonical_confidence=norm["confidence"],
        evidence=norm["evidence"],
    )


@app.post("/api/v1/substitute",
          response_model=SubstituteOut,
          dependencies=[Depends(require_api_key)],
          tags=["reasoning"])
def substitute(req: SubstituteRequest):
    a = consolidation.product_detail(req.product_a_id)
    b = consolidation.product_detail(req.product_b_id)
    if not a or not b:
        raise HTTPException(404, "one or both products not found")
    a_info = {
        "product_id": a["id"], "sku": a["sku"],
        "canonical_name": normalize(a["sku"] or "")["canonical_name"],
        "supplier_ids": [s["id"] for s in a["suppliers"]],
    }
    b_info = {
        "product_id": b["id"], "sku": b["sku"],
        "canonical_name": normalize(b["sku"] or "")["canonical_name"],
        "supplier_ids": [s["id"] for s in b["suppliers"]],
    }
    result = assess_substitution(a_info, b_info, mode=req.mode)
    return SubstituteOut(**result)


@app.post("/api/v1/recommend",
          dependencies=[Depends(require_api_key)],
          tags=["reasoning"])
def recommend(req: RecommendRequest):
    return recommender.recommend_for_product(req.product_id, mode=req.mode)


@app.get("/api/v1/recommendations/top",
         dependencies=[Depends(require_api_key)],
         tags=["reasoning"])
def top(limit: int = Query(5, ge=1, le=20), mode: str = "strict"):
    if mode not in ("strict", "creative"):
        raise HTTPException(400, "mode must be strict or creative")
    return recommender.top_recommendations(limit=limit, mode=mode)


@app.get("/api/v1/dashboard",
         response_model=DashboardOut,
         dependencies=[Depends(require_api_key)],
         tags=["analysis"])
def dashboard():
    return DashboardOut(**consolidation.portfolio_summary())


from .schemas import SupplierInventoryOut
from .db import get_supplier_inventory

@app.get("/api/v1/inventory",
         response_model=List[SupplierInventoryOut],
         dependencies=[Depends(require_api_key)],
         tags=["analysis"])
def inventory():
    return get_supplier_inventory()

# ---------- chat endpoint ----------

@app.post("/api/v1/chat",
          response_model=ChatResponse,
          dependencies=[Depends(require_api_key)],
          tags=["chat"])
def chat(req: ChatRequest):
    """Natural-language chat interface to all Agnes capabilities."""
    result = handle_chat(req.message, history=req.history)
    return ChatResponse(**result)
