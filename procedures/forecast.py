# -*- coding: utf-8 -*-
"""
Forecast Pipeline — EnergyQuant
Trains DT / RF / XGB / SARIMAX models on market_features_raw and writes
results to DuckDB tables: runs, forecast_prices, forecast_pk5.

Callable:
    from procedures.forecast import run_pipeline
    result = run_pipeline(fixing_type="F1", log=print)

Standalone:
    python procedures/forecast.py F1
    python procedures/forecast.py F2
"""

import os
import sys
import warnings
import datetime
from datetime import timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import duckdb
from sklearn.tree import DecisionTreeRegressor
from sklearn.ensemble import RandomForestRegressor
from statsmodels.tsa.statespace.sarimax import SARIMAX
import xgboost as xgb

warnings.filterwarnings("ignore")

RANDOM_SEED      = 42
DEFAULT_DB_PATH  = "/home/ubuntu/db/forecast_db.duckdb"

FEATURES = [
    "RL",
    "Prognozowane zapotrzebowanie sieci [MW]",
    "Generacja PV [MW]",
    "Generacja wiatrowa [MW]",
    "Wymiana systemowa [MW]",
    "Niedyspozycyjność sieci [MW]",
    "wind_share",
    "pv_share",
    "hour",
    "weekday",
    "month",
    "is_weekend",
]

EXOG_COLS = [
    "RL",
    "Prognozowane zapotrzebowanie sieci [MW]",
    "Generacja PV [MW]",
    "Generacja wiatrowa [MW]",
    "wind_share",
    "pv_share",
]


# ── Step 1: DuckDB views ──────────────────────────────────────────────────────

def _create_views(con, pk5_path, fixing_path, log):
    if not os.path.exists(pk5_path):
        raise FileNotFoundError(f"PK5 file not found: {pk5_path}")
    if not os.path.exists(fixing_path):
        raise FileNotFoundError(f"Fixing prices file not found: {fixing_path}")

    con.execute("DROP VIEW IF EXISTS pk5")
    con.execute(f"CREATE VIEW pk5 AS SELECT * FROM read_parquet('{pk5_path}')")
    log("[OK] VIEW pk5 created")

    con.execute("DROP VIEW IF EXISTS fixing_prices")
    con.execute(f"CREATE VIEW fixing_prices AS SELECT * FROM read_parquet('{fixing_path}')")
    log("[OK] VIEW fixing_prices created")


# ── Step 2: Build market_features_raw ────────────────────────────────────────

def _build_market_features(con, log):
    con.execute("DROP TABLE IF EXISTS market_features_raw")
    con.execute("""
CREATE TABLE market_features_raw AS

WITH pk5_latest AS (
    SELECT *
    FROM (
        SELECT *,
               ROW_NUMBER() OVER (
                   PARTITION BY business_date, period
                   ORDER BY snapshot_date DESC
               ) AS rn
        FROM pk5
    )
    WHERE rn = 1
),

fixing_latest AS (
    SELECT *
    FROM (
        SELECT *,
               ROW_NUMBER() OVER (
                   PARTITION BY delivery_date, H
                   ORDER BY fixing_date DESC
               ) AS rn
        FROM fixing_prices
    )
    WHERE rn = 1
)

SELECT
    p.plan_dtime    AS Timestamp,
    p.business_date AS business_date,
    CAST(SUBSTR(p.period, 1, 2) AS INTEGER) + 1 AS H,

    s.f1_price_PLN   AS Fixing1,
    s.sdac_price_PLN AS Fixing2,

    p.grid_demand_fcst AS "Prognozowane zapotrzebowanie sieci [MW]",
    p.fcst_pv_tot_gen  AS "Generacja PV [MW]",
    p.fcst_wi_tot_gen  AS "Generacja wiatrowa [MW]",
    p.planned_exchange AS "Wymiana systemowa [MW]",
    p.fcst_unav_energy AS "Niedyspozycyjność sieci [MW]",

    (p.grid_demand_fcst - p.fcst_pv_tot_gen - p.fcst_wi_tot_gen) AS RL

FROM pk5_latest p
LEFT JOIN fixing_latest s
    ON s.delivery_date = p.business_date
   AND s.H = CAST(SUBSTR(p.period, 1, 2) AS INTEGER) + 1

ORDER BY p.plan_dtime
""")
    count = con.execute("SELECT COUNT(*) FROM market_features_raw").fetchone()[0]
    log(f"[OK] market_features_raw: {count} rows")


