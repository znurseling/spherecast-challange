"""
Seed a demo-friendly distribution of stock deficits into SupplierInventoryCost.

The database already has InventoryLevel for every supplier-product mapping,
but the values are uniformly healthy (50-5000). For the jury demo we want
a visible mix of out-of-stock, low-stock, and well-stocked rows so the UI
can show the deficit -> substitute suggestion flow.

Strategy (deterministic, uses a fixed seed):
  - ~8%  of rows -> 0           (Out of stock)
  - ~15% of rows -> 30-180      (Low / deficit)
  - rest left untouched
"""
import random
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent / "db.sqlite"
random.seed(42)

conn = sqlite3.connect(DB)
cur = conn.cursor()

rows = cur.execute(
    "SELECT SupplierId, ProductId FROM SupplierInventoryCost"
).fetchall()

out_count = 0
low_count = 0
for s_id, p_id in rows:
    r = random.random()
    if r < 0.08:
        cur.execute(
            "UPDATE SupplierInventoryCost SET InventoryLevel = 0 "
            "WHERE SupplierId = ? AND ProductId = ?",
            (s_id, p_id),
        )
        out_count += 1
    elif r < 0.23:
        cur.execute(
            "UPDATE SupplierInventoryCost SET InventoryLevel = ? "
            "WHERE SupplierId = ? AND ProductId = ?",
            (random.randint(30, 180), s_id, p_id),
        )
        low_count += 1

conn.commit()
print(f"Updated {out_count} rows to OUT (0) and {low_count} rows to LOW (30-180).")
print(f"Remaining {len(rows) - out_count - low_count} rows left at healthy levels.")
conn.close()
