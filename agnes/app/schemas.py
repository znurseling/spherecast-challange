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
    history: Optional[List[Dict[str, str]]] = Field(default=[], description="Previous chat history")


class ChatResponse(BaseModel):
    type: str = Field(..., description="Response type: text, dashboard, table, product, substitution, recommendation")
    message: str = Field(..., description="Human-readable message")
    data: Optional[Dict[str, Any]] = Field(None, description="Structured data payload")
    intent: Optional[str] = Field(None, description="Detected intent")
    llm_enabled: Optional[bool] = Field(None, description="Whether LLM is active")


class SubstituteSuggestion(BaseModel):
    supplier_name: str
    sku: str
    stock_quantity: int


class InventoryItem(BaseModel):
    sku: str
    type: str
    canonical_name: Optional[str]
    supplier_count: Optional[int]
    market_price_avg: Optional[float] = None
    market_price_min: Optional[float] = None
    market_price_max: Optional[float] = None
    is_estimate: Optional[bool] = False
    purity_percentage: Optional[float] = None
    grade: Optional[str] = None
    lab_status: Optional[str] = None
    certifications: Optional[str] = None
    quality_audit_score: Optional[int] = None
    sustainability_rating: Optional[str] = None
    stock_quantity: Optional[int] = None
    stock_status: Optional[str] = None  # ok | low | out | unknown
    substitute: Optional[SubstituteSuggestion] = None


class SupplierInventoryOut(BaseModel):
    supplier_name: str
    materials: List[InventoryItem]
