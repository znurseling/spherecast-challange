"""
Chat endpoint — natural-language interface to every Agnes capability.

Receives a user message, detects intent via keyword/regex matching,
calls the appropriate internal function, and returns a structured
response the frontend renders as rich cards, tables, or plain text.
"""
import re
from typing import Dict, List, Optional, Any
from . import consolidation, recommender
from .normalizer import normalize
from .llm import assess_substitution, chat_with_agnes, understand_message
from .config import LLM_ENABLED


# ── Intent detection ────────────────────────────────────────────────

_INTENTS = [
    # (pattern, intent_name, description)
    # ORDER MATTERS — more specific intents first
    (r"\bhow\s+(many|much)\b|\b(count|inventory|stock)\s+of\b|\bdo\s+we\s+have\b",
     "material_count", "Count raw materials by name"),
    (r"\b(dashboard|overview|summary|portfolio|stats|status)\b", "dashboard",
     "Show portfolio dashboard"),
    (r"\b(deliver|supply|produce|request|order).*\d+.*(but|only|have|short)\b", "order_fulfillment",
     "Fulfill order with potential shortage"),
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

    # Pull real DB results for any material keywords mentioned — gives the
    # LLM concrete data instead of "I don't have access to the database".
    material_hits = _material_hits_from_message(message)
    if material_hits:
        context["material_search"] = material_hits

    return context


def _material_hits_from_message(message: str) -> List[Dict[str, Any]]:
    """Run search_by_material for every plausible keyword in the message and
    return enriched hits so the LLM has real DB data to reason over."""
    keyword_phrase = _extract_keyword(message)
    if not keyword_phrase:
        return []

    tried = set()
    hits: List[Dict[str, Any]] = []
    candidates = [keyword_phrase] + sorted(
        set(keyword_phrase.split()), key=len, reverse=True
    )
    for kw in candidates:
        if kw in tried or len(kw) < 3:
            continue
        tried.add(kw)
        res = consolidation.search_by_material(kw)
        if res["count"] == 0:
            continue
        hits.append({
            "keyword": kw,
            "variant_count": res["count"],
            "companies": [c["name"] for c in res["companies"]],
            "suppliers": [
                {"name": s["name"], "variant_count": s["product_count"]}
                for s in res["suppliers"]
            ],
            "sub_families": [
                {"canonical_name": g["canonical_name"], "count": g["count"]}
                for g in res.get("groups", [])
            ],
            "sample_skus": [p["sku"] for p in res["products"][:8]],
        })
    # Keep the strongest hit(s); drop token subsets that a broader phrase
    # already covered with a larger match count.
    if len(hits) > 1:
        top = max(h["variant_count"] for h in hits)
        hits = [h for h in hits if h["variant_count"] == top] or hits

    # Also include substitution candidates — materials that share any token
    # with the user's keyword but aren't direct matches. This lets the LLM
    # say "you're out of vitamin C, but ascorbic acid is interchangeable."
    subs = consolidation.find_substitutes(keyword_phrase)
    for hit in hits:
        hit["substitute_candidates"] = [
            g for g in subs
            if g["canonical_name"].lower() not in
            {f["canonical_name"].lower() for f in hit["sub_families"]}
        ][:6]

    return hits[:3]


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
    # question / verb filler
    "how", "many", "much", "do", "does", "did", "has", "have", "had",
    "is", "are", "was", "were", "be", "been", "being", "can", "could",
    "would", "should", "will", "shall", "may", "might", "get", "got",
    "want", "need", "know", "tell", "show", "give", "see", "find",
    # pronouns / articles / conjunctions
    "i", "we", "you", "they", "he", "she", "it", "me", "us", "them",
    "my", "our", "your", "their", "his", "her", "its",
    "a", "an", "the", "this", "that", "these", "those",
    "and", "or", "but", "if", "so", "than", "then", "also",
    "of", "in", "on", "at", "to", "from", "by", "for", "with", "about",
    "into", "onto", "out", "over", "under", "up", "down",
    "any", "some", "all", "each", "every", "more", "most", "less",
    "no", "not", "yes", "there", "here", "which", "who", "whom", "what",
    "when", "where", "why", "whose",
    # greetings / filler
    "hi", "hey", "hello", "yo", "hiya", "howdy", "greetings",
    "please", "thanks", "thank", "ok", "okay", "just", "oh", "uh",
    "um", "well", "still", "even",
    # domain filler
    "count", "inventory", "stock", "amount", "quantity", "quantities",
    "total", "number", "left", "remaining", "available",
    "product", "products", "material", "materials", "raw",
    "supply", "supplier", "suppliers", "company", "companies",
    "buy", "purchase", "purchasing", "order", "sourcing",
}


