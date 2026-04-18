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


def raw_type_matches(v: str) -> bool:
    return str(v).lower().replace("_", "-") in ("raw-material", "rawmaterial")
