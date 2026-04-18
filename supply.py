"""
Spherecast hackathon - starter script (robust version).

This version auto-detects column names so it works regardless of
whether the DB uses BOMid / BOMId / bom_id etc.

Run:  python3 supply.py
"""

import sqlite3
from collections import defaultdict

DB_PATH = "agnes/db.sqlite"


# ---------- helpers to find columns by fuzzy match ----------

def cols(conn, table):
    """Return list of actual column names for a table."""
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def find(col_list, *needles):
    """
    Find a column whose name contains all the given substrings
    (case-insensitive). Raises if not found.
    Example: find(cols, "bom", "id") -> matches 'BOMid' or 'BOMId' or 'bom_id'
    """
    for c in col_list:
        low = c.lower()
        if all(n.lower() in low for n in needles):
            return c
    raise KeyError(f"no column matching {needles} in {col_list}")


# ---------- 1. Inspect schema ----------

def inspect_schema(conn):
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )]
    for t in tables:
        print(f"\n=== {t} ===")
        for r in conn.execute(f"PRAGMA table_info({t})"):
            print(f"  {r[1]:25s} {r[2]}")
        n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  ({n} rows)")


# ---------- 2. Load + detect column names ----------

def load(conn):
    conn.row_factory = sqlite3.Row

    # Detect column names once
    product_cols = cols(conn, "Product")
    bom_cols = cols(conn, "BOM")
    bc_cols = cols(conn, "BOM_Component")
    sp_cols = cols(conn, "Supplier_Product")

    col = {
        "p_id":         find(product_cols, "id"),
        "p_sku":        find(product_cols, "sku"),
        "p_company":    find(product_cols, "company"),
        "p_type":       find(product_cols, "type"),
        "bom_id":       find(bom_cols, "id"),
        "bom_produced": find(bom_cols, "produced"),
        "bc_bom":       find(bc_cols, "bom"),
        "bc_consumed":  find(bc_cols, "consumed"),
        "sp_supplier":  find(sp_cols, "supplier"),
        "sp_product":   find(sp_cols, "product"),
    }

    print("\nDetected columns:")
    for k, v in col.items():
        print(f"  {k:15s} -> {v}")

    products = {r[col["p_id"]]: dict(r) for r in conn.execute("SELECT * FROM Product")}
    boms = [dict(r) for r in conn.execute("SELECT * FROM BOM")]
    bcs = [dict(r) for r in conn.execute("SELECT * FROM BOM_Component")]
    sps = [dict(r) for r in conn.execute("SELECT * FROM Supplier_Product")]

    return {"col": col, "products": products, "boms": boms,
            "bcs": bcs, "sps": sps}


# ---------- 3. Consolidation candidates ----------

def consolidation_candidates(data):
    col = data["col"]
    products = data["products"]

    bom_to_company = {}
    for bom in data["boms"]:
        produced = products.get(bom[col["bom_produced"]])
        if produced:
            bom_to_company[bom[col["bom_id"]]] = produced[col["p_company"]]

    consumers = defaultdict(set)   # raw_material_id -> {company_ids}
    for bc in data["bcs"]:
        cid = bom_to_company.get(bc[col["bc_bom"]])
        if cid is not None:
            consumers[bc[col["bc_consumed"]]].add(cid)

    offerers = defaultdict(set)    # product_id -> {supplier_ids}
    for sp in data["sps"]:
        offerers[sp[col["sp_product"]]].add(sp[col["sp_supplier"]])

    results = []
    for pid, p in products.items():
        if str(p.get(col["p_type"])).lower() not in ("raw-material", "raw_material", "rawmaterial"):
            continue
        results.append({
            "id": pid,
            "sku": p.get(col["p_sku"]),
            "n_companies": len(consumers[pid]),
            "n_suppliers": len(offerers[pid]),
        })

    results.sort(key=lambda r: (r["n_companies"], r["n_suppliers"]), reverse=True)
    return results


# ---------- 4. Main ----------

def main():
    conn = sqlite3.connect(DB_PATH)

    print("### SCHEMA ###")
    inspect_schema(conn)

    data = load(conn)

    print(f"\n{len(data['products'])} products total")

    print("\n### TOP 20 CONSOLIDATION CANDIDATES ###\n")
    cands = consolidation_candidates(data)
    for c in cands[:20]:
        print(f"  [{c['id']:>5}] {str(c['sku'])[:35]:<35}  "
              f"companies={c['n_companies']}  suppliers={c['n_suppliers']}")


if __name__ == "__main__":
    main()
