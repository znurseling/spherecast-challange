# Quickstart

## 1. Install

```bash
cd agnes
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## 2. Pick a database

**Option A — use the real hackathon DB:**
Drop the provided `db.sqlite` into the project root (next to `README.md`).

**Option B — use the built-in demo data** (for development):
```bash
python -m app.seed_demo
```

## 3. Run

```bash
export AGNES_API_KEY=devkey
# optional — skip for mock mode:
# export ANTHROPIC_API_KEY=sk-ant-...
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open http://localhost:8000/docs — interactive Swagger UI, click "Authorize" and paste `devkey`.

## 4. Smoke test from the terminal

```bash
bash curl_examples.sh
```

## 5. Point the mobile app at it

Base URL: `http://<your-laptop-ip>:8000`
Auth header: `X-API-Key: devkey`
Full contract: http://localhost:8000/openapi.json

---

## Project map — where to edit what

| You want to...                                 | Edit this file              |
|------------------------------------------------|-----------------------------|
| Change the consolidation scoring formula       | `app/consolidation.py`      |
| Change how SKUs get cleaned                    | `app/llm.py` → `_mock_canonical` |
| Change the substitution-reasoning prompt       | `app/llm.py` → `assess_substitution` |
| Change how a recommendation is built           | `app/recommender.py`        |
| Add a new API endpoint                         | `app/main.py` + `app/schemas.py` |
| Add external enrichment (web scraping)         | create `app/enrichment.py` and call it from `recommender.py` |

## The four things to build next, in priority order

1. **Real enrichment.** Write `app/enrichment.py` that, given a supplier name, scrapes or fetches a product page and extracts certifications/purity. Feed results into `assess_substitution` as `context`.
2. **Compliance inference from the finished-good side.** In `recommender.py`, before assessing substitutes, look at the finished goods that use the target raw material, classify them ("organic granola bar", "kosher cereal"), and pass those constraints into the LLM prompt as required properties the substitute must satisfy.
3. **Evidence-trail UI.** Even without a mobile app, a single HTML page that calls `/api/v1/recommend` and renders the evidence list is a killer demo artifact.
4. **Feedback loop.** Add `POST /api/v1/feedback` that accepts `{recommendation_id, accepted: bool, reason}` and writes to a new table. Pitch this as "Agnes learns from procurement decisions."
