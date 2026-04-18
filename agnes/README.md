# Agnes — AI Supply Chain Manager

Hackathon prototype for Spherecast. FastAPI backend + SQLite +
LLM reasoning layer, mobile-app-ready via REST + API key auth.

## Run

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-...        # optional; falls back to mock
export AGNES_API_KEY=devkey             # mobile app sends this header
python -m app.seed_demo                 # only if you don't have db.sqlite
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open http://localhost:8000/docs for the interactive API.

## Architecture (what matters for judging)

```
 Mobile app  ──HTTPS──▶  FastAPI (app/main.py)
                           │
              ┌────────────┼────────────────┬──────────────┐
              ▼            ▼                ▼              ▼
         consolidation  normalizer      reasoner      enrichment
         (SQL only)     (LLM + cache)   (RAG + LLM)   (web stub)
                           │                │
                           ▼                ▼
                       SQLite db.sqlite (provided)
```

Every AI output carries an **evidence trail** (list of sources +
confidence). Nothing is claimed without a source — this is the
anti-hallucination story for judges.

## Endpoints the mobile app will call

| Method | Path                           | Purpose                                    |
|--------|--------------------------------|--------------------------------------------|
| GET    | /api/v1/health                 | liveness                                   |
| GET    | /api/v1/candidates             | top consolidation opportunities            |
| GET    | /api/v1/products/{id}          | raw-material detail + normalized name      |
| POST   | /api/v1/substitute             | "can A replace B?" with evidence trail     |
| POST   | /api/v1/recommend              | consolidated sourcing proposal (Strict/Creative) |
| GET    | /api/v1/dashboard              | current-state vs Agnes-state summary       |

All endpoints require `X-API-Key` header.