# ── Step 3: Load data ─────────────────────────────────────────────────────────

def _load_data(con, target_column, log):
    df = con.execute(
        "SELECT * FROM market_features_raw ORDER BY Timestamp"
    ).df()
    df = df.set_index("Timestamp")
    df.index = pd.to_datetime(df.index)
    df["business_date"] = pd.to_datetime(df["business_date"]).dt.date

    log(f"[OK] Data loaded: {df.shape}")

    # Use business_date, not the Timestamp index — PK5's plan_dtime for H=24
    # (period "23-24") is midnight of the NEXT day, which would silently
    # shift last_price_date (and forecast_end) forward by one day if read
    # from the index instead.
    last_price_date = df.loc[df[target_column].notna(), "business_date"].max()
    log(f"[INFO] Last price date: {last_price_date}")

    forecast_start = last_price_date + timedelta(days=1)
    forecast_end   = df["business_date"].max()

    log(f"[INFO] Forecast: {forecast_start} → {forecast_end}"
        f" ({(forecast_end - forecast_start).days + 1} days)")

    return df, last_price_date, forecast_start, forecast_end


# ── Step 4: Feature engineering ───────────────────────────────────────────────

def _feature_engineering(df, target_column, log):
    df_fe = df.copy()
    df_fe["Fixing1"] = df_fe[target_column]

    # Derive calendar features from business_date/H, NOT the Timestamp index
    # (see _load_data note — H=24 rows would otherwise read the next day's
    # weekday/month and hour=0 instead of hour=23).
    _bd = pd.to_datetime(df_fe["business_date"])
    df_fe["hour"]       = df_fe["H"] - 1
    df_fe["weekday"]    = _bd.dt.weekday.values
    df_fe["month"]      = _bd.dt.month.values
    df_fe["is_weekend"] = (df_fe["weekday"] >= 5).astype(int)

    df_fe["Fixing1_lag1"]         = df_fe["Fixing1"].shift(1)
    df_fe["Fixing1_lag24"]        = df_fe["Fixing1"].shift(24)
    df_fe["Fixing1_roll24_mean"]  = df_fe["Fixing1"].rolling(24, min_periods=24).mean()
    df_fe["Fixing1_roll24_std"]   = df_fe["Fixing1"].rolling(24, min_periods=24).std()

    demand = df_fe["Prognozowane zapotrzebowanie sieci [MW]"]
    df_fe["wind_share"] = df_fe["Generacja wiatrowa [MW]"] / demand.replace(0, pd.NA)
    df_fe["pv_share"]   = df_fe["Generacja PV [MW]"]       / demand.replace(0, pd.NA)

    before  = len(df_fe)
    df_fe   = df_fe.dropna()
    log(f"[OK] Feature engineering done. Dropped {before - len(df_fe)} NaN rows. "
        f"Shape: {df_fe.shape}")
    return df_fe


# ── Step 5: History / forecast split ─────────────────────────────────────────

