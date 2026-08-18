"""
DE Forecast Pipeline — energyforecast.de (EFDE)

A SECOND, independent German day-ahead price forecast, parallel to the
existing DE_Price_72H_Forecast.parquet (DE_forecast.py). Useful as a
cross-check / ensemble input — not wired into any model yet.

Endpoint : GET /api/v1/predictions/next_48_hours
Auth     : query param "token" (apiKeyAuth)
Response : JSON array of {start, end, price (EUR/kWh), price_origin}
           price_origin = "market" (realized EPEX) or "forecast" (predicted)

We request fixed_cost_cent=0 & vat=0 to get the RAW EPEX wholesale price
(no VAT / retail markup), so it's directly comparable to de_spot.parquet
and DE_Price_72H_Forecast.parquet (both EUR/MWh, no tax).

Output: {app_dir}/data/de/DE_Price_EnergyForecastDE.parquet
Overwritten each run (rolling 48h snapshot, not an accumulating archive) —
same convention as the existing DE_Price_72H_Forecast.parquet.

Callable: run_pipeline(app_dir, log)
Standalone: python procedures/de_forecast_efde.py
"""

import os
import datetime as dt
import requests
import pandas as pd

API_KEY  = "0955a07534353f217dc557dbe7"
BASE_URL = "https://www.energyforecast.de/api/v1/predictions/next_48_hours"
TIMEOUT  = 30


def _fetch(log):
    params = {
        "token": API_KEY,
        "fixed_cost_cent": 0,
        "vat": 0,
        "resolution": "HOURLY",
        "market_zone": "DE-LU",
    }
    r = requests.get(BASE_URL, params=params, timeout=TIMEOUT)
    if r.status_code != 200:
        log(f"[ERROR] HTTP {r.status_code}: {r.text[:200]}")
        return None

    records = r.json()
    if not records:
        log("[WARN] Empty response.")
        return None

    df = pd.DataFrame(records)
    df["start"] = pd.to_datetime(df["start"])
    df["end"]   = pd.to_datetime(df["end"])
    df["price_eur_mwh"] = pd.to_numeric(df["price"], errors="coerce") * 1000.0
    df = df.rename(columns={"start": "datetime"})
    df = df[["datetime", "price_eur_mwh", "price_origin"]]
    log(f"[OK] Fetched {len(df)} rows "
        f"({df['datetime'].min()} -> {df['datetime'].max()})")
    return df


def run_pipeline(app_dir=None, log=print):
    """
    Download the next-48h DE-LU day-ahead forecast from energyforecast.de
    and overwrite data/de/DE_Price_EnergyForecastDE.parquet.

    Returns dict {"status": "ok"|"error", "message": str, "rows": int}
    """
    if app_dir is None:
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    out_dir = os.path.join(app_dir, "data", "de")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "DE_Price_EnergyForecastDE.parquet")

    log("=== DE FORECAST (energyforecast.de) PIPELINE START ===")

    try:
        df = _fetch(log)
        if df is None or df.empty:
            msg = "No data fetched from energyforecast.de."
            log(f"[WARN] {msg}")
            return {"status": "warning", "message": msg, "rows": 0}

        df["run_timestamp"] = dt.datetime.now()

        tmp = out_path + ".tmp"
        df.to_parquet(tmp, index=False)
        os.replace(tmp, out_path)
        log(f"[OK] Saved: {out_path}")

        # ── Append to unified forecast history ────────────────────────────────
        try:
            import datetime as _dt_mod
            _hist_path = os.environ.get(
                "DE_FORE_HIST_PATH",
                os.path.join(out_dir, "de_forecast_history.parquet"),
            )
            _capture_date = _dt_mod.date.today()
            _dt_local = pd.to_datetime(df["datetime"], utc=True).dt.tz_convert("Europe/Warsaw")
            _df_hist_new = pd.DataFrame({
                "capture_date":  _capture_date,
                "forecast_date": _dt_local.dt.date,
                "hour":          (_dt_local.dt.hour + 1).astype(int),
                "source":        "energyforecast_de",
                "price_eur":     df["price_eur_mwh"].values,
                "run_timestamp": _dt_mod.datetime.now(),
            })
            if os.path.exists(_hist_path):
                _df_old = pd.read_parquet(_hist_path)
                _df_uni = pd.concat([_df_old, _df_hist_new], ignore_index=True)
            else:
                _df_uni = _df_hist_new
            _df_uni = (
                _df_uni
                .drop_duplicates(
                    subset=["capture_date", "forecast_date", "hour", "source"],
                    keep="last",
                )
                .sort_values(["capture_date", "forecast_date", "source", "hour"])
                .reset_index(drop=True)
            )
            _tmp_h = _hist_path + ".tmp"
            _df_uni.to_parquet(_tmp_h, index=False)
            os.replace(_tmp_h, _hist_path)
            log(f"[OK] Unified history: {_hist_path} ({len(_df_uni)} rows)")
        except Exception as _e_hist:
            log(f"[WARN] Unified history failed: {_e_hist}")

        log("=== DE FORECAST (energyforecast.de) PIPELINE DONE ===")

        msg = f"Fetched {len(df)} rows, {df['datetime'].min()} -> {df['datetime'].max()}."
        return {"status": "ok", "message": msg, "rows": len(df)}

    except Exception as e:
        log(f"[ERROR] {e}")
        return {"status": "error", "message": str(e), "rows": 0}


if __name__ == "__main__":
    result = run_pipeline()
    print("\nResult:", result)
