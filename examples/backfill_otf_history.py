"""
backfill_otf_history.py
-----------------------
One-time script: import historical TGE OTF data from CSV files into parquets.

Sources : examples/TGE_Market_Data/2020.csv … 2026.csv
Targets : prices/tge_otf_ee.parquet
          prices/tge_otf_gas.parquet

Only data BEFORE the earliest date already in each parquet is imported
(no overwriting of scraped data).

EE  : BASE, PEAK5, OFFPEAK (M / Q / Y)
Gas : GAS_BASE M / Q / Y / S (seasonal Summer/Winter)

Column mapping (CSV → parquet):
  dkr / DKR         : Last  (if Last > 0)  else  Slmnt
  trades             : Trades
  vol_mwh / wolumen  : Quantity × hours_in_delivery_period
  lop_mwh / LOP      : O/I   × hours_in_delivery_period
  min / max          : Low / High  (NaN when 0)
  value_pln / wartość: Trade qty × 100  (matches existing parquet scale)
"""

import os, re, calendar
import pandas as pd
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
APP_DIR     = Path(__file__).resolve().parent.parent
EE_PARQUET  = APP_DIR / "prices" / "tge_otf_ee.parquet"
GAS_PARQUET = APP_DIR / "prices" / "tge_otf_gas.parquet"
CSV_DIR     = Path(__file__).resolve().parent / "TGE_Market_Data"


# ── Helpers ────────────────────────────────────────────────────────────────────

def delivery_hours(product_type: str, instrument: str):
    """Hours in the delivery period, derived from the instrument name."""
    parts = instrument.split("-")
    try:
        year = 2000 + int(parts[-1])
    except Exception:
        return None

    try:
        if product_type == "M":
            month = int(parts[-2])
            return calendar.monthrange(year, month)[1] * 24

        elif product_type == "Q":
            q = int(parts[-2])
            start_m = (q - 1) * 3 + 1
            return sum(calendar.monthrange(year, m)[1] for m in range(start_m, start_m + 3)) * 24

        elif product_type == "Y":
            return (366 if calendar.isleap(year) else 365) * 24

        elif product_type == "S":
            season = parts[-2].upper()
            if season == "S":   # Summer: Apr–Sep
                return sum(calendar.monthrange(year, m)[1] for m in range(4, 10)) * 24
            elif season == "W": # Winter: Oct–Mar (year+1)
                oct_dec = sum(calendar.monthrange(year,     m)[1] for m in range(10, 13))
                jan_mar = sum(calendar.monthrange(year + 1, m)[1] for m in range(1,  4))
                return (oct_dec + jan_mar) * 24
    except Exception:
        return None
    return None


def parse_dkr(row) -> float:
    """DKR = Last when traded, else settlement (Slmnt)."""
    last  = float(row.get("Last",  0) or 0)
    slmnt = float(row.get("Slmnt", 0) or 0)
    if last  > 0: return last
    if slmnt > 0: return slmnt
    return float("nan")


def zero_to_nan(series: pd.Series) -> pd.Series:
    """Replace 0 with NaN (used for price columns with no trading)."""
    return pd.to_numeric(series, errors="coerce").replace(0.0, float("nan"))


# ── Load all CSVs ──────────────────────────────────────────────────────────────
print("Loading CSV files …")
frames = []
for year in range(2020, 2027):
    path = CSV_DIR / f"{year}.csv"
    df = pd.read_csv(path, sep=";", encoding="utf-8", decimal=",")
    df["Date"] = pd.to_datetime(df["Date"], format="%d.%m.%Y")
    frames.append(df)

all_csv = pd.concat(frames, ignore_index=True)
print(f"  Total rows: {len(all_csv):,}  |  date range: {all_csv['Date'].min().date()} – {all_csv['Date'].max().date()}")


# ══════════════════════════════════════════════════════════════════════════════
# EE BACKFILL
# ══════════════════════════════════════════════════════════════════════════════
print("\n=== OTF EE ===")

df_ee_exist = pd.read_parquet(EE_PARQUET)
df_ee_exist["date"] = pd.to_datetime(df_ee_exist["date"])
ee_cutoff = df_ee_exist["date"].min()
print(f"  Existing rows : {len(df_ee_exist):,}  |  earliest: {ee_cutoff.date()}")

