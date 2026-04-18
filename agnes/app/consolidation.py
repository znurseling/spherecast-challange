"""
Step 1 of the Agnes pipeline: SQL-only consolidation signal.

For every raw material, count how many companies consume it and how many
suppliers offer it. This is the baseline signal — no AI, no hallucination
risk — that everything else refines.
"""
from collections import defaultdict
from typing import Dict, List
from .db import connection, schema, raw_type_matches


def load_all() -> Dict:
    s = schema()
    try:
        with connection() as c:
            products = {r[s["p_id"]]: dict(r) for r in c.execute("SELECT * FROM Product")}
            companies = {r[s["co_id"]]: dict(r) for r in c.execute("SELECT * FROM Company")}
            suppliers = {r[s["su_id"]]: dict(r) for r in c.execute("SELECT * FROM Supplier")}
            boms = [dict(r) for r in c.execute("SELECT * FROM BOM")]
            bcs = [dict(r) for r in c.execute("SELECT * FROM BOM_Component")]
            sps = [dict(r) for r in c.execute("SELECT * FROM Supplier_Product")]
    except Exception:
        # Fallback for missing tables
        products, companies, suppliers = {}, {}, {}
        boms, bcs, sps = [], [], []

    return {
        "s": s, "products": products, "companies": companies,
        "suppliers": suppliers, "boms": boms, "bcs": bcs, "sps": sps,
    }


def consolidation_candidates(limit: int = 50) -> List[Dict]:
    d = load_all()
    s, prods = d["s"], d["products"]

    # BOM -> company
    bom_company = {}
    for bom in d["boms"]:
        produced = prods.get(bom[s["bom_produced"]])
        if produced:
            bom_company[bom[s["bom_id"]]] = produced[s["p_company"]]

    consumers = defaultdict(set)
    finished_goods_using = defaultdict(set)
    for bc in d["bcs"]:
        cid = bom_company.get(bc[s["bc_bom"]])
        if cid is not None:
            consumers[bc[s["bc_consumed"]]].add(cid)
        # Track which finished-good BOMs use this raw material
        finished_goods_using[bc[s["bc_consumed"]]].add(bc[s["bc_bom"]])

    offerers = defaultdict(set)
    for sp in d["sps"]:
        offerers[sp[s["sp_product"]]].add(sp[s["sp_supplier"]])

    out: List[Dict] = []
    for pid, p in prods.items():
        if not raw_type_matches(p.get(s["p_type"])):
            continue
        n_c, n_s = len(consumers[pid]), len(offerers[pid])
        if n_c == 0 and n_s == 0:
            continue
        # "fragmentation" score: high when many companies buy from many
        # suppliers -> biggest consolidation upside
        score = n_c * n_s
        out.append({
            "product_id": pid,
            "sku": p.get(s["p_sku"]),
            "n_companies": n_c,
            "n_suppliers": n_s,
            "n_boms": len(finished_goods_using[pid]),
            "fragmentation_score": score,
            "company_ids": sorted(consumers[pid]),
            "supplier_ids": sorted(offerers[pid]),
        })

    out.sort(key=lambda r: (r["fragmentation_score"], r["n_companies"]),
             reverse=True)
    return out[:limit]


def product_detail(product_id: int) -> Dict:
    d = load_all()
    s, prods = d["s"], d["products"]
    p = prods.get(product_id)
    if not p:
        return None

    suppliers = []
    for sp in d["sps"]:
        if sp[s["sp_product"]] == product_id:
            sup = d["suppliers"].get(sp[s["sp_supplier"]])
            if sup:
                suppliers.append({"id": sup[s["su_id"]], "name": sup[s["su_name"]]})

    # Which BOMs consume this, and therefore which companies
    consuming_boms = [bc[s["bc_bom"]] for bc in d["bcs"]
                      if bc[s["bc_consumed"]] == product_id]
    company_ids = set()
    for bom in d["boms"]:
        if bom[s["bom_id"]] in consuming_boms:
            produced = prods.get(bom[s["bom_produced"]])
            if produced:
                company_ids.add(produced[s["p_company"]])
    companies = [{"id": cid, "name": d["companies"][cid][s["co_name"]]}
                 for cid in company_ids if cid in d["companies"]]

    return {
        "id": product_id,
        "sku": p.get(s["p_sku"]),
        "type": p.get(s["p_type"]),
        "suppliers": suppliers,
        "consumed_by_companies": companies,
        "consuming_bom_count": len(consuming_boms),
    }


def search_by_material(keyword: str) -> Dict:
    """Find raw-material products whose SKU contains `keyword`.
    Returns counts plus the suppliers offering them."""
    d = load_all()
    s, prods = d["s"], d["products"]
    kw = keyword.lower().strip()
    if not kw:
        return {"keyword": keyword, "count": 0, "products": [], "suppliers": []}

    matches = []
    for pid, p in prods.items():
        sku = (p.get(s["p_sku"]) or "")
        if not raw_type_matches(p.get(s["p_type"])):
            continue
        if kw in sku.lower():
            matches.append({"id": pid, "sku": sku})

    match_ids = {m["id"] for m in matches}

    supplier_names = {}
    supplier_to_products = defaultdict(list)
    for sp in d["sps"]:
        if sp[s["sp_product"]] in match_ids:
            sup = d["suppliers"].get(sp[s["sp_supplier"]])
            if sup:
                sid = sup[s["su_id"]]
                supplier_names[sid] = sup[s["su_name"]]
                supplier_to_products[sid].append(sp[s["sp_product"]])

    bom_company = {}
    for bom in d["boms"]:
        produced = prods.get(bom[s["bom_produced"]])
        if produced:
            bom_company[bom[s["bom_id"]]] = produced[s["p_company"]]

    company_ids = set()
    for bc in d["bcs"]:
        if bc[s["bc_consumed"]] in match_ids:
            cid = bom_company.get(bc[s["bc_bom"]])
            if cid is not None:
                company_ids.add(cid)

    companies = [{"id": cid, "name": d["companies"][cid][s["co_name"]]}
                 for cid in company_ids if cid in d["companies"]]

    suppliers = [{"id": sid, "name": name,
                  "product_count": len(set(supplier_to_products[sid]))}
                 for sid, name in supplier_names.items()]
    suppliers.sort(key=lambda r: r["product_count"], reverse=True)

    return {
        "keyword": keyword,
        "count": len(matches),
        "products": matches,
        "suppliers": suppliers,
        "companies": companies,
    }


def portfolio_summary() -> Dict:
    """Numbers for the 'current state vs Agnes state' dashboard."""
    cands = consolidation_candidates(limit=10_000)
    total_raw = len(cands)
    total_supplier_links = sum(c["n_suppliers"] for c in cands)
    fragmented = [c for c in cands if c["n_suppliers"] > 1]
    # Agnes target: one preferred supplier per raw material cluster
    agnes_links = total_raw  # one per raw material
    return {
        "raw_materials": total_raw,
        "current_supplier_relationships": total_supplier_links,
        "agnes_consolidated_relationships": agnes_links,
        "reduction_pct": round(
            100 * (1 - agnes_links / total_supplier_links), 1
        ) if total_supplier_links else 0,
        "fragmented_materials": len(fragmented),
    }
