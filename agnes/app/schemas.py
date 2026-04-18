"""Pydantic models = the API contract the mobile app codes against."""
from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field


class HealthOut(BaseModel):
    status: str
    llm_enabled: bool
    db_path: str


class Evidence(BaseModel):
    source: str
    detail: str


class CandidateOut(BaseModel):
    product_id: int
    sku: Optional[str]
    n_companies: int
    n_suppliers: int
    n_boms: int
    fragmentation_score: int


class ProductDetailOut(BaseModel):
    id: int
    sku: Optional[str]
    type: Optional[str]
    canonical_name: Optional[str]
    canonical_confidence: Optional[float]
    suppliers: List[Dict[str, Any]]
    consumed_by_companies: List[Dict[str, Any]]
    consuming_bom_count: int
    evidence: List[Evidence]


class SubstituteRequest(BaseModel):
    product_a_id: int = Field(..., description="Currently-used raw material")
    product_b_id: int = Field(..., description="Proposed substitute")
    mode: str = Field("strict", pattern="^(strict|creative)$")


class SubstituteOut(BaseModel):
    verdict: str
    confidence: float
    reasoning: str
    mode: str
    evidence: List[Evidence]


class RecommendRequest(BaseModel):
    product_id: int
    mode: str = Field("strict", pattern="^(strict|creative)$")


class DashboardOut(BaseModel):
    raw_materials: int
    current_supplier_relationships: int
    agnes_consolidated_relationships: int
    reduction_pct: float
    fragmented_materials: int


class ChatRequest(BaseModel):
    message: str = Field(..., description="User chat message")


class ChatResponse(BaseModel):
    type: str = Field(..., description="Response type: text, dashboard, table, product, substitution, recommendation")
    message: str = Field(..., description="Human-readable message")
    data: Optional[Dict[str, Any]] = Field(None, description="Structured data payload")
    intent: Optional[str] = Field(None, description="Detected intent")
    llm_enabled: Optional[bool] = Field(None, description="Whether LLM is active")


class InventoryItem(BaseModel):
    sku: str
    type: str
    canonical_name: Optional[str]
    supplier_count: Optional[int]


class SupplierInventoryOut(BaseModel):
    supplier_name: str
    materials: List[InventoryItem]
