# ============================================
# UNIWERSALNY EXPORT PARQUET → EXCEL
# działa na dowolnym katalogu
# ============================================

import os
import pandas as pd

#BASE_PATH = "/home/ubuntu/data"   # <- zmieniasz katalog
BASE_PATH = os.getcwd()

print("[INFO] Start konwersji parquet → excel")

def remove_timezone(df):
    df = df.copy()
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            try:
                df[col] = df[col].dt.tz_localize(None)
            except:
                pass
    return df

files = [f for f in os.listdir(BASE_PATH) if f.endswith(".parquet")]

print(f"[INFO] znaleziono {len(files)} plików")

for file in files:
    parquet_path = os.path.join(BASE_PATH, file)
    excel_path = os.path.join(BASE_PATH, file.replace(".parquet", ".xlsx"))

    print(f"\n[INFO] {file}")

    try:
        df = pd.read_parquet(parquet_path)

        # fix timezone
        df = remove_timezone(df)

        df.to_excel(excel_path, index=False)

        print(f"[OK] zapisano: {excel_path}")

    except Exception as e:
        print(f"[ERROR] {file}: {e}")

print("\n[DONE]")
