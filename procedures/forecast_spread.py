# -*- coding: utf-8 -*-
"""
Spread Forecast Pipeline — EnergyQuant

Forecasts the F1-SDAC spread (Fixing1 - Fixing2) DIRECTLY as a single target,
instead of subtracting two independently-trained F1/F2 price models (which
compounds their individual errors). Writes results to the SAME DuckDB file
as forecast.py, in separate tables (spread_runs, spread_forecast_prices) so
both pipelines coexist without schema conflicts.

Standalone (procedures/ scripts are self-contained — no shared.py import,
holiday calendar is duplicated here intentionally, same as elsewhere).

Callable:
    from procedures.forecast_spread import run_pipeline
    result = run_pipeline(log=print)

Standalone:
    python procedures/forecast_spread.py
"""

import os
import warnings
import datetime
from datetime import date, timedelta
from functools import lru_cache

import numpy as np
import pandas as pd
import duckdb
from sklearn.tree import DecisionTreeRegressor
from sklearn.ensemble import RandomForestRegressor
from statsmodels.tsa.statespace.sarimax import SARIMAX
import xgboost as xgb

warnings.filterwarnings("ignore")

RANDOM_SEED     = 42
DEFAULT_DB_PATH = "/home/ubuntu/db/forecast_db.duckdb"
# Forward-looking DE price forecast (next ~72h), generated daily at 07:10 by
# DE_forecast.py — lets the spread model use a real DE forecast for the near
# term instead of falling back to the historical median for the whole horizon.
DE_FORE_PATH = os.environ.get("DE_FORE_PATH", "/home/ubuntu/data/de/DE_Price_72H_Forecast.parquet")

FEATURES = [
    "RL",
    "Prognozowane zapotrzebowanie sieci [MW]",
    "Generacja PV [MW]",
    "Generacja wiatrowa [MW]",
    "Wymiana systemowa [MW]",
    "Niedyspozycyjność sieci [MW]",
    "Nadwyzka nad WRM [MW]",
    "DE_spot_PLN",
    "CEN_lag24",
    "wind_share",
    "pv_share",
    "hour",
    "weekday",
    "month",
    "is_weekend",
    "is_holiday",
    "spread_lag24",
    "spread_lag168",
    "spread_roll24_std",
]

EXOG_COLS = [
    "RL",
    "Prognozowane zapotrzebowanie sieci [MW]",
    "Generacja PV [MW]",
    "Generacja wiatrowa [MW]",
    "wind_share",
    "pv_share",
    "Nadwyzka nad WRM [MW]",
    "DE_spot_PLN",
    "CEN_lag24",
]


# ── Polish public holidays — duplicated from shared.py (procedures/ scripts
# are standalone and don't import shared.py, same convention as elsewhere) ──
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
def _pl_holidays(year: int) -> frozenset:
    easter = _easter_sunday(year)
    return frozenset({
        date(year, 1, 1), date(year, 1, 6),
        easter, easter + timedelta(days=1),
        date(year, 5, 1), date(year, 5, 3),
        easter + timedelta(days=49), easter + timedelta(days=60),
        date(year, 8, 15), date(year, 11, 1), date(year, 11, 11),
        date(year, 12, 25), date(year, 12, 26),
    })

def _is_workday(d) -> bool:
    d = pd.Timestamp(d).date()
    return d.weekday() < 5 and d not in _pl_holidays(d.year)


# ── Step 1: Load raw inputs ───────────────────────────────────────────────────

