# ============================================
# MODUŁ — EXPORT market_features_raw → PARQUET (z datą)
# ============================================

import duckdb
import os
from datetime import datetime

DB_PATH = "/home/ubuntu/db/forecast_db.duckdb"

# --- data w formacie YYYYMMDD ---
today_str = datetime.now().strftime("%Y%m%d")

OUTPUT_PATH = f"/home/ubuntu/db/{today_str}_features.parquet"

print("[INFO] Łączenie z bazą...")
con = duckdb.connect(DB_PATH)

print("[INFO] Eksport do parquet...")

con.execute(f"""
COPY (
    SELECT *
    FROM market_features_raw
    ORDER BY Timestamp
)
TO '{OUTPUT_PATH}'
(FORMAT PARQUET);
""")

print("[OK] Eksport zakończony")

# --- kontrola ---
if os.path.exists(OUTPUT_PATH):
    size = os.path.getsize(OUTPUT_PATH)
    print(f"[OK] Plik zapisany: {OUTPUT_PATH}")
    print(f"[INFO] Rozmiar: {round(size/1024/1024,2)} MB")
else:
    print("[ERROR] Plik nie powstał")
