"""
Chat endpoint — natural-language interface to every Agnes capability.

Receives a user message, detects intent via keyword/regex matching,
calls the appropriate internal function, and returns a structured
response the frontend renders as rich cards, tables, or plain text.
"""
import re
from typing import Dict, List, Any
from . import consolidation, recommender
from .normalizer import normalize
from .llm import assess_substitution, chat_with_agnes
from .config import LLM_ENABLED


# ── Intent detection ────────────────────────────────────────────────

_INTENTS = [
    # (pattern, intent_name, description)
    # ORDER MATTERS — more specific intents first
    (r"\bhow\s+(many|much)\b|\b(count|inventory|stock)\s+of\b|\bdo\s+we\s+have\b",
     "material_count", "Count raw materials by name"),
    (r"\b(dashboard|overview|summary|portfolio|stats|status)\b", "dashboard",
     "Show portfolio dashboard"),
    (r"\b(candidates?|consolidat|fragment|opportunit)\b", "candidates",
     "List consolidation candidates"),
    (r"\b(substitut|replace|swap|interchange)\b", "substitute",
     "Check substitution feasibility"),
    (r"\b(recommend|suggest|propos|sourc)\b", "recommend",
     "Get sourcing recommendation"),
    (r"\b(product|detail|info|about)\b.*?\b(\d+)\b", "product_detail",
     "Product detail lookup"),
    (r"\b(help|what can you|commands|how do|capabilities)\b", "help",
     "Show available commands"),
    (r"\b(hello|hi|hey|greet|good morning|good evening)\b", "greeting",
     "Greeting"),
]


def _detect_intent(message: str) -> str:
    low = message.lower().strip()
    for pattern, intent, _ in _INTENTS:
        if re.search(pattern, low):
            return intent
    return "unknown"


def _extract_numbers(message: str) -> List[int]:
    return [int(x) for x in re.findall(r"\b(\d+)\b", message)]


def _extract_mode(message: str) -> str:
    if "creative" in message.lower():
        return "creative"
    return "strict"


def _chat_context(message: str) -> Dict[str, Any]:
    numbers = _extract_numbers(message)
    candidates = consolidation.consolidation_candidates(limit=3)
    context: Dict[str, Any] = {
        "portfolio_summary": consolidation.portfolio_summary(),
        "top_candidates": [
            {
                "product_id": row["product_id"],
                "sku": row["sku"],
                "fragmentation_score": row["fragmentation_score"],
                "n_companies": row["n_companies"],
                "n_suppliers": row["n_suppliers"],
            }
            for row in candidates
        ],
    }

    if numbers:
        products = []
        for product_id in numbers[:3]:
            detail = consolidation.product_detail(product_id)
            if not detail:
                continue
            norm = normalize(detail["sku"] or "")
            products.append({
                "id": detail["id"],
                "sku": detail["sku"],
                "type": detail["type"],
                "canonical_name": norm["canonical_name"],
                "suppliers": [s["name"] for s in detail["suppliers"]],
                "companies": [c["name"] for c in detail["consumed_by_companies"]],
                "bom_count": detail["consuming_bom_count"],
            })
        if products:
            context["referenced_products"] = products

    return context


# ── Response builders ───────────────────────────────────────────────

def _greeting_response() -> Dict:
    return {
        "type": "text",
        "message": (
            "👋 Hello! I'm **Agnes**, your AI Supply Chain Manager.\n\n"
            "I can help you with:\n"
            "- 📊 **Dashboard** — portfolio overview & consolidation stats\n"
            "- 🔍 **Candidates** — find fragmented raw materials\n"
            "- 📦 **Product details** — look up any raw material by ID\n"
            "- 🔄 **Substitution checks** — can material B replace A?\n"
            "- 💡 **Recommendations** — consolidated sourcing proposals\n\n"
            "Try saying *\"show me the dashboard\"* or *\"top candidates\"*!"
        ),
    }


def _help_response() -> Dict:
    return {
        "type": "text",
        "message": (
            "Here's what I can do:\n\n"
            "| Command | Example |\n"
            "|---|---|\n"
            "| 📊 Dashboard | *\"show dashboard\"* |\n"
            "| 🔍 Candidates | *\"top consolidation candidates\"* |\n"
            "| 📦 Product detail | *\"tell me about product 200\"* |\n"
            "| 🔄 Substitution | *\"can 201 substitute 200?\"* |\n"
            "| 💡 Recommend | *\"recommend for product 200\"* |\n\n"
            "You can also use the **quick action** buttons below the chat!"
        ),
    }


