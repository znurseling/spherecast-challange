"""
Thin Google Gemini client with a deterministic MOCK fallback.

Why mock? Two reasons:
  1. Judges may run this without an API key.
  2. During dev you don't want to burn tokens on every reload.

Every public function returns a dict with an `evidence` list so downstream
endpoints always have a provenance trail — even when mocked.
"""
import json
import re
from typing import Dict, List, Optional
from .config import GOOGLE_API_KEY, LLM_MODEL, LLM_ENABLED

try:
    import google.generativeai as genai
    if LLM_ENABLED:
        genai.configure(api_key=GOOGLE_API_KEY)
        _model = genai.GenerativeModel(LLM_MODEL)
    else:
        _model = None
except Exception as e:
    print(f"LLM Initialization Error: {e}")
    _model = None


_NORM_RE = re.compile(r"[^a-zA-Z]+")


def _mock_canonical(sku: str) -> str:
    """
    Heuristic canonicaliser used when no LLM is available.
    SKUs in the provided DB look like 'RM-C2-ascorbic-acid-4823fabf'.
    Strip prefixes, suffix hashes, and tidy up.
    """
    # SKUs look like 'RM-C2-ascorbic-acid-71ab' or 'RM-C1-...-4823fabf'
    # Strip: prefix codes (RM, C\d+), trailing hash-like alphanum, and
    # trailing short hex tokens.
    parts = str(sku).split("-")
    keep = []
    for i, p in enumerate(parts):
        if re.fullmatch(r"RM|C\d+|raw|material", p, re.IGNORECASE):
            continue
        # last token that looks like a hash (mix of letters+digits, short)
        if (i == len(parts) - 1
                and re.fullmatch(r"[0-9a-f]{3,}", p, re.IGNORECASE)
                and any(ch.isdigit() for ch in p)):
            continue
        if p:
            keep.append(p.replace("_", " "))
    txt = " ".join(keep).strip()
    return txt.title() if txt else str(sku)


def canonicalize(sku: str) -> Dict:
    """Normalize a messy SKU to a canonical ingredient name."""
    mock = _mock_canonical(sku)
    if not _model:
        return {
            "canonical_name": mock,
            "confidence": 0.6,
            "evidence": [{"source": "rule-based heuristic", "detail": "mock mode"}],
        }

    prompt = (
        "You normalize messy procurement SKUs into canonical ingredient names.\n"
        f"SKU: {sku}\n"
        "Return ONLY a JSON object: "
        '{"canonical_name": "...", "confidence": 0.0-1.0, "reasoning": "..."}'
    )
    try:
        resp = _model.generate_content(prompt)
        text = resp.text.strip()
        # strip ``` fences if present
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
        data = json.loads(text)
        return {
            "canonical_name": data.get("canonical_name", mock),
            "confidence": float(data.get("confidence", 0.7)),
            "evidence": [{
                "source": f"LLM ({LLM_MODEL})",
                "detail": data.get("reasoning", "")[:300],
            }],
        }
    except Exception as e:
        return {
            "canonical_name": mock,
            "confidence": 0.5,
            "evidence": [{"source": "fallback", "detail": f"LLM error: {e}"}],
        }