# Filter: EE M/Q/Y markets, strictly before cutoff
EE_MARKET_PAT = r"^(BASE|PEAK5?|OFFPEAK|H-PEAK5?|L-PEAK5?)_(M|Q|Y)$"
ee_raw = all_csv[
    all_csv["Market"].str.match(EE_MARKET_PAT, na=False) &
    (all_csv["Date"] < ee_cutoff)
].copy()
print(f"  CSV rows to import (before {ee_cutoff.date()}): {len(ee_raw):,}")

if not ee_raw.empty:
    # Derive typed columns
    ee_raw["product_type"] = ee_raw["Market"].str.extract(r"_(M|Q|Y)$")[0]
    ee_raw["segment"]      = ee_raw["Instrument"].str.split("_").str[0]
    ee_raw["dkr_val"]      = ee_raw.apply(parse_dkr, axis=1)

    ee_raw["_hours"] = ee_raw.apply(
        lambda r: delivery_hours(r["product_type"], str(r["Instrument"])), axis=1
    )
    ee_raw["vol_mwh_val"] = pd.to_numeric(ee_raw["Quantity"], errors="coerce") * ee_raw["_hours"]
    ee_raw["lop_mwh_val"] = pd.to_numeric(ee_raw["O/I"],      errors="coerce") * ee_raw["_hours"]

    df_ee_new = pd.DataFrame({
        "date":         pd.to_datetime(ee_raw["Date"]),
        "product_name": ee_raw["Instrument"].astype("string"),
        "segment":      ee_raw["segment"].astype(object),
        "product_type": ee_raw["product_type"].astype(object),
        "dkr":          pd.to_numeric(ee_raw["dkr_val"],     errors="coerce").astype("Float64"),
        "vol_mwh":      pd.to_numeric(ee_raw["vol_mwh_val"], errors="coerce").astype("Float64"),
        "trades":       pd.to_numeric(ee_raw["Trades"],      errors="coerce").astype("Float64"),
        "value_pln":    (pd.to_numeric(ee_raw["Trade qty"],  errors="coerce") * 100).astype("Float64"),
        "lop_mwh":      pd.to_numeric(ee_raw["lop_mwh_val"], errors="coerce").astype("Float64"),
        "min_price":    zero_to_nan(ee_raw["Low"]).astype("Float64"),
        "max_price":    zero_to_nan(ee_raw["High"]).astype("Float64"),
    })

    df_ee_new = df_ee_new.dropna(subset=["dkr"])
    print(f"  New rows after dkr filter : {len(df_ee_new):,}")

    # Merge + dedup (existing rows win on duplicate date/product_name)
    df_ee_all = pd.concat([df_ee_new, df_ee_exist], ignore_index=True)
    df_ee_all["date"] = pd.to_datetime(df_ee_all["date"])
    df_ee_all = (
        df_ee_all
        .drop_duplicates(subset=["date", "product_name"], keep="last")
        .sort_values(["date", "product_name"])
        .reset_index(drop=True)
    )
    print(f"  Total after merge : {len(df_ee_all):,}  |  range: {df_ee_all['date'].min().date()} – {df_ee_all['date'].max().date()}")

    tmp = str(EE_PARQUET) + ".tmp"
    df_ee_all.to_parquet(tmp, index=False)
    os.replace(tmp, str(EE_PARQUET))
    print(f"  Saved: {EE_PARQUET}")
else:
    print("  Nothing to import.")


# ══════════════════════════════════════════════════════════════════════════════
# GAS BACKFILL
# ══════════════════════════════════════════════════════════════════════════════
print("\n=== OTF GAS ===")

df_gas_exist = pd.read_parquet(GAS_PARQUET)
df_gas_exist["date"] = pd.to_datetime(df_gas_exist["date"])
gas_cutoff = df_gas_exist["date"].min()
gas_cols   = df_gas_exist.columns.tolist()
print(f"  Existing rows : {len(df_gas_exist):,}  |  earliest: {gas_cutoff.date()}")

# Resolve Polish column names from the parquet (robust to encoding)
def _find_col(cols, *keywords):
    for kw in keywords:
        for c in cols:
            if kw.lower() in c.lower():
                return c
    raise KeyError(f"Column not found for keywords {keywords}")