def _split_data(df_fe, df, forecast_start, forecast_end, log):
    # Split on business_date, NOT the Timestamp index — see note in _load_data.
    mask_hist = df_fe["business_date"] < forecast_start
    df_hist   = df_fe[mask_hist].copy()

    mask_future  = (df["business_date"] >= forecast_start) & (df["business_date"] <= forecast_end)
    df_forecast  = df[mask_future].copy()

    _bd_fc = pd.to_datetime(df_forecast["business_date"])
    df_forecast["hour"]       = df_forecast["H"] - 1
    df_forecast["weekday"]    = _bd_fc.dt.weekday.values
    df_forecast["month"]      = _bd_fc.dt.month.values
    df_forecast["is_weekend"] = (df_forecast["weekday"] >= 5).astype(int)

    demand_fc = df_forecast["Prognozowane zapotrzebowanie sieci [MW]"]
    df_forecast["wind_share"] = df_forecast["Generacja wiatrowa [MW]"] / demand_fc.replace(0, pd.NA)
    df_forecast["pv_share"]   = df_forecast["Generacja PV [MW]"]       / demand_fc.replace(0, pd.NA)

    if len(df_hist) == 0:
        raise ValueError("No historical data for training.")
    if len(df_forecast) == 0:
        raise ValueError(f"No forecast data for {forecast_start} → {forecast_end}.")

    missing = set(FEATURES) - set(df_forecast.columns)
    if missing:
        raise ValueError(f"Missing features in forecast period: {missing}")

    y_hist     = df_hist["Fixing1"]
    X_hist     = df_hist[FEATURES]
    X_forecast = df_forecast[FEATURES]

    log(f"[OK] Split done. X_hist: {X_hist.shape}, X_forecast: {X_forecast.shape}")
    return df_hist, df_forecast, X_hist, y_hist, X_forecast


# ── Step 6: Train all models ──────────────────────────────────────────────────

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
    log(f"[OK] RF done")

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
    log(f"[OK] XGB done")

    log("[MODEL 4/4] SARIMAX (may take several minutes) ...")
    y_sar        = df_hist["Fixing1"].astype(float)
    exog_hist_s  = df_hist[EXOG_COLS].astype(float)
    exog_future_s = df_forecast[EXOG_COLS].astype(float)

    exog_hist_s   = exog_hist_s.replace([np.inf, -np.inf], np.nan)
    exog_future_s = exog_future_s.replace([np.inf, -np.inf], np.nan)

    mask_ok     = y_sar.notna() & exog_hist_s.notna().all(axis=1)
    y_sar       = y_sar.loc[mask_ok]
    exog_hist_s = exog_hist_s.loc[mask_ok]

    if exog_future_s.isna().any().any():
        exog_future_s = exog_future_s.fillna(exog_future_s.median())

    sar_model = SARIMAX(
        endog=y_sar, exog=exog_hist_s,
        order=(1, 1, 1), seasonal_order=(1, 0, 1, 24),
        enforce_stationarity=False, enforce_invertibility=False,
    )
    sar_fit = sar_model.fit(disp=False)
    sar_fc  = sar_fit.forecast(steps=len(exog_future_s), exog=exog_future_s)
    results["SARIMAX"] = pd.Series(
        np.asarray(sar_fc, dtype=float), index=exog_future_s.index
    )
    log(f"[OK] SARIMAX done")

    return results


# ── Step 7: Write to DuckDB ───────────────────────────────────────────────────