def _extract_keyword(message: str) -> str:
    # Allow single-letter tokens so "Vitamin C" survives. Stopword filter
    # drops noise like "a" / "i".
    tokens = re.findall(r"[A-Za-z][A-Za-z\-]*", message.lower())
    kept = [t for t in tokens if t not in _STOPWORDS]
    return " ".join(kept).strip()


def _best_material_match(message: str):
    """Try the most-specific phrasing first and return the first keyword
    that actually matches something. Prefers 'vitamin c' over 'vitamin',
    'ascorbic acid' over 'acid'. Returns (keyword, result) or (None, None)."""
    keyword_phrase = _extract_keyword(message)
    if not keyword_phrase:
        return None, None

    tokens = keyword_phrase.split()
    candidates: List[str] = []

    def _add(kw: str):
        if kw and kw not in candidates:
            candidates.append(kw)

    _add(keyword_phrase)
    # adjacent pairs capture multi-word materials like 'ascorbic acid'
    for i in range(len(tokens) - 1):
        _add(f"{tokens[i]} {tokens[i+1]}")
    # fall back to individual tokens, longest first
    for tok in sorted(set(tokens), key=len, reverse=True):
        _add(tok)

    for kw in candidates:
        if len(kw) < 2:
            continue
        res = consolidation.search_by_material(kw)
        if res["count"] > 0:
            return kw, res
    return None, None


def _material_count_response(message: str) -> Dict:
    keyword, best = _best_material_match(message)

    if not best:
        # Nothing directly matched — offer substitute hints if any token is
        # a partial canonical match (e.g. user said "vitamin" but we store
        # each vitamin separately).
        raw_kw = _extract_keyword(message)
        subs = consolidation.find_substitutes(raw_kw) if raw_kw else []
        if subs:
            lines = "\n".join(
                f"- **{g['canonical_name']}** — {g['variant_count']} variant"
                f"{'s' if g['variant_count'] != 1 else ''}"
                for g in subs[:8]
            )
            return {
                "type": "text",
                "message": (
                    f"No exact match for **{raw_kw}**, but related "
                    f"raw-material families in inventory:\n\n{lines}\n\n"
                    "Any of these could be a substitution candidate — ask "
                    "*\"can X substitute Y?\"* to check."
                ),
            }
        return {
            "type": "text",
            "message": "Which material are you asking about? Try *\"how much zinc do we have?\"*",
        }

    suppliers = best["suppliers"]
    sup_lines = "\n".join(
        f"- **{s['name']}** — supplies {s['product_count']} variant"
        f"{'s' if s['product_count'] != 1 else ''}"
        for s in suppliers[:10]
    ) or "_(no suppliers linked)_"
    more = f"\n…and {len(suppliers) - 10} more suppliers" if len(suppliers) > 10 else ""

    # Show canonical groupings so the user can see e.g. Zinc vs Zinc Oxide —
    # these are natural substitution families within the match.
    groups = best.get("groups", [])
    group_block = ""
    if len(groups) > 1:
        group_lines = "\n".join(
            f"- **{g['canonical_name']}** — {g['count']} variant"
            f"{'s' if g['count'] != 1 else ''}"
            for g in groups[:6]
        )
        group_block = f"\n\n**Sub-families (potential substitutes):**\n{group_lines}"

    best_supplier = suppliers[0] if suppliers else None
    recommend = ""
    if best_supplier:
        recommend = (
            f"\n\n💡 **Most efficient single source:** **{best_supplier['name']}** "
            f"— covers {best_supplier['product_count']} of {best['count']} "
            f"variants in one relationship."
        )

    return {
        "type": "text",
        "message": (
            f"📦 We have **{best['count']}** raw-material "
            f"variant{'s' if best['count'] != 1 else ''} matching "
            f"**{keyword}**, used across **{len(best['companies'])}** "
            f"compan{'ies' if len(best['companies']) != 1 else 'y'}.\n\n"
            f"**Suppliers ({len(suppliers)}):**\n{sup_lines}{more}"
            f"{group_block}{recommend}"
        ),
    }

def _unknown_response(message: str, history: Optional[List[Dict[str, str]]] = None) -> Dict:
    if LLM_ENABLED:
        text = chat_with_agnes(message, context=_chat_context(message), history=history)
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


