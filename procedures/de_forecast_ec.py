"""
DE Forecast Pipeline — Electricity Maps / energy-charts (72H)

Callable : run_pipeline(app_dir, log)
Standalone: python procedures/de_forecast_ec.py
Cron OVH : 10 7 * * * /usr/bin/python3 /home/ubuntu/quant_energy/procedures/de_forecast_ec.py
"""

from __future__ import annotations

import os
import datetime as dt
import requests
import pandas as pd

API_TOKEN     = "ejN3pR5M2rhfKD52Bp3F"
ZONE          = "DE"
HORIZON_HOURS = 72
API_URL       = "https://api.electricitymaps.com/v3/price-day-ahead/forecast"
EURPLN_FALLBACK = 4.28


def _fetch(log) -> pd.DataFrame | None:
    params  = {"zone": ZONE, "horizonHours": HORIZON_HOURS}
    headers = {"auth-token": API_TOKEN}

    r = requests.get(API_URL, params=params, headers=headers, timeout=60)
    if r.status_code != 200:
        log(f"[ERROR] API {r.status_code}: {r.text[:200]}")
        return None

    data = r.json()
    if "data" not in data or not data["data"]:
        log("[ERROR] Empty API response.")
        return None

    df = pd.DataFrame(data["data"])
    if not {"datetime", "value"}.issubset(df.columns):
        log(f"[ERROR] Missing columns: {list(df.columns)}")
        return None

    df["datetime"] = (
        pd.to_datetime(df["datetime"], utc=True)
        .dt.tz_convert("Europe/Warsaw")
    )
    df["PriceEU"] = pd.to_numeric(df["value"], errors="coerce")
    df = (
        df[["datetime", "PriceEU"]]
        .dropna()
        .sort_values("datetime")
        .drop_duplicates("datetime", keep="last")
        .reset_index(drop=True)
    )
    log(f"[OK] Fetched {len(df)} rows ({df['datetime'].min()} → {df['datetime'].max()})")
    return df


def run_pipeline(app_dir: str | None = None, log=print) -> dict:
    if app_dir is None:
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    out_dir = os.path.join(app_dir, "data", "de")
    os.makedirs(out_dir, exist_ok=True)

    OUTPUT_PARQUET = os.path.join(out_dir, "DE_Price_72H_Forecast.parquet")
    HIST_PARQUET   = os.path.join(out_dir, "DE_fore_hist.parquet")
    HIST_UNIFIED   = os.environ.get(
        "DE_FORE_HIST_PATH",
        os.path.join(out_dir, "de_forecast_history.parquet"),
    )

    log("=== DE FORECAST (energy-charts) PIPELINE START ===")

    RUN_TS  = pd.Timestamp.now(tz="Europe/Warsaw")
    TODAY   = RUN_TS.normalize()

    # Live EURPLN — try parquet, fallback to constant
    EURPLN = EURPLN_FALLBACK
    try:
        _fx_path = os.path.join(app_dir, "data", "market", "EURPLN_Rate.parquet")
        if os.path.exists(_fx_path):
            _fx = pd.read_parquet(_fx_path)
            if not _fx.empty and "rate" in _fx.columns:
                EURPLN = float(_fx["rate"].iloc[-1])
                log(f"[INFO] Live EURPLN: {EURPLN}")
    except Exception as _e:
        log(f"[WARN] Could not load live EURPLN: {_e}")

    # Fetch
    try:
        df_api = _fetch(log)
        if df_api is None or df_api.empty:
            return {"status": "error", "message": "No data from API.", "rows": 0}
    except Exception as e:
        log(f"[ERROR] Fetch failed: {e}")
        return {"status": "error", "message": str(e), "rows": 0}

    # Build main file
    df_main = df_api.copy()
    df_main["kurs"]          = EURPLN
    df_main["PricePL"]       = (df_main["PriceEU"] * EURPLN).round(2)
    df_main["run_timestamp"] = RUN_TS
    df_main = df_main[["datetime", "PriceEU", "kurs", "PricePL", "run_timestamp"]]

    # Save main (atomic)
    _tmp = OUTPUT_PARQUET + ".tmp"
    df_main.to_parquet(_tmp, index=False)
    os.replace(_tmp, OUTPUT_PARQUET)
    log(f"[OK] Saved main: {OUTPUT_PARQUET}")

    # Save legacy per-source history (DE_fore_hist.parquet)
    try:
        _days_ahead = (df_main["datetime"].dt.normalize() - TODAY).dt.days

        def _rel(x):
            return "d" if x <= 0 else f"d+{int(x)}"

        df_hist_new = df_main.copy()
        df_hist_new["day_relative"] = _days_ahead.map(_rel)
        df_hist_new = df_hist_new[
            ["datetime", "day_relative", "PriceEU", "kurs", "PricePL", "run_timestamp"]
        ]

        if os.path.exists(HIST_PARQUET):
            df_hist_old = pd.read_parquet(HIST_PARQUET)
            df_hist = pd.concat([df_hist_old, df_hist_new], ignore_index=True)
        else:
            df_hist = df_hist_new

        df_hist = (
            df_hist
            .drop_duplicates(subset=["run_timestamp", "datetime"], keep="last")
            .sort_values(["run_timestamp", "datetime"])
            .reset_index(drop=True)
        )
        _tmp_h = HIST_PARQUET + ".tmp"
        df_hist.to_parquet(_tmp_h, index=False)
        os.replace(_tmp_h, HIST_PARQUET)
        log(f"[OK] Saved legacy history: {HIST_PARQUET} ({len(df_hist)} rows)")
    except Exception as e:
        log(f"[WARN] Legacy history failed: {e}")

    # Save unified forecast history (all horizons)
    try:
        _capture_date = TODAY.date()
        df_uni_new = pd.DataFrame({
            "capture_date":  _capture_date,
            "forecast_date": df_main["datetime"].dt.date,
            "hour":          (df_main["datetime"].dt.hour + 1).astype(int),
            "source":        "energy_charts",
            "price_eur":     df_main["PriceEU"].values,
            "run_timestamp": RUN_TS,
        })

        if os.path.exists(HIST_UNIFIED):
            df_uni_old = pd.read_parquet(HIST_UNIFIED)
            df_uni = pd.concat([df_uni_old, df_uni_new], ignore_index=True)
        else:
            df_uni = df_uni_new

        df_uni = (
            df_uni
            .drop_duplicates(
                subset=["capture_date", "forecast_date", "hour", "source"],
                keep="last",
            )
            .sort_values(["capture_date", "forecast_date", "source", "hour"])
            .reset_index(drop=True)
        )
        _tmp_u = HIST_UNIFIED + ".tmp"
        df_uni.to_parquet(_tmp_u, index=False)
        os.replace(_tmp_u, HIST_UNIFIED)
        log(f"[OK] Unified history: {HIST_UNIFIED} ({len(df_uni)} rows)")
    except Exception as e:
        log(f"[WARN] Unified history failed: {e}")

    log("=== DE FORECAST (energy-charts) PIPELINE DONE ===")
    msg = f"Fetched {len(df_main)} rows, {df_main['datetime'].min()} → {df_main['datetime'].max()}."
    return {"status": "ok", "message": msg, "rows": len(df_main)}


if __name__ == "__main__":
    import sys
    _app_dir = sys.argv[1] if len(sys.argv) > 1 else None
    result   = run_pipeline(app_dir=_app_dir)
    print("\nResult:", result)
