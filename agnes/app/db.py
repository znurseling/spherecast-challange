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

def get_supplier_inventory() -> List[Dict]:
    s = schema()
    q = f"""
        SELECT 
            su.{s["su_name"]} AS supplier_name,
            p.{s["p_sku"]} AS sku,
            p.{s["p_type"]} AS type,
            c.supplier_count
        FROM Supplier su
        JOIN Supplier_Product sp ON su.{s["su_id"]} = sp.{s["sp_supplier"]}
        JOIN Product p ON p.{s["p_id"]} = sp.{s["sp_product"]}
        JOIN (
            SELECT {s["sp_product"]}, COUNT({s["sp_supplier"]}) as supplier_count
            FROM Supplier_Product
            GROUP BY {s["sp_product"]}
        ) c ON c.{s["sp_product"]} = p.{s["p_id"]}
        WHERE p.{s["p_type"]} IN ('raw-material', 'rawmaterial')
        ORDER BY su.{s["su_name"]}, p.{s["p_sku"]}
    """
    with connection() as c:
        try:
            rows = c.execute(q).fetchall()
        except sqlite3.OperationalError:
            rows = []
        
    inventory_map = {}
    from .llm import _mock_canonical
    
    for r in rows:
        sup = r["supplier_name"]
        if sup not in inventory_map:
            inventory_map[sup] = {"supplier_name": sup, "materials": []}
            
        inventory_map[sup]["materials"].append({
            "sku": r["sku"],
            "type": r["type"],
            "canonical_name": _mock_canonical(r["sku"]),
            "supplier_count": r["supplier_count"]
        })
        
    return list(inventory_map.values())