col_open      = _find_col(gas_cols, "pierwszej")
col_dkr       = _find_col(gas_cols, "DKR")
col_min       = _find_col(gas_cols, "min.")
col_max       = _find_col(gas_cols, "maks.")
col_vol       = _find_col(gas_cols, "wolumen")
col_contracts = _find_col(gas_cols, "kontraktów", "kontraktow", "kontraktów")
col_value     = _find_col(gas_cols, "wartość", "wartosci", "warto")
col_trans     = _find_col(gas_cols, "transakcji")
col_lop       = _find_col(gas_cols, "LOP")

# Filter: GAS M/Q/Y/S markets, strictly before cutoff
GAS_MARKET_PAT = r"^GAS_BASE_(M|Q|Y|S)$"
gas_raw = all_csv[
    all_csv["Market"].str.match(GAS_MARKET_PAT, na=False) &
    (all_csv["Date"] < gas_cutoff)
].copy()
print(f"  CSV rows to import (before {gas_cutoff.date()}): {len(gas_raw):,}")

if not gas_raw.empty:
    # Parse contract components (mirrors tge_otf_gas.py pipeline)
    _split = gas_raw["Instrument"].str.split("_", expand=True)
    gas_raw["segment"]      = _split[0]                                 # GAS
    gas_raw["profile"]      = _split[1]                                 # BASE
    _period                 = _split[2]                                 # M-01-26 / Q-1-26 / Y-26 / S-S-26
    gas_raw["product_type"] = _period.str[0]                           # M / Q / Y / S
    gas_raw["product_week"] = pd.to_numeric(
        _period.str.extract(r"W-(\d+)")[0], errors="coerce"
    )
    gas_raw["product_year"] = pd.to_numeric(
        "20" + _period.str.extract(r"-(\d+)$")[0], errors="coerce"
    ).astype("Int64")

    gas_raw["dkr_val"] = gas_raw.apply(parse_dkr, axis=1)
    gas_raw["_hours"]  = gas_raw.apply(
        lambda r: delivery_hours(r["product_type"], str(r["Instrument"])), axis=1
    )
    gas_raw["vol_val"] = pd.to_numeric(gas_raw["Quantity"], errors="coerce") * gas_raw["_hours"]
    gas_raw["lop_val"] = pd.to_numeric(gas_raw["O/I"],      errors="coerce") * gas_raw["_hours"]

    df_gas_new = pd.DataFrame({
        "Kontrakt":    gas_raw["Instrument"],
        col_open:      zero_to_nan(gas_raw["Open"]),
        col_dkr:       pd.to_numeric(gas_raw["dkr_val"],   errors="coerce"),
        col_min:       zero_to_nan(gas_raw["Low"]),
        col_max:       zero_to_nan(gas_raw["High"]),
        col_vol:       pd.to_numeric(gas_raw["vol_val"],   errors="coerce"),
        col_contracts: pd.to_numeric(gas_raw["Quantity"],  errors="coerce"),
        col_value:     pd.to_numeric(gas_raw["Trade qty"], errors="coerce") * 100,
        col_trans:     pd.to_numeric(gas_raw["Trades"],    errors="coerce"),
        col_lop:       pd.to_numeric(gas_raw["lop_val"],   errors="coerce"),
        "date":         pd.to_datetime(gas_raw["Date"]),
        "segment":      gas_raw["segment"],
        "profile":      gas_raw["profile"],
        "product_type": gas_raw["product_type"],
        "product_week": gas_raw["product_week"],
        "product_year": gas_raw["product_year"],
    })

    df_gas_new = df_gas_new.dropna(subset=[col_dkr])
    print(f"  New rows after dkr filter : {len(df_gas_new):,}")

    # Merge + dedup (existing rows win)
    df_gas_all = pd.concat([df_gas_new, df_gas_exist], ignore_index=True)
    df_gas_all["date"] = pd.to_datetime(df_gas_all["date"])
    df_gas_all = (
        df_gas_all
        .drop_duplicates(subset=["date", "Kontrakt"], keep="last")
        .sort_values(["date", "Kontrakt"])
        .reset_index(drop=True)
    )
    print(f"  Total after merge : {len(df_gas_all):,}  |  range: {df_gas_all['date'].min().date()} – {df_gas_all['date'].max().date()}")

    tmp = str(GAS_PARQUET) + ".tmp"
    df_gas_all.to_parquet(tmp, index=False)
    os.replace(tmp, str(GAS_PARQUET))
    print(f"  Saved: {GAS_PARQUET}")
else:
    print("  Nothing to import.")

print("\nDone.")
