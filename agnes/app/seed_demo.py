"""
Create a demo db.sqlite that matches the challenge schema, so the API
runs end-to-end out of the box. Replace this file with the real
hackathon db.sqlite and everything keeps working.

Run: python -m app.seed_demo
"""
import sqlite3
import os
from .config import DB_PATH


DDL = """
DROP TABLE IF EXISTS BOM_Component;
DROP TABLE IF EXISTS BOM;
DROP TABLE IF EXISTS Supplier_Product;
DROP TABLE IF EXISTS Supplier;
DROP TABLE IF EXISTS Product;
DROP TABLE IF EXISTS Company;

CREATE TABLE Company   (Id INTEGER PRIMARY KEY, Name TEXT);
CREATE TABLE Supplier  (Id INTEGER PRIMARY KEY, Name TEXT);
CREATE TABLE Product   (Id INTEGER PRIMARY KEY,
                        SKU TEXT,
                        CompanyId INTEGER,
                        Type TEXT);
CREATE TABLE BOM       (Id INTEGER PRIMARY KEY, ProducedProductId INTEGER);
CREATE TABLE BOM_Component (BOMid INTEGER, ConsumedProductId INTEGER);
CREATE TABLE Supplier_Product (SupplierId INTEGER, ProductId INTEGER);
"""


def seed():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.executescript(DDL)

    c.executemany("INSERT INTO Company VALUES (?, ?)", [
        (1, "NorthFoods"), (2, "EvergreenBeverages"), (3, "ValleySnacks"),
    ])
    c.executemany("INSERT INTO Supplier VALUES (?, ?)", [
        (1, "GlobalChem AG"), (2, "Bavaria Ingredients"),
        (3, "Alpine Organics"), (4, "PureSource BV"),
    ])

    products = [
        # finished goods
        (100, "FG-Lemon-Soda-12pk",         2, "finished-good"),
        (101, "FG-Orange-Juice-1L",         2, "finished-good"),
        (102, "FG-Granola-Bar-ChocoCrunch", 1, "finished-good"),
        (103, "FG-Granola-Bar-Berry",       1, "finished-good"),
        (104, "FG-Potato-Chips-Salted",     3, "finished-good"),

        # raw materials — deliberately messy names
        (200, "RM-C1-ascorbic-acid-4823fabf",       1, "raw-material"),
        (201, "RM-C2-ascorbic-acid-71ab",           2, "raw-material"),
        (202, "RM-C3-Ascorbic_Acid-food-grade",     3, "raw-material"),
        (203, "RM-C1-citric-acid-anhydrous",        1, "raw-material"),
        (204, "RM-C2-citric-acid-monohydrate",      2, "raw-material"),
        (205, "RM-C1-sunflower-oil-refined",        1, "raw-material"),
        (206, "RM-C3-sunflower-oil-high-oleic",     3, "raw-material"),
        (207, "RM-C1-rolled-oats-organic",          1, "raw-material"),
        (208, "RM-C1-cocoa-powder-natural",         1, "raw-material"),
        (209, "RM-C2-orange-concentrate",           2, "raw-material"),
    ]
    c.executemany("INSERT INTO Product VALUES (?, ?, ?, ?)", products)

    boms = [
        (1000, 100), (1001, 101), (1002, 102), (1003, 103), (1004, 104),
    ]
    c.executemany("INSERT INTO BOM VALUES (?, ?)", boms)

    bcs = [
        (1000, 201), (1000, 204),                      # lemon soda
        (1001, 201), (1001, 209),                      # OJ
        (1002, 200), (1002, 207), (1002, 208), (1002, 205),  # chocolate granola
        (1003, 200), (1003, 207), (1003, 205),         # berry granola
        (1004, 202), (1004, 206),                      # chips
    ]
    c.executemany("INSERT INTO BOM_Component VALUES (?, ?)", bcs)

    sps = [
        (1, 200), (1, 201), (1, 202),                  # GlobalChem supplies all ascorbic
        (2, 200), (2, 203),                            # Bavaria: ascorbic + citric
        (4, 201), (4, 204),                            # PureSource: both citric types
        (3, 205), (3, 206), (3, 207),                  # Alpine: oils + oats
        (1, 208), (2, 209),
    ]
    c.executemany("INSERT INTO Supplier_Product VALUES (?, ?)", sps)

    c.commit()
    c.close()
    print(f"Seeded demo DB at {DB_PATH}")
    print(f"  {len(products)} products ({sum(1 for p in products if p[3]=='raw-material')} raw materials)")
    print(f"  {len(sps)} supplier relationships")


if __name__ == "__main__":
    seed()
