"""
Local demo — runs the full Agnes API end-to-end without starting a server.
Uses FastAPI TestClient + mock LLM mode (no ANTHROPIC_API_KEY needed).

Usage:
    python demo.py
"""
import os, sys, json, textwrap

# Use demo DB in /tmp so we don't clobber the real db.sqlite
os.environ.setdefault("AGNES_API_KEY", "devkey")
os.environ.setdefault("AGNES_DB", "/tmp/agnes_demo.sqlite")
os.environ.pop("ANTHROPIC_API_KEY", None)   # force mock mode

# Seed the demo DB
from app.seed_demo import seed
seed()

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
HEADERS = {"X-API-Key": "devkey"}


# ── helpers ──────────────────────────────────────────────────────────────────

def section(title: str):
    bar = "─" * 60
    print(f"\n{bar}\n  {title}\n{bar}")

def show(label: str, data):
    print(f"\n▶ {label}")
    if isinstance(data, (dict, list)):
        lines = json.dumps(data, indent=2).splitlines()
        # truncate long arrays for readability
        if len(lines) > 40:
            lines = lines[:40] + ["  ... (truncated)"]
        print(textwrap.indent("\n".join(lines), "  "))
    else:
        print(f"  {data}")

def ok(resp):
    assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text}"
    return resp.json()


# ── 1. Health ─────────────────────────────────────────────────────────────────

section("1  HEALTH CHECK")
data = ok(client.get("/api/v1/health"))
show("GET /api/v1/health", data)
assert data["status"] == "ok"
print(f"\n  LLM enabled: {data['llm_enabled']}  (mock mode = {not data['llm_enabled']})")


# ── 2. Dashboard ──────────────────────────────────────────────────────────────

section("2  PORTFOLIO DASHBOARD")
data = ok(client.get("/api/v1/dashboard", headers=HEADERS))
show("GET /api/v1/dashboard", data)


# ── 3. Consolidation candidates ───────────────────────────────────────────────

section("3  TOP CONSOLIDATION CANDIDATES")
data = ok(client.get("/api/v1/candidates?limit=5", headers=HEADERS))
show("GET /api/v1/candidates?limit=5", data)

# remember first two candidates for later calls
top_ids = [r["product_id"] for r in data[:2]]


# ── 4. Product detail (with canonicalisation) ─────────────────────────────────

section("4  PRODUCT DETAIL + SKU CANONICALISATION")
for pid in top_ids[:2]:
    d = ok(client.get(f"/api/v1/products/{pid}", headers=HEADERS))
    show(f"GET /api/v1/products/{pid}  →  {d['sku']}", {
        "canonical_name": d["canonical_name"],
        "canonical_confidence": d["canonical_confidence"],
        "n_suppliers": len(d.get("suppliers", [])),
        "evidence": d["evidence"],
    })


# ── 5. Substitution check ─────────────────────────────────────────────────────

section("5  SUBSTITUTION CHECK")

# strict: two different ascorbic-acid SKUs → should accept
payload_strict = {"product_a_id": 200, "product_b_id": 201, "mode": "strict"}
data = ok(client.post("/api/v1/substitute", json=payload_strict, headers=HEADERS))
show("POST /api/v1/substitute  (ascorbic-acid A vs ascorbic-acid B, strict)", data)

# creative: ascorbic-acid vs citric-acid → review/reject
payload_creative = {"product_a_id": 200, "product_b_id": 203, "mode": "creative"}
data = ok(client.post("/api/v1/substitute", json=payload_creative, headers=HEADERS))
show("POST /api/v1/substitute  (ascorbic-acid vs citric-acid, creative)", data)


# ── 6. Recommendation ─────────────────────────────────────────────────────────

section("6  SOURCING RECOMMENDATION")
payload_rec = {"product_id": 200, "mode": "strict"}
resp = client.post("/api/v1/recommend", json=payload_rec, headers=HEADERS)
assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text}"
data = resp.json()
show("POST /api/v1/recommend  (product 200, strict)", data)


# ── 7. Top recommendations ────────────────────────────────────────────────────

section("7  TOP PORTFOLIO RECOMMENDATIONS")
data = ok(client.get("/api/v1/recommendations/top?limit=3&mode=strict", headers=HEADERS))
show("GET /api/v1/recommendations/top?limit=3&mode=strict", data)


# ── 8. Auth guard check ───────────────────────────────────────────────────────

section("8  AUTH GUARD (expected 401)")
resp = client.get("/api/v1/candidates")          # no key
show("GET /api/v1/candidates  (no API key)", {"status_code": resp.status_code, "detail": resp.json()})
assert resp.status_code == 401

resp = client.get("/api/v1/candidates", headers={"X-API-Key": "wrong"})
show("GET /api/v1/candidates  (wrong key)", {"status_code": resp.status_code, "detail": resp.json()})
assert resp.status_code == 401


# ── done ──────────────────────────────────────────────────────────────────────

print("\n" + "═" * 60)
print("  All demo checks passed ✓")
print("═" * 60 + "\n")
