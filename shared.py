"""
shared.py — common imports, path constants, loaders, helpers.
Imported by app.py and every pages/*.py module.
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import json, os, calendar
from datetime import date, timedelta, datetime
from functools import lru_cache

# ── Root directory ────────────────────────────────────────────────────────────
APP_DIR = os.path.dirname(os.path.abspath(__file__))

# ── File paths ────────────────────────────────────────────────────────────────
DATA_DIR = os.path.join(APP_DIR, "data")

PARQUET_PATH     = os.path.join(DATA_DIR, "pl_spot", "FixingPricesH.parquet")
PARQUET_QH_PATH  = os.path.join(DATA_DIR, "pl_spot", "FixingPricesQH.parquet")
TRADES_PATH      = os.path.join(APP_DIR, "trades.json")
TSO_TRADES_PATH  = os.path.join(APP_DIR, "tso_trades.json")
CDS_PARAMS_PATH  = os.path.join(APP_DIR, "cds_params.json")
CCS_PARAMS_PATH  = os.path.join(APP_DIR, "ccs_params.json")

DE_PRICES_PATH   = os.path.join(DATA_DIR, "de",      "de_prices.parquet")
EURPLN_PATH      = os.path.join(DATA_DIR, "market",  "EURPLN_Rate.parquet")
PSE_PRICES_PATH  = os.path.join(DATA_DIR, "rb",      "pse_prices.parquet")
PSE_DEMAND_PATH  = os.path.join(DATA_DIR, "pse",     "pse_demand.parquet")
PSE_WLK_PATH     = os.path.join(DATA_DIR, "rb",      "pse_wlk.parquet")
RB_H_PATH        = os.path.join(DATA_DIR, "rb",      "RB_prices_H.parquet")
PSCMI_PATH       = os.path.join(DATA_DIR, "coal",    "pscmi.parquet")
ETS_CO2_PATH     = os.path.join(DATA_DIR, "ets",     "ets_co2.parquet")
OTF_EE_PATH      = os.path.join(DATA_DIR, "otf",    "tge_otf_ee.parquet")
OTF_GAS_PATH     = os.path.join(DATA_DIR, "otf",    "tge_otf_gas.parquet")
DE_SPOT_PATH     = os.path.join(DATA_DIR, "de",      "de_spot.parquet")
DE_EFDE_PATH     = os.path.join(DATA_DIR, "de",      "DE_Price_EnergyForecastDE.parquet")
PK5_PATH         = os.path.join(DATA_DIR, "pse",     "pk5.parquet")
PK5FOR_PATH      = os.path.join(DATA_DIR, "pse",     "pk5for.parquet")
VAR_SPOT_PATH      = os.path.join(APP_DIR,  "app_data", "var", "var_params_spot.parquet")
VAR_RB_PATH        = os.path.join(APP_DIR,  "app_data", "var", "var_params_rb.parquet")
ANCILLARY_PATH     = os.path.join(DATA_DIR, "rb",      "ancillary_prices.parquet")

FC_DIR             = os.path.join(APP_DIR, "fc")
FC_COEFF_PATH      = os.path.join(FC_DIR,  "fc_coefficients.parquet")
FC_CURVES_PATH     = os.path.join(FC_DIR,  "fc_curves.parquet")
FC_CALENDAR_PATH   = os.path.join(FC_DIR,  "calendar_hourly.parquet")

FC_HOURLY_RATIO_PATH    = os.path.join(FC_DIR, "fc_hourly_ratio_params.parquet")
FC_HOURLY_SCHEDULES_DIR = os.path.join(FC_DIR, "fc_hourly_schedules")

DE_FORE_HIST_PATH  = os.environ.get(
    "DE_FORE_HIST_PATH",
    os.path.join(DATA_DIR, "de", "de_forecast_history.parquet"),
)
DE_NETLOAD_PATH    = os.path.join(DATA_DIR, "de", "de_netload.parquet")
DE_TOTALLOAD_PATH  = os.path.join(DATA_DIR, "de", "de_totalload.parquet")

FORECAST_DB_PATH = os.environ.get("FORECAST_DB_PATH", "/home/ubuntu/db/forecast_db.duckdb")
DE_FORE_PATH     = os.environ.get("DE_FORE_PATH",     os.path.join(DATA_DIR, "de", "DE_Price_72H_Forecast.parquet"))

# ── Chart theme ───────────────────────────────────────────────────────────────
CHART_THEME = dict(
    plot_bgcolor="white",
    paper_bgcolor="white",
    font=dict(color="#333"),
)

# ── Helpers ───────────────────────────────────────────────────────────────────
def _otf_delivery_hours(pname: str, ptype: str):
    parts = str(pname).split("-")
    try:
        year = 2000 + int(parts[-1])
    except Exception:
        return None
    try:
        if ptype == "M":
            return calendar.monthrange(year, int(parts[-2]))[1] * 24
        elif ptype == "Q":
            q = int(parts[-2])
            s = (q - 1) * 3 + 1
            return sum(calendar.monthrange(year, m)[1] for m in range(s, s + 3)) * 24
        elif ptype == "Y":
            return (366 if calendar.isleap(year) else 365) * 24
    except Exception:
        return None
    return None

def calc_pnl(direction: str, volume_mw: float, spread: float) -> float:
    """Short = sell F1, buy SDAC → profit when spread > 0
       Long  = buy F1, sell SDAC → profit when spread < 0"""
    sign = 1 if direction == "Short" else -1
    return sign * spread * volume_mw

# ── Polish public holidays (fixed-date + Easter-based movable feasts) ────────
# Verified against examples/Calendar_holidays.pdf for 2026-2030.
@lru_cache(maxsize=32)
def _easter_sunday(year: int) -> date:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)

@lru_cache(maxsize=32)
def pl_holidays(year: int) -> frozenset:
    easter = _easter_sunday(year)
    return frozenset({
        date(year, 1, 1), date(year, 1, 6),
        easter,                        # Easter Sunday
        easter + timedelta(days=1),    # Easter Monday
        date(year, 5, 1), date(year, 5, 3),
        easter + timedelta(days=49),   # Pentecost (Zielone Świątki)
        easter + timedelta(days=60),   # Corpus Christi (Boże Ciało)
        date(year, 8, 15), date(year, 11, 1), date(year, 11, 11),
        date(year, 12, 25), date(year, 12, 26),
    })

def is_workday(d) -> bool:
    """Mon-Fri, excluding Polish public holidays."""
    d = pd.Timestamp(d).date()
    return d.weekday() < 5 and d not in pl_holidays(d.year)

# ── Data loaders ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600)
def load_prices() -> pd.DataFrame:
    df = pd.read_parquet(PARQUET_PATH)
    df["fixing_date"]   = pd.to_datetime(df["fixing_date"]).dt.date
    df["delivery_date"] = pd.to_datetime(df["delivery_date"]).dt.date
    return df

@st.cache_data(ttl=3600)
def load_prices_qh() -> pd.DataFrame:
    if not os.path.exists(PARQUET_QH_PATH):
        return pd.DataFrame()
    df = pd.read_parquet(PARQUET_QH_PATH)
    df["fixing_date"]   = pd.to_datetime(df["fixing_date"]).dt.date
    df["delivery_date"] = pd.to_datetime(df["delivery_date"]).dt.date
    return df

def load_trades() -> list:
    if os.path.exists(TRADES_PATH):
        with open(TRADES_PATH, "r") as f:
            return json.load(f)
    return []

def save_trades(trades: list):
    with open(TRADES_PATH, "w") as f:
        json.dump(trades, f, indent=2, default=str)

def load_tso_trades() -> list:
    if os.path.exists(TSO_TRADES_PATH):
        with open(TSO_TRADES_PATH, "r") as f:
            return json.load(f)
    return []

def save_tso_trades(tso_trades: list):
    with open(TSO_TRADES_PATH, "w") as f:
        json.dump(tso_trades, f, indent=2, default=str)

@st.cache_data(ttl=3600)
def load_de_prices() -> pd.DataFrame:
    if not os.path.exists(DE_PRICES_PATH):
        return pd.DataFrame()
    df = pd.read_parquet(DE_PRICES_PATH)
    df["business_date"] = pd.to_datetime(df["business_date"]).dt.date
    return df

@st.cache_data(ttl=3600)
def load_de_spot() -> pd.DataFrame:
    if not os.path.exists(DE_SPOT_PATH):
        return pd.DataFrame()
    df = pd.read_parquet(DE_SPOT_PATH)
    df["datetime_utc"] = pd.to_datetime(df["datetime_utc"])
    df["date"]         = pd.to_datetime(df["date"]).dt.date
    return df

@st.cache_data(ttl=3600)
def load_eurpln() -> pd.DataFrame:
    if not os.path.exists(EURPLN_PATH):
        return pd.DataFrame()
    df = pd.read_parquet(EURPLN_PATH)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df

@st.cache_data(ttl=3600)
def load_pse() -> pd.DataFrame:
    if not os.path.exists(PSE_PRICES_PATH):
        return pd.DataFrame()
    df = pd.read_parquet(PSE_PRICES_PATH)
    df["dtime"]         = pd.to_datetime(df["dtime"])
    df["business_date"] = pd.to_datetime(df["business_date"]).dt.date
    return df

@st.cache_data(ttl=3600)
def load_pse_demand() -> pd.DataFrame:
    if not os.path.exists(PSE_DEMAND_PATH):
        return pd.DataFrame()
    df = pd.read_parquet(PSE_DEMAND_PATH)
    df["business_date"] = pd.to_datetime(df["business_date"]).dt.date
    df["dtime"]         = pd.to_datetime(df["dtime"])
    for col in ["load_actual", "load_fcst"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df

@st.cache_data(ttl=3600)
def load_pk5() -> pd.DataFrame:
    if not os.path.exists(PK5_PATH):
        return pd.DataFrame()
    df = pd.read_parquet(PK5_PATH)
    df["plan_dtime"]    = pd.to_datetime(df["plan_dtime"])
    df["business_date"] = pd.to_datetime(df["business_date"]).dt.date
    for col in ["fcst_wi_tot_gen", "fcst_pv_tot_gen", "grid_demand_fcst", "pred_gen_res_not_cov"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df

@st.cache_data(ttl=3600)
def load_pk5for() -> pd.DataFrame:
    if not os.path.exists(PK5FOR_PATH):
        return pd.DataFrame()
    df = pd.read_parquet(PK5FOR_PATH)
    df["business_date"] = pd.to_datetime(df["business_date"]).dt.date
    df["snapshot_date"] = pd.to_datetime(df["snapshot_date"]).dt.date
    for col in ["grid_demand_fcst", "fcst_wi_tot_gen", "fcst_pv_tot_gen",
                "planned_exchange", "fcst_unav_energy"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["H"] = df["period"].str[:2].astype(int) + 1
    return df

@st.cache_data(ttl=3600)
def load_rb_h_cached() -> pd.DataFrame:
    if not os.path.exists(RB_H_PATH):
        return pd.DataFrame()
    df = pd.read_parquet(RB_H_PATH)
    df["delivery_date"] = pd.to_datetime(df["delivery_date"]).dt.date
    return df

@st.cache_data(ttl=3600)
def load_pscmi() -> pd.DataFrame:
    if not os.path.exists(PSCMI_PATH):
        return pd.DataFrame()
    df = pd.read_parquet(PSCMI_PATH)
    if len(df) == 0:
        return df
    if df["date"].dtype == "object" and isinstance(df["date"].iloc[0], str):
        df["date"] = pd.to_datetime(df["date"]).dt.date
    elif not isinstance(df["date"].iloc[0], pd.Timestamp):
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    else:
        df["date"] = df["date"].dt.date
    df = df.dropna(subset=["date"])
    return df

@st.cache_data(ttl=3600)
def load_ets() -> pd.DataFrame:
    if not os.path.exists(ETS_CO2_PATH):
        return pd.DataFrame()
    df = pd.read_parquet(ETS_CO2_PATH)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["settlement"] = pd.to_numeric(df["settlement"], errors="coerce")
    return df

@st.cache_data(ttl=3600)
def load_otf_ee() -> pd.DataFrame:
    if not os.path.exists(OTF_EE_PATH):
        return pd.DataFrame()
    df = pd.read_parquet(OTF_EE_PATH)
    df["date"]      = pd.to_datetime(df["date"])
    df["price"]     = pd.to_numeric(df["dkr"],    errors="coerce")
    df["trades"]    = pd.to_numeric(df["trades"], errors="coerce")
    _hrs = df.apply(lambda r: _otf_delivery_hours(r["product_name"], r["product_type"]), axis=1)
    df["quantity_mw"] = (pd.to_numeric(df["vol_mwh"], errors="coerce") / _hrs).round(1)
    df["is_traded"] = pd.to_numeric(df["vol_mwh"], errors="coerce").fillna(0) > 0
    df = df[df["date"].dt.weekday < 5]
    return df

@st.cache_data(ttl=3600)
def load_ancillary() -> pd.DataFrame:
    if not os.path.exists(ANCILLARY_PATH):
        return pd.DataFrame()
    df = pd.read_parquet(ANCILLARY_PATH)
    df["business_date"] = pd.to_datetime(df["business_date"]).dt.date
    for c in ["fcr_g","fcr_d","afrr_g","afrr_d","mfrrd_g","mfrrd_d","rr_g","rr_d"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

@st.cache_data(ttl=3600)
def load_otf_gas() -> pd.DataFrame:
    if not os.path.exists(OTF_GAS_PATH):
        return pd.DataFrame()
    df = pd.read_parquet(OTF_GAS_PATH)
    df["date"]        = pd.to_datetime(df["date"])
    df["price"]       = pd.to_numeric(df["DKR (PLN/MWh)"],    errors="coerce")
    df["trades"]      = pd.to_numeric(df["Liczba kontraktów"], errors="coerce")
    df["quantity_mw"] = df["trades"]
    df["is_traded"]   = df["trades"].fillna(0) > 0
    df = df[df["date"].dt.weekday < 5]
    return df
