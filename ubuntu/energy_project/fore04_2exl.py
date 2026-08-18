# ============================================
# EXPORT market_features_raw → EXCEL (OVH)
# ============================================

import duckdb
import pandas as pd
from datetime import datetime

DB_PATH = "/home/ubuntu/db/forecast_db.duckdb"
OUTPUT_PATH = "/home/ubuntu/db/market_features_raw.xlsx"

print("[INFO] Łączenie z DuckDB...")
con = duckdb.connect(DB_PATH)

print("[INFO] Pobieranie danych z market_features_raw...")

df = con.execute("""
SELECT *
FROM market_features_raw
ORDER BY Timestamp
""").fetchdf()

print(f"[OK] Pobrano {len(df)} rekordów")

# --- konwersja datetime (bezpieczna)
if "Timestamp" in df.columns:
    df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce")

# --- zapis do Excela
print("[INFO] Zapis do Excel...")

df.to_excel(OUTPUT_PATH, index=False)

print(f"[OK] Zapisano plik: {OUTPUT_PATH}")

# --- info końcowe
print("===================================")
print("MIN Timestamp:", df["Timestamp"].min())
print("MAX Timestamp:", df["Timestamp"].max())
print("===================================")

con.close()
