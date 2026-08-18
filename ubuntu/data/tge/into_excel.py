# ============================================
# KONWERSJA PARQUET → EXCEL (batch)
# katalog: /home/ubuntu/data/tge
# ============================================

import os
import pandas as pd

# --- ścieżka ---
BASE_PATH = "/home/ubuntu/data/tge"

print("[INFO] Start konwersji parquet → excel")

# --- lista plików ---
files = [f for f in os.listdir(BASE_PATH) if f.endswith(".parquet")]

print(f"[INFO] Znaleziono {len(files)} plików parquet")

for file in files:
    parquet_path = os.path.join(BASE_PATH, file)
    excel_path = os.path.join(BASE_PATH, file.replace(".parquet", ".xlsx"))

    print(f"\n[INFO] Przetwarzanie: {file}")

    try:
        df = pd.read_parquet(parquet_path)

        print(f"[OK] Wczytano: {df.shape}")

        df.to_excel(excel_path, index=False)

        print(f"[OK] Zapisano: {excel_path}")

    except Exception as e:
        print(f"[ERROR] {file}: {e}")

print("\n[INFO] Konwersja zakończona")