def _load_pk5(app_dir, log):
    path = os.path.join(app_dir, "data", "pse", "pk5.parquet")
    if not os.path.exists(path):
        raise FileNotFoundError(f"PK5 file not found: {path}")
    df = pd.read_parquet(path)
    df["business_date"] = pd.to_datetime(df["business_date"]).dt.date
    df["snapshot_date"] = pd.to_datetime(df["snapshot_date"]).dt.date
    df["H"] = df["period"].str[:2].astype(int) + 1
    df = df.sort_values("snapshot_date").drop_duplicates(["business_date", "H"], keep="last")

    keep = ["business_date", "H", "plan_dtime", "grid_demand_fcst",
            "fcst_pv_tot_gen", "fcst_wi_tot_gen", "planned_exchange",
            "fcst_unav_energy", "gen_surplus_avail_tso_above"]
    df = df[keep].rename(columns={
        "grid_demand_fcst": "Prognozowane zapotrzebowanie sieci [MW]",
        "fcst_pv_tot_gen":  "Generacja PV [MW]",
        "fcst_wi_tot_gen":  "Generacja wiatrowa [MW]",
        "planned_exchange": "Wymiana systemowa [MW]",
        "fcst_unav_energy": "Niedyspozycyjność sieci [MW]",
        "gen_surplus_avail_tso_above": "Nadwyzka nad WRM [MW]",
    })
    log(f"[OK] PK5 loaded: {len(df)} rows")
    return df


def _load_fixing(app_dir, log):
    path = os.path.join(app_dir, "data", "pl_spot", "FixingPricesH.parquet")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Fixing prices file not found: {path}")
    df = pd.read_parquet(path)
    df["delivery_date"] = pd.to_datetime(df["delivery_date"]).dt.date
    df = df.sort_values("fixing_date").drop_duplicates(["delivery_date", "H"], keep="last")
    df = df.rename(columns={"delivery_date": "business_date"})
    log(f"[OK] Fixing prices loaded: {len(df)} rows")
    return df[["business_date", "H", "f1_price_PLN", "sdac_price_PLN"]]


def _load_de_spot_pln(app_dir, log):
    """Realized DE day-ahead price, converted to PLN/MWh.

    Uses de_prices.parquet (Electricity Maps / Nordpool — already hour 1-24,
    business_date keyed, updated daily). de_spot.parquet (netztransparenz.de)
    was tried first but currently lags by weeks due to a real publication
    delay on that source's side, which badly truncated training history."""
    de_path = os.path.join(app_dir, "data", "de", "de_prices.parquet")
    fx_path = os.path.join(app_dir, "data", "market", "EURPLN_Rate.parquet")
    if not os.path.exists(de_path) or not os.path.exists(fx_path):
        log("[WARN] DE prices or EUR/PLN file missing — DE_spot_PLN will be NaN")
        return pd.DataFrame(columns=["business_date", "H", "DE_spot_PLN"])

    de = pd.read_parquet(de_path)
    de["business_date"] = pd.to_datetime(de["business_date"]).dt.date
    de = de.rename(columns={"hour": "H"})
    de = de.groupby(["business_date", "H"])["price_eur"].mean().reset_index()

    fx = pd.read_parquet(fx_path)
    fx["date"] = pd.to_datetime(fx["date"]).dt.date
    fx = fx[["date", "rate"]].rename(columns={"date": "business_date"})

    de = de.merge(fx, on="business_date", how="left").sort_values("business_date")
    de["rate"] = de["rate"].ffill()
    de["DE_spot_PLN"] = de["price_eur"] * de["rate"]   # live NBP rate, not the file's own static-rate price_pln
    log(f"[OK] DE prices (Electricity Maps, PLN) loaded: {len(de)} rows")
    return de[["business_date", "H", "DE_spot_PLN"]]


def _load_cen_lag24(app_dir, log):
    path = os.path.join(app_dir, "data", "rb", "RB_prices_H.parquet")
    if not os.path.exists(path):
        log("[WARN] RB_prices_H file missing — CEN_lag24 will be NaN")
        return pd.DataFrame(columns=["business_date", "H", "CEN_lag24"])
    df = pd.read_parquet(path)
    df["delivery_date"] = pd.to_datetime(df["delivery_date"]).dt.date
    df = df[["delivery_date", "H", "cen_cost"]].rename(columns={"cen_cost": "CEN_lag24"})
    df["business_date"] = df["delivery_date"] + timedelta(days=1)   # yesterday's CEN -> today's feature
    log(f"[OK] CEN lag24 source loaded: {len(df)} rows")
    return df[["business_date", "H", "CEN_lag24"]]


