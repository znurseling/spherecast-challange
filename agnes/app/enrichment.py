from typing import List, Dict, Optional
import json
import re
from duckduckgo_search import DDGS
from .db import get_external_evidence, save_external_evidence
from . import llm

def enrich_product_data(product_id: int, supplier_name: str, canonical_name: str) -> List[Dict]:
    """
    Checks the database for cached external evidence. If not found, performs a web search
    using DuckDuckGo to find compliance and specification data, extracts facts using the LLM,
    and caches the results.
    """
    # 1. Check Cache
    try:
        cached = get_external_evidence(product_id)
        if cached:
            return cached
    except:
        pass

    # 2. Perform Web Search
    query = f"{supplier_name} {canonical_name} specification sheet compliance FDA"
    snippets = []
    try:
        results = DDGS().text(query, max_results=3)
        for r in results:
            snippets.append({
                "url": r.get("href", ""),
                "title": r.get("title", ""),
                "body": r.get("body", "")
            })
    except Exception as e:
        print(f"Web search failed: {e}")
        return []

    if not snippets:
        return []

    # 3. Extract Facts using LLM
    evidence_found = []
    
    # We will process each snippet to find compliance facts
    for snip in snippets:
        prompt = (
            f"You are a compliance fact extractor. Read the following web search snippet "
            f"for a raw material ({canonical_name}) supplied by {supplier_name}.\n\n"
            f"Snippet Title: {snip['title']}\n"
            f"Snippet Body: {snip['body']}\n\n"
            f"Extract any concrete compliance facts (e.g. FDA approved, Kosher, Halal, ISO certified, "
            f"organic, purity percentage). If no relevant compliance facts are found, return an empty JSON object.\n"
            f"Return ONLY a JSON object in this format:\n"
            f'{{"fact_snippet": "...", "compliance_tags": "Kosher, Halal"}}'
        )
        
        try:
            resp = llm._model.generate_content(prompt)
            text = resp.text.strip()
            text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
            if not text or text == "{}":
                continue
                
            data = json.loads(text)
            if "fact_snippet" in data and data["fact_snippet"]:
                fact = data["fact_snippet"]
                tags = data.get("compliance_tags", "")
                
                # 4. Save to Cache
                save_external_evidence(
                    product_id=product_id,
                    supplier_name=supplier_name,
                    canonical_name=canonical_name,
                    query=query,
                    url=snip["url"],
                    snippet=fact,
                    tags=tags
                )
                
                evidence_found.append({
                    "SourceURL": snip["url"],
                    "FactSnippet": fact,
                    "ComplianceTags": tags
                })
        except Exception as e:
            print(f"LLM extraction failed: {e}")
            continue
            
    return evidence_found