def _dashboard_response() -> Dict:
    summary = consolidation.portfolio_summary()
    return {
        "type": "dashboard",
        "message": "Here's your portfolio overview:",
        "data": {
            "cards": [
                {"label": "Raw Materials", "value": summary["raw_materials"],
                 "icon": "🧪"},
                {"label": "Current Suppliers", "value": summary["current_supplier_relationships"],
                 "icon": "🏭"},
                {"label": "Agnes Target", "value": summary["agnes_consolidated_relationships"],
                 "icon": "🎯"},
                {"label": "Reduction", "value": f"{summary['reduction_pct']}%",
                 "icon": "📉"},
                {"label": "Fragmented Materials", "value": summary["fragmented_materials"],
                 "icon": "⚠️"},
            ],
        },
    }


def _candidates_response(message: str) -> Dict:
    numbers = _extract_numbers(message)
    limit = numbers[0] if numbers and numbers[0] <= 50 else 10
    rows = consolidation.consolidation_candidates(limit=limit)
    table_rows = []
    for r in rows:
        table_rows.append({
            "id": r["product_id"],
            "sku": r["sku"] or "—",
            "companies": r["n_companies"],
            "suppliers": r["n_suppliers"],
            "boms": r["n_boms"],
            "score": r["fragmentation_score"],
        })
    return {
        "type": "table",
        "message": f"Top **{len(table_rows)}** consolidation candidates ranked by fragmentation score:",
        "data": {
            "columns": [
                {"key": "id", "label": "ID"},
                {"key": "sku", "label": "SKU"},
                {"key": "companies", "label": "Companies"},
                {"key": "suppliers", "label": "Suppliers"},
                {"key": "boms", "label": "BOMs"},
                {"key": "score", "label": "Score"},
            ],
            "rows": table_rows,
        },
    }


def _product_response(message: str) -> Dict:
    numbers = _extract_numbers(message)
    if not numbers:
        return {"type": "text", "message": "Please specify a product ID, e.g. *\"product 200\"*"}
    product_id = numbers[0]
    detail = consolidation.product_detail(product_id)
    if not detail:
        return {"type": "text", "message": f"❌ Product **{product_id}** not found."}
    norm = normalize(detail["sku"] or "")
    return {
        "type": "product",
        "message": f"Details for product **{product_id}**:",
        "data": {
            "id": detail["id"],
            "sku": detail["sku"],
            "type": detail["type"],
            "canonical_name": norm["canonical_name"],
            "confidence": norm["confidence"],
            "suppliers": detail["suppliers"],
            "companies": detail["consumed_by_companies"],
            "bom_count": detail["consuming_bom_count"],
            "evidence": norm["evidence"],
        },
    }


def _substitute_response(message: str) -> Dict:
    numbers = _extract_numbers(message)
    if len(numbers) < 2:
        return {
            "type": "text",
            "message": "I need two product IDs to check substitution.\n\nExample: *\"can 201 substitute 200?\"*",
        }
    a_id, b_id = numbers[0], numbers[1]
    a = consolidation.product_detail(a_id)
    b = consolidation.product_detail(b_id)
    if not a or not b:
        return {"type": "text", "message": f"❌ One or both products ({a_id}, {b_id}) not found."}

    mode = _extract_mode(message)
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
    result = assess_substitution(a_info, b_info, mode=mode)

    verdict_emoji = {"accept": "✅", "review": "🔍", "reject": "❌"}.get(
        result["verdict"], "❓"
    )

    return {
        "type": "substitution",
        "message": f"Substitution analysis ({mode} mode):",
        "data": {
            "product_a": {"id": a_id, "sku": a["sku"],
                          "canonical": a_info["canonical_name"]},
            "product_b": {"id": b_id, "sku": b["sku"],
                          "canonical": b_info["canonical_name"]},
            "verdict": f"{verdict_emoji} {result['verdict'].upper()}",
            "confidence": result["confidence"],
            "reasoning": result["reasoning"],
            "mode": mode,
            "evidence": result["evidence"],
        },
    }


def _recommend_response(message: str) -> Dict:
    numbers = _extract_numbers(message)
    mode = _extract_mode(message)

    if not numbers:
        # Fall back to top recommendations
        recs = recommender.top_recommendations(limit=3, mode=mode)
        if not recs:
            return {"type": "text", "message": "No recommendations available."}
        return {
            "type": "recommendations",
            "message": f"Top **{len(recs)}** sourcing recommendations ({mode} mode):",
            "data": {"recommendations": recs},
        }

    product_id = numbers[0]
    rec = recommender.recommend_for_product(product_id, mode=mode)
    if "error" in rec:
        return {"type": "text", "message": f"❌ {rec['error']}"}
    return {
        "type": "recommendation",
        "message": f"Sourcing recommendation for product **{product_id}** ({mode} mode):",
        "data": rec,
    }