def _load_de_forecast_pln(log):
    """Forward-looking DE price forecast (next ~72h, already PLN-converted).
    Used to fill DE_spot_PLN for forecast days instead of the (otherwise
    NaN -> historical-median) realized DE spot price, which doesn't exist yet
    for future delivery dates."""
    if not os.path.exists(DE_FORE_PATH):
        log(f"[WARN] DE 72H forecast not found at {DE_FORE_PATH} — "
            "forecast days will fall back to historical DE median")
        return pd.DataFrame(columns=["business_date", "H", "DE_spot_PLN_fc"])
    df = pd.read_parquet(DE_FORE_PATH)
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True).dt.tz_convert("Europe/Warsaw")
    df["business_date"] = df["datetime"].dt.date
    df["H"] = df["datetime"].dt.hour + 1
    df = df.groupby(["business_date", "H"])["PricePL"].mean().reset_index()
    df = df.rename(columns={"PricePL": "DE_spot_PLN_fc"})
    log(f"[OK] DE 72H forecast loaded: {len(df)} rows")
    return df[["business_date", "H", "DE_spot_PLN_fc"]]


# ── Step 2: Build spread_features_raw ────────────────────────────────────────

def _build_features(app_dir, log):
    pk5 = _load_pk5(app_dir, log)
    fix = _load_fixing(app_dir, log)
    de  = _load_de_spot_pln(app_dir, log)
    cen = _load_cen_lag24(app_dir, log)

    df = pk5.merge(fix, on=["business_date", "H"], how="left")
    df = df.merge(de,  on=["business_date", "H"], how="left")
    df = df.merge(cen, on=["business_date", "H"], how="left")

    df["Timestamp"] = pd.to_datetime(df["plan_dtime"])
    df = df.drop(columns=["plan_dtime"]).set_index("Timestamp").sort_index()
    df["Spread"] = df["f1_price_PLN"] - df["sdac_price_PLN"]
    df["RL"] = (df["Prognozowane zapotrzebowanie sieci [MW]"]
                - df["Generacja PV [MW]"] - df["Generacja wiatrowa [MW]"])

    log(f"[OK] spread_features_raw: {df.shape}")
    return df


# ── Step 3: Feature engineering (history side) ───────────────────────────────

def _feature_engineering(df, log):
    df_fe = df.copy()

    # Derive calendar features from business_date/H, NOT the Timestamp index —
    # PK5's plan_dtime for H=24 (period "23-24") is midnight of the NEXT day,
    # so index.hour/.weekday/.month would silently read the wrong day for the
    # last hour of every single day.
    _bd = pd.to_datetime(df_fe["business_date"])
    df_fe["hour"]       = df_fe["H"] - 1
    df_fe["weekday"]    = _bd.dt.weekday.values
    df_fe["month"]      = _bd.dt.month.values
    df_fe["is_weekend"] = (df_fe["weekday"] >= 5).astype(int)
    df_fe["is_holiday"] = (~df_fe["business_date"].apply(_is_workday)).astype(int)

    df_fe["spread_lag24"]  = df_fe["Spread"].shift(24)
    df_fe["spread_lag168"] = df_fe["Spread"].shift(168)
    # shift(1) before rolling so the window never includes the row's own
    # (possibly NaN, for future rows) value — avoids look-ahead leakage.
    df_fe["spread_roll24_std"] = df_fe["Spread"].shift(1).rolling(24, min_periods=24).std()

    demand = df_fe["Prognozowane zapotrzebowanie sieci [MW]"]
    df_fe["wind_share"] = df_fe["Generacja wiatrowa [MW]"] / demand.replace(0, pd.NA)
    df_fe["pv_share"]   = df_fe["Generacja PV [MW]"]       / demand.replace(0, pd.NA)

    before = len(df_fe)
    df_fe = df_fe.dropna(subset=["Spread"] + FEATURES)
    log(f"[OK] Feature engineering done. Dropped {before - len(df_fe)} rows. Shape: {df_fe.shape}")
    return df_fe


