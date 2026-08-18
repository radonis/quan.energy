# ============================================
# PK5 PIPELINE — OVH VERSION (PRODUCTION)
# ============================================

import os
import time
import requests
import pandas as pd
from datetime import datetime, timedelta

# ============================================
# CONFIG
# ============================================

BASE_DIR = "/home/ubuntu/data/pk5"
PATH_PK5 = f"{BASE_DIR}/pk5.parquet"
PATH_PK5FOR = f"{BASE_DIR}/pk5for.parquet"
PATH_BACKUP = f"{BASE_DIR}/backup"

os.makedirs(BASE_DIR, exist_ok=True)
os.makedirs(PATH_BACKUP, exist_ok=True)

TODAY = pd.Timestamp(datetime.today().date())
H_CUTOFF = TODAY - pd.Timedelta(days=1)

PSE_BASE_URL = "https://api.raporty.pse.pl/api"
PSE_REPORT_PK5 = "pk5l-wp"
PSE_TIMEOUT = 30
PSE_THROTTLE_SEC = 0.2

FORECAST_HORIZON_DAYS = 14

print(f"[START] PK5 pipeline | {TODAY.date()}")

# ============================================
# UTILS
# ============================================

def safe_save(df, path):
    tmp_path = path + ".tmp"

    # zapis tmp
    df.to_parquet(tmp_path, index=False)

    if not os.path.exists(tmp_path):
        raise RuntimeError("❌ TMP zapis nie powiódł się")

    # backup starego pliku
    if os.path.exists(path):
        backup_path = os.path.join(
            PATH_BACKUP,
            f"{os.path.basename(path)}_{int(time.time())}.parquet"
        )
        os.rename(path, backup_path)
        print(f"[OK] Backup: {backup_path}")

    # atomic replace
    os.rename(tmp_path, path)

    print(f"[OK] Zapisano: {path}")


def clean_strings(df):
    str_cols = df.select_dtypes(include="object").columns
    for c in str_cols:
        df[c] = (
            df[c]
            .str.replace(r"\n", "", regex=True)
            .str.replace('"', "", regex=True)
            .str.replace("'", "", regex=True)
        )
    return df


def download_pse_day(day):
    url = (
        f"{PSE_BASE_URL}/{PSE_REPORT_PK5}"
        f"?$filter=business_date eq '{day.strftime('%Y-%m-%d')}'"
        "&$first=100000"
    )

    try:
        r = requests.get(url, timeout=PSE_TIMEOUT)
        if r.status_code != 200:
            print(f"[WARN] HTTP {r.status_code} {day.date()}")
            return pd.DataFrame()

        payload = r.json().get("value", [])
        if not payload:
            return pd.DataFrame()

        df = pd.DataFrame(payload)
        df = clean_strings(df)
        df = df.convert_dtypes()

        # daty
        if "business_date" in df:
            df["business_date"] = pd.to_datetime(df["business_date"])
        if "plan_dtime" in df:
            df["plan_dtime"] = pd.to_datetime(df["plan_dtime"])
        if "plan_dtime_utc" in df:
            df["plan_dtime_utc"] = pd.to_datetime(df["plan_dtime_utc"])

        return df

    except Exception as e:
        print(f"[ERROR] {day.date()} {e}")
        return pd.DataFrame()


# ============================================
# 1. LOAD MASTER
# ============================================

if os.path.exists(PATH_PK5):
    df_pk5 = pd.read_parquet(PATH_PK5)
    print(f"[OK] Wczytano master: {df_pk5.shape}")
else:
    df_pk5 = pd.DataFrame()
    print("[INFO] Brak mastera — start od zera")

# ============================================
# 2. LAST H DATE
# ============================================

if not df_pk5.empty and "data_type" in df_pk5.columns:
    df_h = df_pk5[df_pk5["data_type"] == "H"]

    if not df_h.empty:
        last_h_date = df_h["business_date"].max().normalize()
    else:
        last_h_date = TODAY - pd.Timedelta(days=7)
else:
    last_h_date = TODAY - pd.Timedelta(days=7)

pse_start_date = last_h_date + pd.Timedelta(days=1)
pse_end_date = TODAY + pd.Timedelta(days=FORECAST_HORIZON_DAYS)

print(f"[INFO] Zakres PSE: {pse_start_date.date()} → {pse_end_date.date()}")

# ============================================
# 3. DOWNLOAD PSE
# ============================================

dates = pd.date_range(pse_start_date, pse_end_date, freq="D")

dfs = []

for d in dates:
    print(f"[DOWNLOAD] {d.date()}")
    df_day = download_pse_day(d)

    if not df_day.empty:
        dfs.append(df_day)

    time.sleep(PSE_THROTTLE_SEC)

df_pk5_new = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()

print(f"[OK] Nowe dane: {df_pk5_new.shape}")

# ============================================
# 4. CLASSIFY H / F
# ============================================

if not df_pk5_new.empty:
    df_pk5_new["data_type"] = "F"
    df_pk5_new.loc[
        df_pk5_new["business_date"] <= H_CUTOFF,
        "data_type"
    ] = "H"

    df_pk5_new["snapshot_date"] = TODAY

# ============================================
# 5. MERGE
# ============================================

if df_pk5.empty:
    df_pk5_merged = df_pk5_new.copy()
else:
    all_cols = list(set(df_pk5.columns).union(df_pk5_new.columns))

    df_old = df_pk5.reindex(columns=all_cols)
    df_new = df_pk5_new.reindex(columns=all_cols)

    df_pk5_merged = pd.concat([df_old, df_new], ignore_index=True)

    dedup_keys = ["business_date"]
    if "plan_dtime" in df_pk5_merged.columns:
        dedup_keys.append("plan_dtime")

    sort_cols = dedup_keys + ["snapshot_date"]

    df_pk5_merged = (
        df_pk5_merged
        .sort_values(sort_cols)
        .drop_duplicates(subset=dedup_keys, keep="last")
        .sort_values(dedup_keys)
        .reset_index(drop=True)
    )

print(f"[OK] Master merged: {df_pk5_merged.shape}")

# ============================================
# 6. SAVE MASTER
# ============================================

safe_save(df_pk5_merged, PATH_PK5)

# ============================================
# 7. FORECAST HISTORY
# ============================================

df_forecast_new = df_pk5_merged[df_pk5_merged["data_type"] == "F"].copy()

if not df_forecast_new.empty:

    if os.path.exists(PATH_PK5FOR):
        df_hist = pd.read_parquet(PATH_PK5FOR)
    else:
        df_hist = pd.DataFrame()

    all_cols = list(set(df_hist.columns).union(df_forecast_new.columns))

    df_hist = df_hist.reindex(columns=all_cols)
    df_forecast_new = df_forecast_new.reindex(columns=all_cols)

    df_all = pd.concat([df_hist, df_forecast_new], ignore_index=True)

    dedup_keys = ["business_date", "snapshot_date"]
    if "plan_dtime" in df_all.columns:
        dedup_keys.insert(1, "plan_dtime")

    df_all = (
        df_all
        .sort_values(dedup_keys)
        .drop_duplicates(subset=dedup_keys, keep="last")
        .reset_index(drop=True)
    )

    safe_save(df_all, PATH_PK5FOR)

    print(f"[OK] Forecast DB: {df_all.shape}")

# ============================================
# END
# ============================================

print("[END] Pipeline zakończony")
