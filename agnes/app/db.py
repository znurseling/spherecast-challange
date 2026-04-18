"""
SQLite access layer.

Uses the same auto-detect trick as the starter script so the code works
regardless of whether the provided DB uses BOMid / BOMId / bom_id.
Detection runs once at startup and is cached.
"""
import sqlite3
from contextlib import contextmanager
from functools import lru_cache
from typing import Dict, List
from .config import DB_PATH


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


@contextmanager
def connection():
    c = _conn()
    try:
        yield c
    finally:
        c.close()

def init_db():
    q = """
    CREATE TABLE IF NOT EXISTS ExternalEvidence (
        Id INTEGER PRIMARY KEY AUTOINCREMENT,
        ProductId INTEGER,
        SupplierName TEXT,
        CanonicalName TEXT,
        SearchQuery TEXT,
        SourceURL TEXT,
        FactSnippet TEXT,
        ComplianceTags TEXT
    )
    """
    with connection() as c:
        c.execute(q)
        c.commit()

def save_external_evidence(product_id: int, supplier_name: str, canonical_name: str, query: str, url: str, snippet: str, tags: str):
    q = "INSERT INTO ExternalEvidence (ProductId, SupplierName, CanonicalName, SearchQuery, SourceURL, FactSnippet, ComplianceTags) VALUES (?, ?, ?, ?, ?, ?, ?)"
    with connection() as c:
        c.execute(q, (product_id, supplier_name, canonical_name, query, url, snippet, tags))
        c.commit()

def get_external_evidence(product_id: int) -> List[Dict]:
    q = "SELECT SourceURL, FactSnippet, ComplianceTags FROM ExternalEvidence WHERE ProductId = ?"
    with connection() as c:
        rows = c.execute(q, (product_id,)).fetchall()
    return [dict(r) for r in rows]


