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
except Exception:
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

Preliminary DB evidence:
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

def chat_with_agnes(message: str) -> str:
    """Fallback conversational chat when no structured intent matches."""
    if not _model:
        return ""
    prompt = (
        "You are Agnes, a highly intelligent AI Supply Chain Manager. "
        "A user just said: " + message + "\n\n"
        "Reply conversationally and concisely."
    )
    try:
        resp = _model.generate_content(prompt)
        return resp.text.strip()
    except Exception:
        return ""