def _write_to_db(con, fixing_type, forecast_start, forecast_end,
                 last_price_date, df_forecast, model_results, log):

    con.execute("""
CREATE TABLE IF NOT EXISTS runs (
    run_id         VARCHAR PRIMARY KEY,
    snapshot_ts    TIMESTAMP,
    snapshot_date  DATE,
    fixing_type    VARCHAR,
    forecast_start DATE,
    forecast_end   DATE,
    sdac_last_date DATE,
    pk5_last_date  DATE
)""")
    con.execute("""
CREATE TABLE IF NOT EXISTS forecast_prices (
    run_id        VARCHAR,
    ts            TIMESTAMP,
    model         VARCHAR,
    price_pln_mwh DOUBLE
)""")
    con.execute("""
CREATE TABLE IF NOT EXISTS forecast_pk5 (
    run_id      VARCHAR,
    ts          TIMESTAMP,
    rl          DOUBLE,
    demand_mw   DOUBLE,
    pv_mw       DOUBLE,
    wind_mw     DOUBLE,
    exchange_mw DOUBLE,
    unavail_mw  DOUBLE
)""")
    for ddl in [
        "CREATE INDEX IF NOT EXISTS idx_prices_run_ts ON forecast_prices(run_id, ts)",
        "CREATE INDEX IF NOT EXISTS idx_pk5_run_ts    ON forecast_pk5(run_id, ts)",
    ]:
        try:
            con.execute(ddl)
        except Exception:
            pass

    run_id      = datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{fixing_type}"
    snapshot_ts = datetime.datetime.now()

    con.execute("DELETE FROM forecast_prices WHERE run_id = ?", [run_id])
    con.execute("DELETE FROM forecast_pk5    WHERE run_id = ?", [run_id])
    con.execute("DELETE FROM runs           WHERE run_id = ?", [run_id])

    runs_row = pd.DataFrame([{
        "run_id":         run_id,
        "snapshot_ts":    snapshot_ts,
        "snapshot_date":  snapshot_ts.date(),
        "fixing_type":    fixing_type,
        "forecast_start": forecast_start,
        "forecast_end":   forecast_end,
        "sdac_last_date": last_price_date,
        "pk5_last_date":  forecast_end,
    }])

    price_frames = []
    for model_name, series in model_results.items():
        price_frames.append(pd.DataFrame({
            "ts":           series.index,
            "price_pln_mwh": series.values,
            "model":        model_name,
            "run_id":       run_id,
        }))
    prices_all = pd.concat(price_frames, ignore_index=True)
    prices_all["ts"]            = pd.to_datetime(prices_all["ts"])
    prices_all["price_pln_mwh"] = pd.to_numeric(prices_all["price_pln_mwh"], errors="coerce").astype(float)

    pk5_cols = {
        "Prognozowane zapotrzebowanie sieci [MW]": "demand_mw",
        "Generacja PV [MW]":                       "pv_mw",
        "Generacja wiatrowa [MW]":                 "wind_mw",
        "Wymiana systemowa [MW]":                  "exchange_mw",
        "Niedyspozycyjność sieci [MW]":            "unavail_mw",
        "RL":                                      "rl",
    }
    pk5_out = df_forecast[list(pk5_cols.keys())].copy().reset_index()
    pk5_out = pk5_out.rename(columns={df_forecast.index.name: "ts", **pk5_cols})
    pk5_out["run_id"] = run_id
    pk5_out["ts"]     = pd.to_datetime(pk5_out["ts"])
    for c in ["rl", "demand_mw", "pv_mw", "wind_mw", "exchange_mw", "unavail_mw"]:
        pk5_out[c] = pd.to_numeric(pk5_out[c], errors="coerce").astype(float)

    con.register("_runs_row",   runs_row)
    con.register("_prices_all", prices_all)
    con.register("_pk5_out",    pk5_out)

    con.execute("INSERT INTO runs SELECT * FROM _runs_row")
    con.execute("INSERT INTO forecast_prices SELECT run_id, ts, model, price_pln_mwh FROM _prices_all")
    con.execute("INSERT INTO forecast_pk5 SELECT run_id, ts, rl, demand_mw, pv_mw, wind_mw, exchange_mw, unavail_mw FROM _pk5_out")

    log(f"[OK] Written to DuckDB. run_id={run_id}")
    log(f"[OK] forecast_prices: {len(prices_all)} rows | forecast_pk5: {len(pk5_out)} rows")
    return run_id


# ── Public API ────────────────────────────────────────────────────────────────