# ── Step 4: History / forecast split ─────────────────────────────────────────

def _split_data(df_fe, df, forecast_start, forecast_end, log, de_forecast=None):
    # Split on business_date, NOT the Timestamp index — see note in
    # _feature_engineering about PK5's H=24 midnight-of-next-day quirk.
    mask_hist = df_fe["business_date"] < forecast_start
    df_hist   = df_fe[mask_hist].copy()

    mask_future = (df["business_date"] >= forecast_start) & (df["business_date"] <= forecast_end)
    df_forecast = df[mask_future].copy()

    _bd_fc = pd.to_datetime(df_forecast["business_date"])
    df_forecast["hour"]       = df_forecast["H"] - 1
    df_forecast["weekday"]    = _bd_fc.dt.weekday.values
    df_forecast["month"]      = _bd_fc.dt.month.values
    df_forecast["is_weekend"] = (df_forecast["weekday"] >= 5).astype(int)
    df_forecast["is_holiday"] = (~df_forecast["business_date"].apply(_is_workday)).astype(int)

    # Lag/rolling features need the FULL series (history+future) so future
    # rows correctly reference already-realized past spread values.
    full_lag24  = df["Spread"].shift(24)
    full_lag168 = df["Spread"].shift(168)
    full_roll   = df["Spread"].shift(1).rolling(24, min_periods=24).std()
    df_forecast["spread_lag24"]      = full_lag24.reindex(df_forecast.index)
    df_forecast["spread_lag168"]     = full_lag168.reindex(df_forecast.index)
    df_forecast["spread_roll24_std"] = full_roll.reindex(df_forecast.index)

    demand_fc = df_forecast["Prognozowane zapotrzebowanie sieci [MW]"]
    df_forecast["wind_share"] = df_forecast["Generacja wiatrowa [MW]"] / demand_fc.replace(0, pd.NA)
    df_forecast["pv_share"]   = df_forecast["Generacja PV [MW]"]       / demand_fc.replace(0, pd.NA)

    # DE_spot_PLN is the REALIZED price (NaN for future dates by construction).
    # Where a genuine DE 72H forecast covers the same (business_date, H), use
    # it instead of leaving the gap for the later historical-median fallback.
    if de_forecast is not None and not de_forecast.empty:
        de_fc_map = de_forecast.set_index(["business_date", "H"])["DE_spot_PLN_fc"]
        fc_keys   = pd.MultiIndex.from_arrays([df_forecast["business_date"], df_forecast["H"]])
        de_fc_vals = pd.Series(de_fc_map.reindex(fc_keys).values, index=df_forecast.index)
        n_filled = de_fc_vals.notna().sum()
        df_forecast["DE_spot_PLN"] = df_forecast["DE_spot_PLN"].fillna(de_fc_vals)
        log(f"[OK] DE 72H forecast applied to {n_filled}/{len(df_forecast)} forecast rows")

    if len(df_hist) == 0:
        raise ValueError("No historical data for training.")
    if len(df_forecast) == 0:
        raise ValueError(f"No forecast data for {forecast_start} -> {forecast_end}.")

    missing = set(FEATURES) - set(df_forecast.columns)
    if missing:
        raise ValueError(f"Missing features in forecast period: {missing}")

    y_hist     = df_hist["Spread"]
    X_hist     = df_hist[FEATURES]
    X_forecast = df_forecast[FEATURES]

    if X_forecast.isna().any().any():
        X_forecast = X_forecast.fillna(X_hist.median())

    log(f"[OK] Split done. X_hist: {X_hist.shape}, X_forecast: {X_forecast.shape}")
    return df_hist, df_forecast, X_hist, y_hist, X_forecast


# ── Step 5: Train all models ──────────────────────────────────────────────────

def _sanitize_cols(df):
    df = df.copy()
    df.columns = [
        c.replace("[", "").replace("]", "").replace("<", "")
         .replace(" ", "_").replace("-", "_")
        for c in df.columns
    ]
    return df


