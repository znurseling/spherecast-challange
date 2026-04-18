"""
Recommendation engine.

Given a raw-material product id, Agnes proposes a consolidated sourcing
plan: which supplier to consolidate under, which currently-separate
purchases would roll into it, evidence, and tradeoffs.

Deliberately NOT a real MILP optimizer — hackathon-appropriate scoring
that is easy to explain to judges.
"""
from collections import Counter, defaultdict
from typing import Dict, List, Optional
from .consolidation import load_all, consolidation_candidates
from .db import schema, raw_type_matches
from .normalizer import normalize
from .llm import assess_substitution


def _group_similar_raw_materials() -> Dict[str, List[int]]:
    """
    Cluster raw-material product_ids by canonical name.
    This is the 'substitution graph' in its simplest possible form.
    """
    d = load_all()
    s, prods = d["s"], d["products"]
    groups: Dict[str, List[int]] = defaultdict(list)
    for pid, p in prods.items():
        if not raw_type_matches(p.get(s["p_type"])):
            continue
        canon = normalize(p.get(s["p_sku"]))["canonical_name"]
        groups[canon.lower()].append(pid)
    return groups


def recommend_for_product(product_id: int, mode: str = "strict") -> Dict:
    d = load_all()
    s, prods = d["s"], d["products"]
    target = prods.get(product_id)
    if not target:
        return {"error": f"product {product_id} not found"}

    target_canon = normalize(target[s["p_sku"]])["canonical_name"]

    # Find all products in the same canonical group
    groups = _group_similar_raw_materials()
    siblings = [pid for pid in groups.get(target_canon.lower(), [])
                if pid != product_id]

    # Current state: which suppliers exist for target + siblings
    sp_by_product = defaultdict(set)
    for sp in d["sps"]:
        sp_by_product[sp[s["sp_product"]]].add(sp[s["sp_supplier"]])

    all_products_in_cluster = [product_id] + siblings
    supplier_votes = Counter()
    for pid in all_products_in_cluster:
        for sup_id in sp_by_product[pid]:
            supplier_votes[sup_id] += 1

    if not supplier_votes:
        return {
            "product_id": product_id,
            "canonical_name": target_canon,
            "recommendation": None,
            "reasoning": "No suppliers currently offer this or sibling products.",
            "evidence": [],
        }

    # Pick the supplier that covers the most of the cluster — fewer new
    # supplier relationships needed to consolidate.
    best_supplier_id, coverage = supplier_votes.most_common(1)[0]
    best_supplier = d["suppliers"][best_supplier_id][s["su_name"]]

    # Build the substitution assessments for each sibling to justify
    # folding them under the chosen supplier.
    assessments = []
    target_info = {
        "product_id": product_id,
        "sku": target[s["p_sku"]],
        "canonical_name": target_canon,
        "supplier_ids": list(sp_by_product[product_id]),
    }
    for sib_pid in siblings[:5]:  # cap to keep LLM calls bounded
        sib = prods[sib_pid]
        sib_info = {
            "product_id": sib_pid,
            "sku": sib[s["p_sku"]],
            "canonical_name": normalize(sib[s["p_sku"]])["canonical_name"],
            "supplier_ids": list(sp_by_product[sib_pid]),
        }
        a = assess_substitution(target_info, sib_info, mode=mode)
        assessments.append({
            "candidate_product_id": sib_pid,
            "candidate_sku": sib[s["p_sku"]],
            **a,
        })

    approved = [a for a in assessments if a["verdict"] == "accept"]
    review  = [a for a in assessments if a["verdict"] == "review"]

    # Tradeoffs are surfaced explicitly — judges asked for this.
    tradeoffs = []
    if coverage < len(all_products_in_cluster):
        tradeoffs.append(
            f"Chosen supplier currently offers {coverage}/"
            f"{len(all_products_in_cluster)} cluster members. New supplier "
            "relationship(s) needed to cover the rest."
        )
    if mode == "creative":
        tradeoffs.append(
            "Creative mode: functional-equivalent substitutes flagged; "
            "requires R&D sign-off before production swap."
        )
    if not approved and review:
        tradeoffs.append(
            f"{len(review)} candidate(s) need manual review — not enough "
            "automatic evidence to approve."
        )

    evidence = [
        {"source": "DB: Product + BOM_Component",
         "detail": f"{len(all_products_in_cluster)} products share canonical "
                   f"name '{target_canon}'"},
        {"source": "DB: Supplier_Product",
         "detail": f"Supplier '{best_supplier}' covers {coverage} of "
                   f"{len(all_products_in_cluster)} cluster members"},
    ]

    return {
        "product_id": product_id,
        "canonical_name": target_canon,
        "mode": mode,
        "recommendation": {
            "consolidate_under_supplier_id": best_supplier_id,
            "consolidate_under_supplier_name": best_supplier,
            "cluster_size": len(all_products_in_cluster),
            "current_supplier_count": len(
                {s for pid in all_products_in_cluster for s in sp_by_product[pid]}
            ),
        },
        "substitution_assessments": assessments,
        "approved_count": len(approved),
        "review_count": len(review),
        "tradeoffs": tradeoffs,
        "evidence": evidence,
    }


def top_recommendations(limit: int = 5, mode: str = "strict") -> List[Dict]:
    cands = consolidation_candidates(limit=limit * 3)
    # Prioritize candidates that are fragmented across companies AND suppliers
    top = [c for c in cands if c["n_suppliers"] > 1][:limit]
    return [recommend_for_product(c["product_id"], mode=mode) for c in top]
