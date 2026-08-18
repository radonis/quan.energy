# ============================================
# GAS PIPELINE — TGE OTF (PRODUCTION VERSION)
# ============================================

import pandas as pd
import requests
from io import StringIO
import datetime as dt
import time
import random
import os

# ============================================
# CONFIG
# ============================================

DATA_PATH = "/home/ubuntu/data/tge/tge_otf_gaz_hist.parquet"

# ============================================
# LOAD EXISTING DATA
# ============================================

def load_data():
    if os.path.exists(DATA_PATH):
        df = pd.read_parquet(DATA_PATH)
        df["date"] = pd.to_datetime(df["date"])
        print(f"[INFO] Wczytano dane: {len(df)} rekordów")
    else:
        df = pd.DataFrame()
        print("[WARN] Brak pliku — start od zera")

    return df

# ============================================
# DATE RANGE
# ============================================

def get_date_range(df):

    today = dt.date.today()

    if df.empty:
        start_date = today - dt.timedelta(days=30)
    else:
        last_date = df["date"].max().date()
        start_date = last_date + dt.timedelta(days=1)

    end_date = today - dt.timedelta(days=1)

    if start_date > end_date:
        print("[INFO] Brak nowych danych")
        return []

    dates = pd.date_range(start_date, end_date).date

    print(f"[INFO] Pobieramy {len(dates)} dni: {start_date} → {end_date}")

    return dates

# ============================================
# FETCH DATA
# ============================================

def fetch_data(dates):

    rows = []

    for i, d in enumerate(dates, 1):

        url = f"https://www.tge.pl/gaz-otf?dateShow={d.strftime('%d-%m-%Y')}"

        try:
            print(f"{i}/{len(dates)} {d} ...", end="")

            r = requests.get(url, timeout=30)
            r.raise_for_status()

            tables = pd.read_html(StringIO(r.text))

            df_day = None
            for t in tables:
                if "Kontrakt" in t.columns:
                    df_day = t.copy()
                    break

            if df_day is None:
                print(" brak tabeli")
                continue

            df_day["date"] = pd.to_datetime(d)
            rows.append(df_day)

            print(" OK")

            time.sleep(1 + random.random())

        except Exception as e:
            print(" ERROR:", e)
            time.sleep(2)

    if rows:
        return pd.concat(rows, ignore_index=True)
    else:
        return pd.DataFrame()

# ============================================
# CLEAN DATA
# ============================================

def clean_data(df):

    if df.empty:
        return df

    df = df.loc[:, ~df.columns.str.contains("^Unnamed")]

    price_cols = [
        "Kurs pierwszej transakcji (PLN/MWh)",
        "DKR (PLN/MWh)",
        "Kurs min. na sesji (PLN/MWh)",
        "Kurs maks. na sesji (PLN/MWh)"
    ]

    for c in price_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce") / 100

    num_cols = [
        "Łączny wolumen obrotu (MWh)",
        "Liczba kontraktów",
        "Łączna wartość obrotu (PLN)",
        "Liczba transakcji",
        "Łączna liczba otwartych pozycji LOP (MWh)"
    ]

    for c in num_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df[
        ~df["Kontrakt"].str.lower().str.contains("suma|razem", na=False)
    ]

    # parsing kontraktu
    split = df["Kontrakt"].str.split("_", expand=True)

    df["segment"] = split[0]
    df["profile"] = split[1]

    period = split[2]

    df["product_type"] = period.str[0]
    df["product_week"] = pd.to_numeric(period.str.extract(r"W-(\d+)")[0], errors="coerce")
    df["product_year"] = pd.to_numeric("20" + period.str.extract(r"-(\d+)$")[0], errors="coerce")

    return df

# ============================================
# MERGE
# ============================================

def merge_data(df_old, df_new):

    if df_new.empty:
        return df_old

    df = pd.concat([df_old, df_new], ignore_index=True)

    df = df.drop_duplicates(
        subset=["date", "Kontrakt"],
        keep="last"
    )

    df = df.sort_values(["date", "Kontrakt"]).reset_index(drop=True)

    return df

# ============================================
# SAVE
# ============================================

def save_data(df):
    df.to_parquet(DATA_PATH, index=False)
    print("[OK] zapisano parquet")

# ============================================
# MAIN
# ============================================

def main():

    print("\n=== GAS PIPELINE START ===")

    df_old = load_data()
    dates = get_date_range(df_old)

    if not dates:
        return

    df_new = fetch_data(dates)
    df_new = clean_data(df_new)

    df_final = merge_data(df_old, df_new)

    print(f"[INFO] rekordy końcowe: {len(df_final)}")

    save_data(df_final)

    print("=== DONE ===\n")


if __name__ == "__main__":
    main()