def assess_substitution(
    a: Dict, b: Dict, mode: str = "strict", context: Optional[Dict] = None
) -> Dict:
    """
    Can raw material B replace raw material A?
    Returns {verdict, confidence, reasoning, evidence[]}.
    """
    ctx = context or {}
    shared_suppliers = set(a.get("supplier_ids", [])) & set(b.get("supplier_ids", []))
    a_canon = a.get("canonical_name", a.get("sku", "?"))
    b_canon = b.get("canonical_name", b.get("sku", "?"))
    name_match = a_canon.lower().strip() == b_canon.lower().strip()

    # --- mock logic, also used to SEED the LLM prompt ---
    if name_match:
        mock_verdict = "accept"
        mock_conf = 0.9 if mode == "strict" else 0.95
        mock_reason = "Canonical names match; same ingredient."
    elif shared_suppliers and mode == "creative":
        mock_verdict = "review"
        mock_conf = 0.55
        mock_reason = (f"Different ingredients but share {len(shared_suppliers)} "
                       "supplier(s) — likely functionally related.")
    elif mode == "strict":
        mock_verdict = "reject"
        mock_conf = 0.8
        mock_reason = "Strict mode requires canonical-name identity."
    else:
        mock_verdict = "review"
        mock_conf = 0.4
        mock_reason = "Insufficient evidence for automatic substitution."

    evidence = [
        {"source": "DB: canonical name comparison",
         "detail": f"{a_canon}  ≟  {b_canon}  →  {'match' if name_match else 'differ'}"},
        {"source": "DB: Supplier_Product",
         "detail": f"{len(shared_suppliers)} shared supplier(s)"},
    ]

    from .enrichment import enrich_product_data
    
    # Try to enrich data with web search
    a_external = enrich_product_data(a.get("product_id"), "Supplier", a_canon)
    b_external = enrich_product_data(b.get("product_id"), "Supplier", b_canon)
    
    for ev in a_external:
        evidence.append({
            "source": f"External Web (Material A)",
            "detail": f"{ev['ComplianceTags']} - {ev['FactSnippet']} (URL: {ev['SourceURL']})"
        })
    for ev in b_external:
        evidence.append({
            "source": f"External Web (Material B)",
            "detail": f"{ev['ComplianceTags']} - {ev['FactSnippet']} (URL: {ev['SourceURL']})"
        })

    if not _model:
        return {
            "verdict": mock_verdict, "confidence": mock_conf,
            "reasoning": mock_reason, "evidence": evidence, "mode": mode,
        }

    prompt = f"""You are Agnes, an AI supply-chain manager. Decide whether raw material B
can substitute raw material A in a CPG bill of materials.

Mode: {mode}
  - strict:   only approve 1:1 canonical-identity matches
  - creative: also approve functional equivalents (e.g. different thickeners)

Material A: {json.dumps(a)[:800]}
Material B: {json.dumps(b)[:800]}
Context:    {json.dumps(ctx)[:400]}

Preliminary DB & External Evidence:
{json.dumps(evidence, indent=2)}

Respond with ONLY a JSON object:
{{"verdict": "accept"|"review"|"reject",
  "confidence": 0.0-1.0,
  "reasoning": "...",
  "risks": ["..."]}}
Do not invent certifications or specs you cannot ground in the provided data."""

    try:
        resp = _model.generate_content(prompt)
        text = resp.text.strip()
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
        data = json.loads(text)
        evidence.append({
            "source": f"LLM reasoning ({LLM_MODEL})",
            "detail": data.get("reasoning", "")[:400],
        })
        for risk in data.get("risks", [])[:3]:
            evidence.append({"source": "LLM risk flag", "detail": str(risk)[:200]})
        return {
            "verdict": data.get("verdict", mock_verdict),
            "confidence": float(data.get("confidence", mock_conf)),
            "reasoning": data.get("reasoning", mock_reason),
            "evidence": evidence,
            "mode": mode,
        }
    except Exception as e:
        evidence.append({"source": "fallback", "detail": f"LLM error: {e}"})
        return {
            "verdict": mock_verdict, "confidence": mock_conf,
            "reasoning": mock_reason, "evidence": evidence, "mode": mode,
        }

def _parse_history(history: Optional[List[Dict[str, str]]] = None) -> List[Dict]:
    """Convert Agnes history format to Gemini history format."""
    if not history:
        return []
    gemini_history = []
    for msg in history:
        role = "user" if msg.get("role") == "user" else "model"
        gemini_history.append({"role": role, "parts": [msg.get("content", "")]})
    return gemini_history