def _train_models(X_hist, y_hist, X_forecast, df_hist, df_forecast, log):
    results = {}

    log("[MODEL 1/4] DecisionTreeRegressor ...")
    dt = DecisionTreeRegressor(
        max_depth=7, min_samples_split=10, min_samples_leaf=5,
        random_state=RANDOM_SEED,
    )
    dt.fit(X_hist, y_hist)
    results["DT"] = pd.Series(dt.predict(X_forecast), index=X_forecast.index)
    log(f"[OK] DT done — {len(results['DT'])} forecasts")

    log("[MODEL 2/4] RandomForestRegressor ...")
    rf = RandomForestRegressor(
        n_estimators=300, max_depth=12, min_samples_split=10, min_samples_leaf=5,
        random_state=RANDOM_SEED, n_jobs=-1,
    )
    rf.fit(X_hist, y_hist)
    results["RF"] = pd.Series(rf.predict(X_forecast), index=X_forecast.index)
    log("[OK] RF done")

    log("[MODEL 3/4] XGBoostRegressor ...")
    X_hist_xgb     = _sanitize_cols(X_hist)
    X_forecast_xgb = _sanitize_cols(X_forecast)
    xgb_model = xgb.XGBRegressor(
        n_estimators=300, learning_rate=0.05, max_depth=7,
        subsample=0.8, colsample_bytree=0.8,
        random_state=RANDOM_SEED, n_jobs=-1,
    )
    xgb_model.fit(X_hist_xgb, y_hist)
    results["XGB"] = pd.Series(xgb_model.predict(X_forecast_xgb), index=X_forecast.index)
    log("[OK] XGB done")

    log("[MODEL 4/4] SARIMAX (may take several minutes) ...")
    y_sar         = df_hist["Spread"].astype(float)
    exog_hist_s   = df_hist[EXOG_COLS].astype(float)
    exog_future_s = df_forecast[EXOG_COLS].astype(float)

    exog_hist_s   = exog_hist_s.replace([np.inf, -np.inf], np.nan)
    exog_future_s = exog_future_s.replace([np.inf, -np.inf], np.nan)

    mask_ok     = y_sar.notna() & exog_hist_s.notna().all(axis=1)
    y_sar       = y_sar.loc[mask_ok]
    exog_hist_s = exog_hist_s.loc[mask_ok]

    # DE_spot_PLN and CEN_lag24 are lagged REALIZED values — structurally
    # unknown for future delivery dates, so the whole forecast-period column
    # can be 100% NaN. Filling with the future slice's OWN median would still
    # be NaN in that case; fall back to the HISTORICAL median instead (same
    # pattern _split_data already uses for the tree-model features).
    if exog_future_s.isna().any().any():
        exog_future_s = exog_future_s.fillna(exog_hist_s.median())

    sar_model = SARIMAX(
        endog=y_sar, exog=exog_hist_s,
        order=(1, 1, 1), seasonal_order=(1, 0, 1, 24),
        enforce_stationarity=False, enforce_invertibility=False,
    )
    sar_fit = sar_model.fit(disp=False)
    sar_fc  = sar_fit.forecast(steps=len(exog_future_s), exog=exog_future_s)
    results["SARIMAX"] = pd.Series(np.asarray(sar_fc, dtype=float), index=exog_future_s.index)
    log("[OK] SARIMAX done")

    return results


# ── Step 6: Write to DuckDB ───────────────────────────────────────────────────

