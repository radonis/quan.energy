#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
DE_forecast.py

Codzienny import prognozy DE z Electricity Maps, zapis pliku głównego
oraz pliku historycznego na serwerze OVH.

Pliki docelowe:
- /home/ubuntu/data/de/DE_Price_72H_Forecast.parquet
- /home/ubuntu/data/de/DE_fore_hist.parquet

Uruchamianie ręczne:
    /usr/bin/python3 /home/ubuntu/energy_project/DE_forecast.py

Cron 07:10:
    10 7 * * * /usr/bin/python3 /home/ubuntu/energy_project/DE_forecast.py >> /home/ubuntu/energy_project/DE_forecast.log 2>&1
"""

from __future__ import annotations

import os
from datetime import datetime

import pandas as pd
import requests


# ============================================================
# MODUŁ 1 — PARAMETRY
# ============================================================
print("=== MODUŁ 1 — PARAMETRY ===")

API_TOKEN = "ejN3pR5M2rhfKD52Bp3F"
ZONE = "DE"
HORIZON_HOURS = 72
API_URL = "https://api.electricitymaps.com/v3/price-day-ahead/forecast"

# kurs ręczny — zostawiam na górze zgodnie z Twoją prośbą
EURPLN = 4.28

BASE_DIR = "/home/ubuntu/data/de"
OUTPUT_PARQUET = os.path.join(BASE_DIR, "DE_Price_72H_Forecast.parquet")
OUTPUT_EXCEL = os.path.join(BASE_DIR, "DE_Price_72H_Forecast.xlsx")
HIST_PARQUET = os.path.join(BASE_DIR, "DE_fore_hist.parquet")
HIST_EXCEL = os.path.join(BASE_DIR, "DE_fore_hist.xlsx")

RUN_TIMESTAMP = pd.Timestamp.now(tz="Europe/Warsaw")
TODAY_PL = RUN_TIMESTAMP.normalize()

print(f"[INFO] ZONE           : {ZONE}")
print(f"[INFO] HORIZON_HOURS  : {HORIZON_HOURS}")
print(f"[INFO] EURPLN         : {EURPLN}")
print(f"[INFO] RUN_TIMESTAMP  : {RUN_TIMESTAMP}")
print(f"[INFO] OUTPUT_PARQUET : {OUTPUT_PARQUET}")
print(f"[INFO] HIST_PARQUET   : {HIST_PARQUET}")

if API_TOKEN == "TU_WSTAW_TOKEN":
    raise ValueError("❌ Uzupełnij API_TOKEN w sekcji parametrów.")

os.makedirs(BASE_DIR, exist_ok=True)
print("[OK] katalog docelowy gotowy")


# ============================================================
# MODUŁ 2 — IMPORT Z API ELECTRICITYMAPS
# ============================================================
print("\n=== MODUŁ 2 — IMPORT Z API ELECTRICITYMAPS ===")

params = {
    "zone": ZONE,
    "horizonHours": HORIZON_HOURS,
}
headers = {
    "auth-token": API_TOKEN,
}

response = requests.get(API_URL, params=params, headers=headers, timeout=60)

if response.status_code != 200:
    raise RuntimeError(f"❌ API error {response.status_code}: {response.text}")

data = response.json()
if "data" not in data:
    raise RuntimeError("❌ API response nie zawiera klucza 'data'.")

records = data["data"]
if not records:
    raise RuntimeError("❌ API zwróciło pustą listę rekordów.")

df_api = pd.DataFrame(records)
print("[INFO] kolumny API:", list(df_api.columns))

required_cols = {"datetime", "value"}
missing_cols = required_cols - set(df_api.columns)
if missing_cols:
    raise RuntimeError(f"❌ Brakuje kolumn w odpowiedzi API: {sorted(missing_cols)}")

# UTC -> Europe/Warsaw
# zachowujemy timezone w parquet; do excela usuniemy później
df_api["datetime"] = pd.to_datetime(df_api["datetime"], utc=True)
df_api["datetime"] = df_api["datetime"].dt.tz_convert("Europe/Warsaw")
df_api["PriceEU"] = pd.to_numeric(df_api["value"], errors="coerce")

df_api = (
    df_api[["datetime", "PriceEU"]]
    .dropna(subset=["datetime", "PriceEU"])
    .sort_values("datetime")
    .drop_duplicates(subset=["datetime"], keep="last")
    .reset_index(drop=True)
)

print("[OK] dataframe API utworzony")
print("[INFO] liczba rekordów:", len(df_api))
print(df_api.head())


# ============================================================
# MODUŁ 3 — BUDOWA PLIKU GŁÓWNEGO
# ============================================================
print("\n=== MODUŁ 3 — BUDOWA PLIKU GŁÓWNEGO ===")

df_DE_Prices_Forecast = df_api.copy()
df_DE_Prices_Forecast["kurs"] = EURPLN
df_DE_Prices_Forecast["PricePL"] = df_DE_Prices_Forecast["PriceEU"] * EURPLN
df_DE_Prices_Forecast["run_timestamp"] = RUN_TIMESTAMP

df_DE_Prices_Forecast = df_DE_Prices_Forecast[
    ["datetime", "PriceEU", "kurs", "PricePL", "run_timestamp"]
].copy()

print("[OK] df_DE_Prices_Forecast gotowy")
print(df_DE_Prices_Forecast.head())


# ============================================================
# MODUŁ 4 — BUDOWA PLIKU HISTORYCZNEGO
# ============================================================
print("\n=== MODUŁ 4 — BUDOWA PLIKU HISTORYCZNEGO ===")

df_hist_new = df_DE_Prices_Forecast.copy()

# dzień względem dzisiaj: d, d+1, d+2, ...
days_ahead = (df_hist_new["datetime"].dt.normalize() - TODAY_PL).dt.days

def map_day_relative(x: int) -> str:
    if x <= 0:
        return "d"
    return f"d+{int(x)}"

df_hist_new["day_relative"] = days_ahead.map(map_day_relative)
df_hist_new = df_hist_new[
    ["datetime", "day_relative", "PriceEU", "kurs", "PricePL", "run_timestamp"]
].copy()

if os.path.exists(HIST_PARQUET):
    print("[INFO] istnieje wcześniejszy plik historii — wczytuję")
    df_hist_old = pd.read_parquet(HIST_PARQUET)
    print(f"[INFO] stara historia shape: {df_hist_old.shape}")

    df_hist = pd.concat([df_hist_old, df_hist_new], ignore_index=True)

    # deduplikacja po snapshot + dacie godziny prognozy
    # zostawiamy ostatni rekord gdyby coś zostało zapisane dwa razy
    df_hist = df_hist.drop_duplicates(
        subset=["run_timestamp", "datetime"],
        keep="last",
    ).sort_values(["run_timestamp", "datetime"]).reset_index(drop=True)
else:
    print("[INFO] brak wcześniejszego pliku historii — tworzę nowy")
    df_hist = df_hist_new.copy()

print(f"[OK] historia gotowa: {df_hist.shape}")
print(df_hist.tail())


# ============================================================
# MODUŁ 5 — WALIDACJA
# ============================================================
print("\n=== MODUŁ 5 — WALIDACJA ===")

if df_DE_Prices_Forecast.empty:
    raise RuntimeError("❌ Plik główny jest pusty.")

if df_hist.empty:
    raise RuntimeError("❌ Plik historii jest pusty.")

if df_DE_Prices_Forecast["datetime"].isna().any():
    raise RuntimeError("❌ W pliku głównym są puste datetime.")

if df_DE_Prices_Forecast["PriceEU"].isna().any():
    raise RuntimeError("❌ W pliku głównym są puste PriceEU.")

print("[OK] walidacja zakończona")
print("[INFO] zakres forecast:")
print("      od:", df_DE_Prices_Forecast["datetime"].min())
print("      do:", df_DE_Prices_Forecast["datetime"].max())
print("[INFO] unikalne day_relative:", sorted(df_hist_new["day_relative"].dropna().unique().tolist()))


# ============================================================
# MODUŁ 6 — ZAPIS PARQUET
# ============================================================
print("\n=== MODUŁ 6 — ZAPIS PARQUET ===")

df_DE_Prices_Forecast.to_parquet(OUTPUT_PARQUET, index=False)
print("[OK] zapisano:", OUTPUT_PARQUET)

df_hist.to_parquet(HIST_PARQUET, index=False)
print("[OK] zapisano:", HIST_PARQUET)


# ============================================================
# MODUŁ 7 — ZAPIS EXCEL
# ============================================================
print("\n=== MODUŁ 7 — ZAPIS EXCEL ===")

def strip_timezone_for_excel(df: pd.DataFrame) -> pd.DataFrame:
    df_out = df.copy()
    for col in df_out.columns:
        dtype_str = str(df_out[col].dtype)
        if dtype_str.startswith("datetime64[ns,"):
            df_out[col] = df_out[col].dt.tz_localize(None)
    return df_out

strip_timezone_for_excel(df_DE_Prices_Forecast).to_excel(OUTPUT_EXCEL, index=False)
print("[OK] zapisano:", OUTPUT_EXCEL)

strip_timezone_for_excel(df_hist).to_excel(HIST_EXCEL, index=False)
print("[OK] zapisano:", HIST_EXCEL)


# ============================================================
# MODUŁ 8 — PODSUMOWANIE
# ============================================================
print("\n=== MODUŁ 8 — PODSUMOWANIE ===")
print("[SUCCESS] DE forecast update zakończony poprawnie ✅")
print(f"[INFO] forecast rows : {len(df_DE_Prices_Forecast)}")
print(f"[INFO] history rows  : {len(df_hist)}")
print(f"[INFO] run_timestamp : {RUN_TIMESTAMP}")
