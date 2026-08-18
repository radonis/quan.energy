# ============================================
# FORECASTING_VIEWS.py
# Tworzy/odświeża widoki: pk5 + fixing_prices
# ============================================

import duckdb
import os

# ============================================
# KONFIG
# ============================================

DB_PATH = "/home/ubuntu/db/forecast_db.duckdb"
PATH_PK5 = "/home/ubuntu/data/pk5/pk5.parquet"
PATH_FIXING = "/home/ubuntu/data/tge/FixingPricesH.parquet"

# ============================================
# WALIDACJA
# ============================================

print("[INFO] Start forecasting_views")

if not os.path.exists(DB_PATH):
    raise FileNotFoundError(f"[ERROR] Brak bazy: {DB_PATH}")

if not os.path.exists(PATH_PK5):
    raise FileNotFoundError(f"[ERROR] Brak pliku PK5: {PATH_PK5}")

if not os.path.exists(PATH_FIXING):
    raise FileNotFoundError(f"[ERROR] Brak pliku fixing: {PATH_FIXING}")

# ============================================
# POŁĄCZENIE
# ============================================

con = duckdb.connect(DB_PATH)
print("[OK] Połączono z bazą")

# ============================================
# VIEW PK5
# ============================================

con.execute("DROP VIEW IF EXISTS pk5")

con.execute(f"""
CREATE VIEW pk5 AS
SELECT *
FROM read_parquet('{PATH_PK5}')
""")

print("[OK] VIEW pk5 utworzony")

# ============================================
# VIEW FIXING PRICES
# ============================================

con.execute("DROP VIEW IF EXISTS fixing_prices")

con.execute(f"""
CREATE VIEW fixing_prices AS
SELECT *
FROM read_parquet('{PATH_FIXING}')
""")

print("[OK] VIEW fixing_prices utworzony")

# ============================================
# ZAMKNIĘCIE
# ============================================

con.close()

print("[INFO] forecasting_views zakończony")
