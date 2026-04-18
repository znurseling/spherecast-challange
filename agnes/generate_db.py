import sqlite3
import random

# Connect to your existing database
# Ensure db.sqlite is in the same directory!
source_conn = sqlite3.connect('db.sqlite')
dest_conn = sqlite3.connect('extended_agnes_db.sqlite')

# 1. Copy original data to the new database
source_conn.backup(dest_conn)
cursor = dest_conn.cursor()

# 2. Create the Decision-Support Tables
cursor.executescript("""
CREATE TABLE IF NOT EXISTS SupplierInventoryCost (
    SupplierId INTEGER,
    ProductId INTEGER,
    UnitCost REAL,
    Currency TEXT,
    LeadTimeDays INTEGER,
    InventoryLevel INTEGER,
    PRIMARY KEY (SupplierId, ProductId)
);

CREATE TABLE IF NOT EXISTS ProductQualitySpecs (
    SupplierId INTEGER,
    ProductId INTEGER,
    PurityPercentage REAL,
    Grade TEXT,
    Certifications TEXT,
    LabTestStatus TEXT,
    PRIMARY KEY (SupplierId, ProductId)
);

CREATE TABLE IF NOT EXISTS SupplierPerformance (
    SupplierId INTEGER PRIMARY KEY,
    OnTimeDeliveryRate REAL,
    QualityAuditScore INTEGER,
    SustainabilityRating TEXT
);
""")

# 3. Populate with Realistic Mock Data
# Get all supplier-product mappings
cursor.execute("SELECT SupplierId, ProductId FROM Supplier_Product")
mappings = cursor.fetchall()

for s_id, p_id in mappings:
    # Inventory & Cost
    cursor.execute("INSERT OR REPLACE INTO SupplierInventoryCost VALUES (?, ?, ?, ?, ?, ?)",
                   (s_id, p_id, round(random.uniform(2.5, 45.0), 2), 'USD', random.randint(3, 45), random.randint(50, 5000)))
    
    # Quality Specs
    certs = ", ".join(random.sample(["ISO 9001", "GMP", "Non-GMO", "Organic", "USP", "HACCP"], random.randint(1, 3)))
    cursor.execute("INSERT OR REPLACE INTO ProductQualitySpecs VALUES (?, ?, ?, ?, ?, ?)",
                   (s_id, p_id, round(random.uniform(94.0, 99.9), 1), 
                    random.choice(["Food Grade", "Pharma Grade"]), certs, 
                    random.choice(["Passed", "Passed", "Passed", "Flagged"])))

# Supplier Performance
cursor.execute("SELECT Id FROM Supplier")
suppliers = cursor.fetchall()
for (s_id,) in suppliers:
    cursor.execute("INSERT OR REPLACE INTO SupplierPerformance VALUES (?, ?, ?, ?)",
                   (s_id, round(random.uniform(0.75, 0.99), 2), random.randint(70, 100), random.choice(['A', 'B', 'C'])))

dest_conn.commit()
print("Success! Created 'extended_agnes_db.sqlite' with quality and cost metrics.")
source_conn.close()
dest_conn.close()
