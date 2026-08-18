# ============================================
# DE LOAD PIPELINE — Electricity Maps
# ============================================
# Downloads German net load and total load
# from api.electricitymaps.com
#
# Output files (in energy_charts/):
#   de_netload.parquet / de_netload.xlsx
#   de_totalload.parquet / de_totalload.xlsx
#
# Callable: run_pipeline(app_dir)
# Standalone: python de_load.py

import os
import time
import datetime as dt
import requests
import pandas as pd

API_TOKEN    = "ejN3pR5M2rhfKD52Bp3F"
API_BASE     = "https://api.electricitymaps.com/v3"
ZONE         = "DE"
CHUNK_DAYS   = 9        # API limit is 10 days
THROTTLE_SEC = 0.3

DATASETS = {
    "net-load":   "de_netload",
    "total-load": "de_totalload",
}


def _download_series(series: str, start_date: dt.date, end_date: dt.date,
                     log=print) -> pd.DataFrame:
    """Download one series (net-load or total-load) for a date range."""

    url     = f"{API_BASE}/{series}/past-range"
    headers = {"auth-token": API_TOKEN}

    # Build 9-day chunks
    chunks, cur = [], start_date
    while cur <= end_date:
        chunk_end = min(cur + dt.timedelta(days=CHUNK_DAYS),
                        end_date + dt.timedelta(days=1))
        chunks.append((cur, chunk_end))
        cur = chunk_end

    frames = []
    for chunk_start, chunk_end in chunks:
        log(f"    {chunk_start} to {chunk_end - dt.timedelta(days=1)} ...")
        try:
            params = {
                "zone":  ZONE,
                "start": f"{chunk_start} 00:00",
                "end":   f"{chunk_end} 00:00",
            }
            r = requests.get(url, params=params, headers=headers, timeout=30)

            if r.status_code != 200:
                log(f"    [WARN] HTTP {r.status_code}: {r.text[:120]}")
                time.sleep(THROTTLE_SEC)
                continue

            records = r.json().get("data", [])
            if not records:
                log(f"    [WARN] No data")
                time.sleep(THROTTLE_SEC)
                continue

            df = pd.DataFrame(records)

            # datetime UTC → CET
            df["datetime_utc"] = pd.to_datetime(df["datetime"], utc=True)
            df["datetime_cet"] = (
                df["datetime_utc"]
                .dt.tz_convert("Europe/Warsaw")
                .dt.tz_localize(None)
            )
            df["datetime_utc"] = df["datetime_utc"].dt.tz_localize(None)
            df["business_date"] = df["datetime_cet"].dt.date
            df["hour"]          = df["datetime_cet"].dt.hour + 1   # 1-24

            df["value_mw"] = pd.to_numeric(df["value"], errors="coerce").round(3)
            df["is_estimated"] = df.get("isEstimated", False)

            df = df[["business_date", "hour", "datetime_cet", "datetime_utc",
                      "value_mw", "is_estimated", "source"]].copy()

            frames.append(df)
            log(f"    [OK] {len(df)} rows")

        except Exception as e:
            log(f"    [ERROR] {chunk_start}: {e}")

        time.sleep(THROTTLE_SEC)

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _save(df: pd.DataFrame, path_parquet: str, path_excel: str, log=print):
    """Save dataframe to parquet and Excel atomically."""
    tmp = path_parquet + ".tmp"
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path_parquet)
    log(f"[OK] Saved: {path_parquet}")

    try:
        df_xl = df.copy()
        for col in ["datetime_cet", "datetime_utc"]:
            if col in df_xl.columns:
                df_xl[col] = pd.to_datetime(df_xl[col]).dt.tz_localize(None)
        df_xl.to_excel(path_excel, index=False, engine="openpyxl")
        log(f"[OK] Saved: {path_excel}")
    except Exception as e:
        log(f"[WARN] Excel save failed: {e}")


def run_pipeline(app_dir: str | None = None, log=print) -> dict:
    """
    Download DE net load and total load and save to energy_charts/.

    Parameters
    ----------
    app_dir : str
        Root app folder. Defaults to parent of this script's directory.
    log : callable
        Progress logger.

    Returns
    -------
    dict with keys: status, message, results (per series)
    """

    if app_dir is None:
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    out_dir = os.path.join(app_dir, "data", "de")
    os.makedirs(out_dir, exist_ok=True)

    log("=== DE LOAD PIPELINE START ===")

    results = {}

    for series, file_stem in DATASETS.items():
        log(f"\n--- {series} ---")

        path_parquet = os.path.join(out_dir, f"{file_stem}.parquet")
        path_excel   = os.path.join(out_dir, f"{file_stem}.xlsx")

        # Load existing
        if os.path.exists(path_parquet):
            df_existing = pd.read_parquet(path_parquet)
            df_existing["datetime_cet"] = pd.to_datetime(df_existing["datetime_cet"])
            # Use last date with actual values
            df_priced = df_existing[df_existing["value_mw"].notna()]
            last_date = pd.to_datetime(df_priced["business_date"]).dt.date.max() \
                        if not df_priced.empty else dt.date(2024, 12, 31)
            log(f"[OK] Existing: {len(df_existing)} rows, last priced date: {last_date}")
        else:
            df_existing = pd.DataFrame()
            last_date   = dt.date(2024, 12, 31)
            log("[INFO] No existing data — starting from 2025-01-01")

        start_date = last_date + dt.timedelta(days=1)
        end_date   = dt.date.today()

        if start_date > end_date:
            log("[INFO] Already up to date.")
            results[series] = {"new_rows": 0, "message": "Already up to date."}
            continue

        log(f"[INFO] Fetching {(end_date - start_date).days + 1} day(s): "
            f"{start_date} to {end_date}")

        df_new = _download_series(series, start_date, end_date, log=log)

        if df_new.empty:
            log("[WARN] No new data downloaded.")
            results[series] = {"new_rows": 0, "message": "No new data."}
            continue

        log(f"[OK] New rows: {len(df_new)}")

        # Merge + dedup
        df_all = pd.concat([df_existing, df_new], ignore_index=True)
        df_all["datetime_cet"] = pd.to_datetime(df_all["datetime_cet"])
        df_all = (
            df_all
            .sort_values(["business_date", "hour"])
            .drop_duplicates(["business_date", "hour"], keep="last")
            .reset_index(drop=True)
        )
        log(f"[OK] Total rows after merge: {len(df_all)}")

        _save(df_all, path_parquet, path_excel, log=log)
        results[series] = {"new_rows": len(df_new), "total_rows": len(df_all)}

    log("\n=== DE LOAD PIPELINE DONE ===")
    return {"status": "ok", "message": "Done.", "results": results}


# ── Standalone ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    app_dir = sys.argv[1] if len(sys.argv) > 1 else None
    result  = run_pipeline(app_dir=app_dir)
    print("\nResult:", result)