def _cols(conn, table: str) -> List[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def _find(cols: List[str], *needles: str) -> str:
    for c in cols:
        low = c.lower()
        if all(n.lower() in low for n in needles):
            return c
    raise KeyError(f"no column matching {needles} in {cols}")


@lru_cache(maxsize=1)
def schema() -> Dict[str, str]:
    """Detect actual column names once. Cached for the process lifetime."""
    try:
        with connection() as c:
            p = _cols(c, "Product")
            b = _cols(c, "BOM")
            bc = _cols(c, "BOM_Component")
            sp = _cols(c, "Supplier_Product")
            co = _cols(c, "Company")
            su = _cols(c, "Supplier")

        return {
            "p_id":         _find(p, "id"),
            "p_sku":        _find(p, "sku"),
            "p_company":    _find(p, "company"),
            "p_type":       _find(p, "type"),
            "bom_id":       _find(b, "id"),
            "bom_produced": _find(b, "produced"),
            "bc_bom":       _find(bc, "bom"),
            "bc_consumed":  _find(bc, "consumed"),
            "sp_supplier": _find(sp, "supplier"),
            "sp_product":  _find(sp, "product"),
            "co_id":        _find(co, "id"),
            "co_name":      _find(co, "name"),
            "su_id":        _find(su, "id"),
            "su_name":      _find(su, "name"),
        }
    except Exception:
        # Return dummy schema if DB is missing/empty so app doesn't crash on init
        return {
            "p_id": "Id", "p_sku": "SKU", "p_company": "CompanyId", "p_type": "Type",
            "bom_id": "Id", "bom_produced": "ProducedProductId",
            "bc_bom": "BOMid", "bc_consumed": "ConsumedProductId",
            "sp_supplier": "SupplierId", "sp_product": "ProductId",
            "co_id": "Id", "co_name": "Name",
            "su_id": "Id", "su_name": "Name"
        }


def raw_type_matches(v: str) -> bool:
    return str(v).lower().replace("_", "-") in ("raw-material", "rawmaterial")

LOW_STOCK_THRESHOLD = 200  # items at/below this are flagged as deficit


def get_supplier_inventory() -> List[Dict]:
    s = schema()
    # Fetch all products with quality + stock metrics via LEFT JOINs
    q = f"""
        SELECT
            su.{s["su_name"]} AS supplier_name,
            su.{s["su_id"]} AS supplier_id,
            p.{s["p_sku"]} AS original_sku,
            p.{s["p_type"]} AS type,
            p.{s["p_id"]} AS product_id,
            c.supplier_count,
            pq.PurityPercentage,
            pq.Grade,
            pq.Certifications,
            pq.LabTestStatus,
            spr.QualityAuditScore,
            spr.SustainabilityRating,
            sic.InventoryLevel AS stock_quantity
        FROM Supplier su
        JOIN Supplier_Product sp ON su.{s["su_id"]} = sp.{s["sp_supplier"]}
        JOIN Product p ON p.{s["p_id"]} = sp.{s["sp_product"]}
        JOIN (
            SELECT {s["sp_product"]}, COUNT({s["sp_supplier"]}) as supplier_count
            FROM Supplier_Product
            GROUP BY {s["sp_product"]}
        ) c ON c.{s["sp_product"]} = p.{s["p_id"]}
        LEFT JOIN ProductQualitySpecs pq
            ON pq.SupplierId = su.{s["su_id"]} AND pq.ProductId = p.{s["p_id"]}
        LEFT JOIN SupplierPerformance spr
            ON spr.SupplierId = su.{s["su_id"]}
        LEFT JOIN SupplierInventoryCost sic
            ON sic.SupplierId = su.{s["su_id"]} AND sic.ProductId = p.{s["p_id"]}
        ORDER BY su.{s["su_name"]}, p.{s["p_sku"]}
    """
    with connection() as c:
        try:
            rows = c.execute(q).fetchall()
        except sqlite3.OperationalError:
            rows = []
        
    # Fetch all available market prices to map them
    with connection() as c:
        try:
            price_rows = c.execute("SELECT material_name, price_per_kg, min_price, max_price FROM market_prices").fetchall()
        except sqlite3.OperationalError:
            price_rows = []
    # Sort by length descending to match more specific names first (e.g., 'magnesium stearate' before 'magnesium')
    sorted_rows = sorted(price_rows, key=lambda r: len(r["material_name"]), reverse=True)
    price_map = {r["material_name"].lower(): r for r in sorted_rows}

    inventory_map = {}
    
    for r in rows:
        sup = r["supplier_name"]
        if sup not in inventory_map:
            inventory_map[sup] = {"supplier_name": sup, "materials": []}
            
        sku = r["original_sku"]
        parts = sku.split("-")
        # Extract middle parts: RM-C57-vegetable-magnesium-stearate-006c7e32 -> vegetable-magnesium-stearate
        if len(parts) > 3:
            clean_name = "-".join(parts[2:-1])
        else:
            clean_name = sku
            
        hex_id = parts[-1] if parts else sku
        
        # Try to find a matching price by checking if any material_name is in the SKU
        m_price = None
        clean_sku_for_match = sku.lower().replace("-", " ")
        for m_name, p_data in price_map.items():
            if m_name in clean_sku_for_match:
                m_price = p_data
                break
        
        # Fallback: Generate a consistent estimate if no market data exists
        if m_price:
            avg_p = m_price["price_per_kg"]
            min_p = m_price["min_price"]
            max_p = m_price["max_price"]
            is_estimate = False
        else:
            # Deterministic pseudo-random price based on SKU hash
            import hashlib
            h = int(hashlib.md5(sku.encode()).hexdigest(), 16)
            if r["type"].lower() == "finished-good" or "fg" in sku.lower():
                avg_p = 5.0 + (h % 450) / 10.0 # $5 - $50
                min_p = avg_p * 0.8
                max_p = avg_p * 1.2
            else:
                avg_p = 1.0 + (h % 140) / 10.0 # $1 - $15
                min_p = avg_p * 0.7
                max_p = avg_p * 1.3
            is_estimate = True
            
        stock_qty = r["stock_quantity"]
        if stock_qty is None:
            stock_status = "unknown"
        elif stock_qty <= 0:
            stock_status = "out"
        elif stock_qty <= LOW_STOCK_THRESHOLD:
            stock_status = "low"
        else:
            stock_status = "ok"

        inventory_map[sup]["materials"].append({
            "sku": sku,
            "type": r["type"],
            "canonical_name": clean_name,
            "supplier_count": r["supplier_count"],
            "hex_id": hex_id,
            "market_price_avg": avg_p,
            "market_price_min": min_p,
            "market_price_max": max_p,
            "is_estimate": is_estimate,
            "purity_percentage": r["PurityPercentage"],
            "grade": r["Grade"],
            "lab_status": r["LabTestStatus"],
            "certifications": r["Certifications"],
            "quality_audit_score": r["QualityAuditScore"],
            "sustainability_rating": r["SustainabilityRating"],
            "stock_quantity": stock_qty,
            "stock_status": stock_status,
            # Keys used to look up a substitute supplier for deficit items
            "_canonical_key": clean_name.lower(),
            "_supplier_name": sup,
        })

    # Build a canonical -> list of (supplier, stock, sku) index to pick
    # substitute suppliers for deficit items.
    canonical_index = {}
    for sup_name, bucket in inventory_map.items():
        for m in bucket["materials"]:
            key = m["_canonical_key"]
            if not key:
                continue
            canonical_index.setdefault(key, []).append({
                "supplier_name": sup_name,
                "sku": m["sku"],
                "stock_quantity": m["stock_quantity"] or 0,
            })

    # Attach a substitute suggestion on deficit rows: pick the supplier
    # offering the same canonical material with the highest available stock.
    for bucket in inventory_map.values():
        for m in bucket["materials"]:
            if m["stock_status"] in ("low", "out"):
                alternates = canonical_index.get(m["_canonical_key"], [])
                best = None
                for alt in alternates:
                    if alt["supplier_name"] == m["_supplier_name"]:
                        continue
                    if alt["stock_quantity"] <= LOW_STOCK_THRESHOLD:
                        continue
                    if best is None or alt["stock_quantity"] > best["stock_quantity"]:
                        best = alt
                m["substitute"] = best
            else:
                m["substitute"] = None
            # strip private helpers
            m.pop("_canonical_key", None)
            m.pop("_supplier_name", None)

    # Sort materials for each supplier by the extracted hex_id
    for sup in inventory_map:
        inventory_map[sup]["materials"].sort(key=lambda x: x["hex_id"])

    return list(inventory_map.values())