# ── LLM-planned handlers ───────────────────────────────────────────

def _material_query_from_plan(message: str, plan: Dict) -> Dict:
    """Execute a material_query plan: the LLM already told us what material
    the user means and what facets they want. We fetch the DB facts and let
    the LLM compose a grounded natural-language reply."""
    material = (plan.get("material") or "").strip()
    if not material:
        # LLM flagged material_query but gave no material — punt to chat.
        return _llm_chat_response(message, plan)

    res = consolidation.search_by_material(material)
    subs = consolidation.find_substitutes(material)

    # Build compact, LLM-friendly evidence blob.
    evidence = {
        "material_asked": material,
        "variant_count": res["count"],
        "suppliers": [
            {"name": s["name"], "variant_count": s["product_count"]}
            for s in res["suppliers"]
        ],
        "companies": [c["name"] for c in res["companies"]],
        "sub_families": [
            {"canonical_name": g["canonical_name"], "count": g["count"]}
            for g in res.get("groups", [])
        ],
        "substitute_families": [
            g for g in subs
            if g["canonical_name"].lower() not in
            {f["canonical_name"].lower() for f in res.get("groups", [])}
        ][:8],
        "sample_skus": [p["sku"] for p in res["products"][:8]],
        "user_intent_flags": {
            k: plan.get(k, False) for k in (
                "wants_count", "wants_suppliers", "wants_companies",
                "wants_substitutes", "wants_efficient",
            )
        },
    }

    if LLM_ENABLED:
        text = chat_with_agnes(message, context=evidence)
        if text:
            return {"type": "text", "message": text, "data": evidence}

    # Deterministic fallback if the LLM composition call fails.
    return _material_evidence_fallback(material, res, subs, plan)


def _material_evidence_fallback(material: str, res: Dict,
                                subs: List[Dict], plan: Dict) -> Dict:
    if res["count"] == 0:
        if subs:
            lines = "\n".join(
                f"- **{g['canonical_name']}** — {g['variant_count']} variant"
                f"{'s' if g['variant_count'] != 1 else ''}"
                for g in subs[:8]
            )
            return {
                "type": "text",
                "message": (
                    f"No exact inventory for **{material}**, but related "
                    f"raw-material families are available as substitution "
                    f"candidates:\n\n{lines}"
                ),
            }
        return {"type": "text",
                "message": f"❌ No raw materials matching **{material}** found."}

    suppliers = res["suppliers"]
    sup_lines = "\n".join(
        f"- **{s['name']}** — supplies {s['product_count']} variant"
        f"{'s' if s['product_count'] != 1 else ''}"
        for s in suppliers[:10]
    ) or "_(no suppliers linked)_"

    best = suppliers[0] if suppliers else None
    rec = (f"\n\n💡 **Most efficient single source:** **{best['name']}** — "
           f"covers {best['product_count']} of {res['count']} variants.") if best else ""

    sub_block = ""
    if plan.get("wants_substitutes") and subs:
        sub_lines = "\n".join(
            f"- **{g['canonical_name']}** ({g['variant_count']} variants)"
            for g in subs[:6]
        )
        sub_block = f"\n\n**Substitute families:**\n{sub_lines}"

    return {
        "type": "text",
        "message": (
            f"📦 We have **{res['count']}** raw-material variants of "
            f"**{material}**, used by **{len(res['companies'])}** "
            f"compan{'ies' if len(res['companies']) != 1 else 'y'}.\n\n"
            f"**Suppliers ({len(suppliers)}):**\n{sup_lines}"
            f"{rec}{sub_block}"
        ),
    }


def _order_fulfillment_offline(message: str) -> Dict:
    return {
        "type": "text", 
        "message": "Order fulfillment and substitution reasoning requires the AI to be enabled."
    }