def understand_message(message: str, history: Optional[List[Dict[str, str]]] = None) -> Optional[Dict]:
    """Ask the LLM to parse a user message into a structured action plan.
    Uses chat history for context-aware intent detection."""
    if not _model:
        return None

    gemini_history = _parse_history(history)
    chat = _model.start_chat(history=gemini_history)

    prompt = f"""You are the intent router for Agnes, an AI supply-chain assistant.
Parse the user message into a JSON action plan. Pick the single best action.

Actions:
- "material_query": user asks about a specific raw material — how much we have,
  who supplies it, who buys it, substitutes, most-efficient sourcing, etc.
- "dashboard": user wants the portfolio overview.
- "candidates": user wants consolidation candidates.
- "product_detail": user references a product by numeric ID.
- "substitute": user asks whether product X can replace product Y
  (needs two product IDs).
- "recommend": user wants a sourcing recommendation for a product/ID.
- "order_fulfillment": user wants to deliver or supply a specific amount of a product.
- "send_email": user wants to send an email to a supplier, customer, or distributor.
- "check_inbox": user wants to check their latest emails or see if a supplier has replied.
- "greeting" / "help" / "chat": small talk or open-ended.

For material_query, extract:
  material          = the canonical ingredient name the user is asking about,
                      lowercase, singular. Normalize spellings. Null if no material mentioned.
  wants_count       = true if they asked quantity / how many / how much / stock.
  wants_suppliers   = true if they asked which supplier / where to buy / who offers.
  wants_companies   = true if they asked which company consumes / buys / uses it.
  wants_substitutes = true if they asked for alternatives / substitutes / swap.
  wants_efficient   = true if they asked for "most efficient" / "best" / "single supplier".

For order_fulfillment, extract:
  material          = the canonical ingredient name requested.
  requested_amount  = the numeric amount the client requested (null if not found).
  available_amount  = the numeric amount we currently have (null if not found).

For send_email, extract:
  recipient         = email address of the recipient. DEFAULT to suppliercompany260@gmail.com if it's for a supplier.
  subject           = subject line for the email.
  body              = text content of the email.

Also extract product_ids (array of integers mentioned) and mode (strict|creative, default strict).

Respond with ONLY the JSON object — no prose, no code fences.

User message: {message}
"""

    try:
        resp = chat.send_message(prompt)
        text = resp.text.strip()
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
        data = json.loads(text)
        data.setdefault("action", "chat")
        data.setdefault("material", None)
        data.setdefault("requested_amount", None)
        data.setdefault("available_amount", None)
        data.setdefault("product_ids", [])
        for flag in ("wants_count", "wants_suppliers", "wants_companies",
                     "wants_substitutes", "wants_efficient"):
            data.setdefault(flag, False)
        data.setdefault("mode", "strict")
        return data
    except Exception:
        return None


def chat_with_agnes(message: str, context: Optional[Dict] = None, history: Optional[List[Dict[str, str]]] = None) -> str:
    """Fallback conversational chat with optional DB-backed context and full history."""
    if not _model:
        print("LLM Chat: No model initialized.")
        return ""
    
    ctx = context or {}
    gemini_history = _parse_history(history)
    chat = _model.start_chat(history=gemini_history)

    prompt = (
        "You are Agnes, a highly intelligent AI Supply Chain Manager.\n"
        "You are embedded in an application that can access its SQLite procurement "
        "database through the backend.\n"
        "Use the provided database context when answering.\n"
        "Reply conversationally and ground claims in the provided context.\n\n"
        "CRITICAL RULES:\n"
        "1. DO NOT suggest raw SQL queries to the user.\n"
        "2. DO NOT give technical advice about data points or database structure.\n"
        "3. DO NOT use phrases like 'feel free to ask for a different data point'.\n"
        "4. Focus entirely on supply chain insights, risks, and recommendations.\n"
        "5. If market price data ('market_price') is present in the context, use it to provide cost insights or compare with current sourcing.\n"
        "6. IMPORTANT: All suppliers share the same contact email: suppliercompany260@gmail.com. Use this address internally for the 'send_email' intent, but NEVER mention the raw email address directly to the user in the chat text. Just refer to them as 'the supplier'.\n"
        "7. DECISIVENESS: When comparing suppliers or options, you MUST always make a definitive choice. If you recommend a specific material, you MUST explicitly state the NAME of the supplier who provides that material as shown in the database. Never just recommend a material without naming the associated supplier from the context.\n"
        "8. PROACTIVE ACTION: After providing any analysis or recommendation, ALWAYS ask the user if they would like you to contact the supplier to take action and 'get the job done'.\n"
        "9. If the user asks you to send an email or contact someone, you have the capability to do so. You should confirm the details (recipient, subject, body) and then the system will handle the 'send_email' intent.\n"
        "10. If you cannot answer based on context, simply state what is missing without suggesting technical queries.\n\n"
        f"Database context:\n{json.dumps(ctx, indent=2)[:4000]}\n\n"
        f"User message: {message}\n"
    )
    try:
        resp = chat.send_message(prompt)
        return resp.text.strip()
    except Exception as e:
        print(f"LLM Chat Runtime Error: {e}")
        return ""