def run_pipeline(fixing_type, db_path=None, app_dir=None, log=print):
    """
    Full forecast pipeline: views → market_features → 4 models → DuckDB write.

    Parameters
    ----------
    fixing_type : "F1" or "F2"
    db_path     : path to DuckDB file (default: /home/ubuntu/db/forecast_db.duckdb)
    app_dir     : root app directory (locates PK5/pk5.parquet + FixingPricesH.parquet)
    log         : callable(str)

    Returns
    -------
    dict {"status": "ok"|"error", "message": str, "run_id": str|None}
    """
    if fixing_type not in ("F1", "F2"):
        return {"status": "error", "message": f"Unknown fixing_type: {fixing_type}", "run_id": None}

    if db_path is None:
        db_path = DEFAULT_DB_PATH
    if app_dir is None:
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    pk5_path    = os.path.join(app_dir, "data", "pse",     "pk5.parquet")
    fixing_path = os.path.join(app_dir, "data", "pl_spot", "FixingPricesH.parquet")
    target_col  = "Fixing1" if fixing_type == "F1" else "Fixing2"

    log(f"=== FORECAST PIPELINE START [{fixing_type}] ===")
    log(f"DB:     {db_path}")
    log(f"PK5:    {pk5_path}")
    log(f"Fixing: {fixing_path}")

    try:
        con = duckdb.connect(db_path, read_only=False)

        log("[STEP 1] Creating DuckDB views ...")
        _create_views(con, pk5_path, fixing_path, log)

        log("[STEP 2] Building market_features_raw ...")
        _build_market_features(con, log)

        log("[STEP 3] Loading data ...")
        df, last_price_date, forecast_start, forecast_end = _load_data(con, target_col, log)

        log("[STEP 4] Feature engineering ...")
        df_fe = _feature_engineering(df, target_col, log)

        log("[STEP 5] Splitting history / forecast ...")
        df_hist, df_forecast, X_hist, y_hist, X_forecast = _split_data(
            df_fe, df, forecast_start, forecast_end, log
        )

        log("[STEP 6] Training models ...")
        model_results = _train_models(X_hist, y_hist, X_forecast, df_hist, df_forecast, log)

        log("[STEP 7] Writing to DuckDB ...")
        run_id = _write_to_db(
            con, fixing_type, forecast_start, forecast_end,
            last_price_date, df_forecast, model_results, log
        )

        try:
            con.execute("CHECKPOINT")
        except Exception:
            pass
        con.close()

        msg = (f"Forecast {fixing_type}: {forecast_start} → {forecast_end}. "
               f"run_id={run_id}")
        log(f"[OK] {msg}")
        log("=== FORECAST PIPELINE DONE ===")
        return {"status": "ok", "message": msg, "run_id": run_id}

    except Exception as e:
        log(f"[ERROR] {e}")
        return {"status": "error", "message": str(e), "run_id": None}


def ensure_run_today(fixing_type, db_path=None, app_dir=None, log=print):
    """
    Run the forecast pipeline for `fixing_type` only if it hasn't already run
    today (e.g. via a manual click on the Forecast page). Used by the 07:15
    cron fallback so the user doesn't have to remember to trigger it by hand.
    """
    if db_path is None:
        db_path = DEFAULT_DB_PATH

    today = datetime.date.today()
    already_ran = False
    if os.path.exists(db_path):
        try:
            con = duckdb.connect(db_path, read_only=True)
            count = con.execute(
                "SELECT COUNT(*) FROM runs WHERE fixing_type = ? AND snapshot_date = ?",
                [fixing_type, today],
            ).fetchone()[0]
            con.close()
            already_ran = count > 0
        except Exception as e:
            log(f"[WARN] Could not check existing runs ({e}) — running anyway.")

    if already_ran:
        msg = f"{fixing_type} already ran today — skipping auto-trigger."
        log(f"[SKIP] {msg}")
        return {"status": "ok", "message": msg, "run_id": None, "skipped": True}

    log(f"[INFO] {fixing_type} has not run today — auto-triggering.")
    result = run_pipeline(fixing_type=fixing_type, db_path=db_path, app_dir=app_dir, log=log)
    result["skipped"] = False
    return result


if __name__ == "__main__":
    ft = sys.argv[1] if len(sys.argv) > 1 else "F1"
    if ft == "auto":
        for _ft in ("F1", "F2"):
            print(f"\n--- {_ft} ---")
            print(ensure_run_today(fixing_type=_ft))
    else:
        res = run_pipeline(fixing_type=ft)
        print("\nResult:", res)