def _write_to_db(con, forecast_start, forecast_end, last_spread_date, model_results, log):
    con.execute("""
CREATE TABLE IF NOT EXISTS spread_runs (
    run_id           VARCHAR PRIMARY KEY,
    snapshot_ts      TIMESTAMP,
    snapshot_date    DATE,
    forecast_start   DATE,
    forecast_end     DATE,
    last_spread_date DATE
)""")
    con.execute("""
CREATE TABLE IF NOT EXISTS spread_forecast_prices (
    run_id         VARCHAR,
    ts             TIMESTAMP,
    model          VARCHAR,
    spread_pln_mwh DOUBLE
)""")
    try:
        con.execute("CREATE INDEX IF NOT EXISTS idx_spread_prices_run_ts ON spread_forecast_prices(run_id, ts)")
    except Exception:
        pass

    run_id      = datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + "_SPREAD"
    snapshot_ts = datetime.datetime.now()

    con.execute("DELETE FROM spread_forecast_prices WHERE run_id = ?", [run_id])
    con.execute("DELETE FROM spread_runs            WHERE run_id = ?", [run_id])

    runs_row = pd.DataFrame([{
        "run_id":           run_id,
        "snapshot_ts":      snapshot_ts,
        "snapshot_date":    snapshot_ts.date(),
        "forecast_start":   forecast_start,
        "forecast_end":     forecast_end,
        "last_spread_date": last_spread_date,
    }])

    price_frames = []
    for model_name, series in model_results.items():
        price_frames.append(pd.DataFrame({
            "ts": series.index, "spread_pln_mwh": series.values,
            "model": model_name, "run_id": run_id,
        }))
    prices_all = pd.concat(price_frames, ignore_index=True)
    prices_all["ts"]             = pd.to_datetime(prices_all["ts"])
    prices_all["spread_pln_mwh"] = pd.to_numeric(prices_all["spread_pln_mwh"], errors="coerce").astype(float)

    con.register("_spread_runs_row", runs_row)
    con.register("_spread_prices_all", prices_all)
    con.execute("INSERT INTO spread_runs SELECT * FROM _spread_runs_row")
    con.execute("INSERT INTO spread_forecast_prices SELECT run_id, ts, model, spread_pln_mwh FROM _spread_prices_all")

    return run_id


# ── Entry point ───────────────────────────────────────────────────────────────

def run_pipeline(db_path=None, app_dir=None, log=print):
    """
    Full spread forecast pipeline: load -> features -> 4 models -> DuckDB write.

    Returns dict {"status": "ok"|"error", "message": str, "run_id": str|None}
    """
    if db_path is None:
        db_path = DEFAULT_DB_PATH
    if app_dir is None:
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    log("=== SPREAD FORECAST PIPELINE START ===")
    log(f"DB: {db_path}")

    try:
        df = _build_features(app_dir, log)

        # Use business_date, not the Timestamp index (see note in
        # _feature_engineering — PK5's H=24 plan_dtime is next-day midnight).
        last_spread_date = df.loc[df["Spread"].notna(), "business_date"].max()
        forecast_start    = last_spread_date + timedelta(days=1)
        forecast_end      = df["business_date"].max()
        log(f"[INFO] Last spread date: {last_spread_date}")
        log(f"[INFO] Forecast: {forecast_start} -> {forecast_end} "
            f"({(forecast_end - forecast_start).days + 1} days)")

        log("[STEP] Feature engineering ...")
        df_fe = _feature_engineering(df, log)

        de_forecast = _load_de_forecast_pln(log)

        log("[STEP] Splitting history / forecast ...")
        df_hist, df_forecast, X_hist, y_hist, X_forecast = _split_data(
            df_fe, df, forecast_start, forecast_end, log, de_forecast=de_forecast
        )

        log("[STEP] Training models ...")
        model_results = _train_models(X_hist, y_hist, X_forecast, df_hist, df_forecast, log)

        log("[STEP] Writing to DuckDB ...")
        con = duckdb.connect(db_path, read_only=False)
        run_id = _write_to_db(con, forecast_start, forecast_end, last_spread_date, model_results, log)
        try:
            con.execute("CHECKPOINT")
        except Exception:
            pass
        con.close()

        msg = f"Spread forecast: {forecast_start} -> {forecast_end}. run_id={run_id}"
        log(f"[OK] {msg}")
        log("=== SPREAD FORECAST PIPELINE DONE ===")
        return {"status": "ok", "message": msg, "run_id": run_id}

    except Exception as e:
        log(f"[ERROR] {e}")
        return {"status": "error", "message": str(e), "run_id": None}


if __name__ == "__main__":
    res = run_pipeline()
    print("\nResult:", res)