def _order_fulfillment_from_plan(message: str, plan: Dict) -> Dict:
    material = plan.get("material")
    req = plan.get("requested_amount")
    avail = plan.get("available_amount")

    if not material or req is None:
        return _llm_chat_response(message, plan)

    if avail is None:
        avail = 0
        
    try:
        req = float(req)
        avail = float(avail)
    except (ValueError, TypeError):
        return _llm_chat_response(message, plan)
        
    deficit = req - avail
    if deficit <= 0:
        return {
            "type": "text",
            "message": f"We have enough **{material}** to fulfill the request of {req}."
        }

    subs = consolidation.find_substitutes(material, limit=5)
    
    evidence = {
        "action": "order_fulfillment",
        "material": material,
        "requested": req,
        "available": avail,
        "deficit": deficit,
        "substitute_candidates": subs
    }

    if LLM_ENABLED:
        prompt = (f"The client requested {req} of {material}, but we only have {avail}. "
                  f"We need {deficit} more. Suggest a reliable substitute to fulfill the "
                  f"remaining {deficit}. "
                  f"Here are the viable database substitutes: {str(subs[:3])}. "
                  "Pick the most functionally equivalent substitute (e.g. matching 'ascorbic acid' with 'Vitamin C' and avoiding unrelated items) "
                  "and explain how it can be used to cover the deficit. Respond in clear, helpful natural language. DO NOT hallucinate specs.")
        text = chat_with_agnes(prompt, context=evidence)
        if text:
            return {"type": "text", "message": text, "data": evidence}

    if not subs:
        return {"type": "text", "message": f"Client requested **{req}** of **{material}**, but only **{avail}** is available. No viable substitutes found for the remaining **{deficit}**."}

    sub_lines = "\n".join(f"- **{s['canonical_name']}**" for s in subs[:3])
    msg = (f"Client requested **{req}** of **{material}**, but only **{avail}** is available.\n\n"
           f"To fulfill the remaining **{deficit}**, consider these viable substitutions:\n{sub_lines}")
    
    return {"type": "text", "message": msg, "data": evidence}


def _llm_chat_response(message: str, plan: Dict, history: Optional[List[Dict[str, str]]] = None) -> Dict:
    """Open-ended question routed to the LLM with the standard DB context."""
    if LLM_ENABLED:
        text = chat_with_agnes(message, context=_chat_context(message), history=history)
        if text:
            return {"type": "text", "message": text}
    return _unknown_response(message, history=history)


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
    "order_fulfillment": _order_fulfillment_offline,
    "unknown":        _unknown_response,
}


_ACTION_TO_INTENT = {
    "material_query":  "material_query",
    "dashboard":       "dashboard",
    "candidates":      "candidates",
    "product_detail":  "product_detail",
    "substitute":      "substitute",
    "recommend":       "recommend",
    "order_fulfillment": "order_fulfillment",
    "greeting":        "greeting",
    "help":            "help",
    "chat":            "unknown",
}


def _dispatch_plan(message: str, plan: Dict, history: Optional[List[Dict[str, str]]] = None) -> Dict:
    """Run the handler that matches the LLM's action plan."""
    action = plan.get("action", "chat")

    if action == "material_query":
        return _material_query_from_plan(message, plan)
    if action == "dashboard":
        return _dashboard_response()
    if action == "order_fulfillment":
        return _order_fulfillment_from_plan(message, plan)
    if action == "candidates":
        return _candidates_response(message)
    if action == "product_detail":
        ids = plan.get("product_ids") or _extract_numbers(message)
        if not ids:
            return {"type": "text",
                    "message": "Please specify a product ID, e.g. *\"product 200\"*"}
        return _product_response(f"product {ids[0]}")
    if action == "substitute":
        ids = plan.get("product_ids") or _extract_numbers(message)
        if len(ids) >= 2:
            mode = plan.get("mode", "strict")
            return _substitute_response(f"can {ids[0]} substitute {ids[1]} {mode}")
        return _substitute_response(message)
    if action == "recommend":
        ids = plan.get("product_ids") or _extract_numbers(message)
        mode = plan.get("mode", "strict")
        msg = f"recommend {ids[0]} {mode}" if ids else f"recommend {mode}"
        return _recommend_response(msg)
    if action == "greeting":
        return _greeting_response()
    if action == "help":
        return _help_response()
    return _llm_chat_response(message, plan, history=history)


def handle_chat(message: str, history: Optional[List[Dict[str, str]]] = None) -> Dict:
    """Process a user chat message and return a structured response.

    When the LLM is available it acts as the intent + entity extractor —
    no regex/stopword guessing. Regex remains as an offline fallback.
    """
    plan = understand_message(message, history=history) if LLM_ENABLED else None

    if plan:
        response = _dispatch_plan(message, plan, history=history)
        response["intent"] = _ACTION_TO_INTENT.get(plan.get("action", "chat"),
                                                   "unknown")
        response["plan"] = plan
    else:
        intent = _detect_intent(message)
        handler = _HANDLERS.get(intent, _unknown_response)
        
        if handler == _unknown_response:
            response = _unknown_response(message, history=history)
        else:
            response = handler(message)
        
        response["intent"] = intent

    response["llm_enabled"] = LLM_ENABLED
    return response