_STOPWORDS = {
    "how", "many", "much", "do", "we", "have", "of", "the", "a", "an",
    "is", "are", "there", "any", "count", "inventory", "stock", "got",
    "our", "in", "does", "has", "had", "can", "you", "tell", "me", "show",
    "please", "for", "product", "products", "material", "materials", "raw",
}


def _extract_keyword(message: str) -> str:
    tokens = re.findall(r"[A-Za-z][A-Za-z\-]+", message.lower())
    kept = [t for t in tokens if t not in _STOPWORDS and len(t) > 1]
    return " ".join(kept).strip()


def _material_count_response(message: str) -> Dict:
    keyword = _extract_keyword(message)
    if not keyword:
        return {
            "type": "text",
            "message": "Which material? Try *\"how many zinc do we have?\"*",
        }
    # Try full phrase, then individual tokens — pick the one with most hits
    best = consolidation.search_by_material(keyword)
    if best["count"] == 0 and " " in keyword:
        for tok in keyword.split():
            r = consolidation.search_by_material(tok)
            if r["count"] > best["count"]:
                best = r
                keyword = tok

    if best["count"] == 0:
        return {
            "type": "text",
            "message": f"❌ No raw materials matching **{keyword}** found.",
        }

    suppliers = best["suppliers"]
    sup_lines = "\n".join(
        f"- **{s['name']}** — supplies {s['product_count']} variant"
        f"{'s' if s['product_count'] != 1 else ''}"
        for s in suppliers[:10]
    ) or "_(no suppliers linked)_"

    more = f"\n…and {len(suppliers) - 10} more suppliers" if len(suppliers) > 10 else ""

    return {
        "type": "text",
        "message": (
            f"📦 We have **{best['count']}** raw-material "
            f"variant{'s' if best['count'] != 1 else ''} matching "
            f"**{keyword}**, used across **{len(best['companies'])}** "
            f"compan{'ies' if len(best['companies']) != 1 else 'y'}.\n\n"
            f"**Suppliers ({len(suppliers)}):**\n{sup_lines}{more}"
        ),
    }


def _unknown_response(message: str, context: Dict | None = None) -> Dict:
    # If we have an uploaded SQL dump in the context, merge it into chat context
    if context is None:
        context = _chat_context(message)
    if LLM_ENABLED:
        # Inject uploaded SQL if present in context
        sql_dump = context.get("uploaded_sql")
        if sql_dump:
            # Append the raw SQL dump to the context for the LLM
            context["uploaded_sql"] = sql_dump
        text = chat_with_agnes(message, context=context)
        if text:
            return {"type": "text", "message": text}
    
    return {
        "type": "text",
        "message": (
            "I'm not sure I understand. Here are some things you can ask:\n\n"
            "- *\"Show me the dashboard\"*\n"
            "- *\"Top consolidation candidates\"*\n"
            "- *\"Product 200 details\"*\n"
            "- *\"Can 201 substitute 200?\"*\n"
            "- *\"Recommend sourcing for product 200\"*\n\n"
            "Or just say **help**!"
        ),
    }


# ── Main chat handler ──────────────────────────────────────────────

_HANDLERS = {
    "greeting":       lambda msg: _greeting_response(),
    "help":           lambda msg: _help_response(),
    "dashboard":      lambda msg: _dashboard_response(),
    "material_count": _material_count_response,
    "candidates":     _candidates_response,
    "product_detail": _product_response,
    "substitute":     _substitute_response,
    "recommend":      _recommend_response,
    "unknown":        _unknown_response,
}


def handle_chat(message: str, uploaded_sql: str | None = None) -> Dict:
    """Process a user chat message and return a structured response.
    If an SQL dump was uploaded, its content is passed as `uploaded_sql`.
    This will be injected into the LLM context for conversational fallback.
    """
    intent = _detect_intent(message)
    handler = _HANDLERS.get(intent, _unknown_response)
    # If the request is unknown and we have uploaded SQL, embed it in the context
    if intent == "unknown" and uploaded_sql:
        # Extend the chat context with the raw SQL dump
        context = _chat_context(message)
        context["uploaded_sql"] = uploaded_sql
        response = handler(message, context=context)
    else:
        response = handler(message)
    response["intent"] = intent
    response["llm_enabled"] = LLM_ENABLED
    return response
