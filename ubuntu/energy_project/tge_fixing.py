# ============================================
# TGE PIPELINE — RDN + FixingPricesH (OVH)
# ============================================

import os
import datetime as dt
import pandas as pd
import requests
from bs4 import BeautifulSoup

print("=== START PIPELINE ===")

# ============================================
# MODUŁ 0 — KONFIG
# ============================================

BASE_DIR = "/home/ubuntu/data/tge"

FILE_RDN = "RDN_fixing.parquet"
FILE_H = "FixingPricesH.parquet"

PATH_RDN = os.path.join(BASE_DIR, FILE_RDN)
PATH_H = os.path.join(BASE_DIR, FILE_H)

os.makedirs(BASE_DIR, exist_ok=True)

RDN_URL = "https://www.tge.pl/energia-elektryczna-rdn?dateShow={date}"

# ============================================
# MODUŁ 1 — LOAD HISTORY
# ============================================

if os.path.exists(PATH_RDN):
    df_rdn_history = pd.read_parquet(PATH_RDN)
    print("[OK] Wczytano historię:", len(df_rdn_history))
else:
    df_rdn_history = pd.DataFrame()
    print("[INFO] Brak historii — start od zera")

# ============================================
# MODUŁ 2 — DATE RANGE
# ============================================

if not df_rdn_history.empty:
    df_rdn_history["data_fix"] = pd.to_datetime(df_rdn_history["data_fix"])
    last_fix_date = df_rdn_history["data_fix"].max().date()
else:
    last_fix_date = dt.date(2025, 1, 1)

target_end_date = dt.date.today() - dt.timedelta(days=1)

if last_fix_date >= target_end_date:
    dates_to_fetch = []
else:
    start = last_fix_date + dt.timedelta(days=1)
    dates_to_fetch = [
        start + dt.timedelta(days=i)
        for i in range((target_end_date - start).days + 1)
    ]

print("[INFO] Daty do pobrania:", len(dates_to_fetch))

# ============================================
# MODUŁ 3 — FUNCTIONS
# ============================================

def download_rdn(date_):
    url = RDN_URL.format(date=date_.strftime("%d-%m-%Y"))
    r = requests.get(url, timeout=30)
    r.raise_for_status()

    soup = BeautifulSoup(r.content, "html.parser")
    table = soup.find("table", {"id": "rdn"})

    if table is None:
        return pd.DataFrame()

    rows = table.find_all("tr")

    headers = []
    for th in rows[1].find_all("th"):
        colspan = int(th.get("colspan", 1))
        headers.extend([th.text.strip()] * colspan)

    data = []
    for row in rows[2:]:
        tds = row.find_all("td")
        if tds:
            data.append([td.text.strip() for td in tds])

    df = pd.DataFrame(data)
    if len(headers) == df.shape[1]:
        df.columns = headers

    df["dateShow"] = date_

    return df


def clean_df(df):
    for col in df.columns:
        if isinstance(df[col], pd.DataFrame):
            continue
        df[col] = (
            df[col]
            .replace("-", pd.NA)
            .astype(str)
            .str.replace(" ", "")
            .str.replace(",", ".")
        )
        try:
            df[col] = df[col].astype(float)
        except:
            pass
    return df


def build_fact(df_raw):
    df = pd.DataFrame()

    df["data_deliv"] = df_raw.iloc[:, 0]
    df["instrument"] = df_raw.iloc[:, 1]

    df["f1_price_PLN"] = pd.to_numeric(df_raw.iloc[:, 2], errors="coerce")
    df["sdac_price_PLN"] = pd.to_numeric(df_raw.iloc[:, 7], errors="coerce")

    return df


# ============================================
# MODUŁ 4 — IMPORT
# ============================================

frames = []

for d in dates_to_fetch:
    print("📥", d)
    try:
        df_raw = download_rdn(d)
        if df_raw.empty:
            continue
        df_raw = clean_df(df_raw)
        df_fact = build_fact(df_raw)
        df_fact["data_fix"] = pd.to_datetime(d)
        frames.append(df_fact)
    except Exception as e:
        print("❌", e)

df_new = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

# ============================================
# MODUŁ 5 — MERGE + DEDUP
# ============================================

df_all = pd.concat([df_rdn_history, df_new], ignore_index=True)

df_all["data_fix"] = pd.to_datetime(df_all["data_fix"])

df_all = (
    df_all
    .sort_values("data_fix")
    .drop_duplicates(["data_fix", "data_deliv", "instrument"], keep="last")
)

print("[OK] RDN rows:", len(df_all))

# ============================================
# MODUŁ 6 — SAVE RDN (ATOMIC)
# ============================================

tmp_path = PATH_RDN + ".tmp"
df_all.to_parquet(tmp_path, index=False)
os.replace(tmp_path, PATH_RDN)

print("[OK] RDN zapisany")

# ============================================
# MODUŁ 7 — BUILD H
# ============================================

df = df_all.copy()

df["Hour"] = df["data_deliv"].str.split("_").str[-1]
df["delivery_date"] = pd.to_datetime(df["data_deliv"].str.split("_").str[0])
df["fixing_date"] = pd.to_datetime(df["data_fix"])

# PROSTE MAPOWANIE H (H01 → 1 itd.)
df["H"] = df["Hour"].str.extract(r'(\d+)').astype(int)

df_h = (
    df
    .groupby(["fixing_date", "delivery_date", "H"], as_index=False)
    .agg(
        f1_price_PLN=("f1_price_PLN", "mean"),
        sdac_price_PLN=("sdac_price_PLN", "mean"),
    )
)

df_h["spread_f1_sdac"] = df_h["f1_price_PLN"] - df_h["sdac_price_PLN"]

print("[OK] H dataset:", len(df_h))

# ============================================
# MODUŁ 8 — SAVE H (ATOMIC)
# ============================================

tmp_path = PATH_H + ".tmp"

df_h.sort_values(["delivery_date", "H"]).to_parquet(tmp_path, index=False)

os.replace(tmp_path, PATH_H)

print("[OK] FixingPricesH zapisany")

# ============================================
# KONIEC
# ============================================

print("=== PIPELINE DONE ===")
