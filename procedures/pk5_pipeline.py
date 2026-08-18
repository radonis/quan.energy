# ============================================
# PK5 PIPELINE — PSE 5-day coordination plan
# ============================================
# Endpoint: https://api.raporty.pse.pl/api/pk5l-wp
# 24 hourly rows per day.
#
# Output files (in {app_dir}/PK5/):
#   pk5.parquet / pk5.xlsx      — master (latest data per date)
#   pk5for.parquet / pk5for.xlsx — forecast snapshot history
#
# Callable: run_pipeline(app_dir, log)
# Standalone: python pk5_pipeline.py

import os
import time
import requests
import pandas as pd
from datetime import datetime

PSE_BASE_URL       = "https://api.raporty.pse.pl/api"
PSE_ENDPOINT       = "pk5l-wp"
PSE_TIMEOUT        = 30
PSE_THROTTLE_SEC   = 0.2
FORECAST_HORIZON   = 14          # days ahead to download
START_DATE_DEFAULT = "2025-02-01"  # earliest date if no existing data


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_save_parquet(df: pd.DataFrame, path: str, backup_dir: str):
    """Atomic parquet save with backup of previous file."""
    tmp = path + ".tmp"
    df.to_parquet(tmp, index=False)
    if not os.path.exists(tmp):
        raise RuntimeError(f"TMP write failed: {tmp}")
    if os.path.exists(path):
        bk = os.path.join(backup_dir,
                          f"{os.path.basename(path)}_{int(time.time())}.parquet")
        os.rename(path, bk)
    os.rename(tmp, path)


def _save_excel(df: pd.DataFrame, path: str, log):
    try:
        df_xl = df.copy()
        for col in df_xl.select_dtypes(include=["datetimetz"]).columns:
            df_xl[col] = df_xl[col].dt.tz_localize(None)
        df_xl.to_excel(path, index=False, engine="openpyxl")
        log(f"[OK] Saved: {path}")
    except Exception as e:
        log(f"[WARN] Excel save failed: {e}")


def _clean_strings(df: pd.DataFrame) -> pd.DataFrame:
    for c in df.select_dtypes(include="object").columns:
        df[c] = (df[c]
                 .str.replace(r"\n", "", regex=True)
                 .str.replace('"', "", regex=True)
                 .str.replace("'", "", regex=True))
    return df


def _download_day(day: pd.Timestamp, log) -> pd.DataFrame:
    url = f"{PSE_BASE_URL}/{PSE_ENDPOINT}"
    try:
        from urllib.parse import quote as _q
        _d = day.strftime('%Y-%m-%d')
        _filt = "business_date eq '" + _d + "'"
        _url = url + '?' + chr(36) + 'filter=' + _q(_filt)
        r = requests.get(_url, timeout=PSE_TIMEOUT)
        if r.status_code != 200:
            log(f"  [WARN] HTTP {r.status_code} for {day.date()}")
            return pd.DataFrame()
        payload = r.json().get("value", [])
        if not payload:
            return pd.DataFrame()
        df = pd.DataFrame(payload)
        df = _clean_strings(df)
        df = df.convert_dtypes()
        for col in ["business_date", "plan_dtime", "plan_dtime_utc",
                    "publication_ts", "publication_ts_utc"]:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col])
        return df
    except Exception as e:
        log(f"  [ERROR] {day.date()}: {e}")
        return pd.DataFrame()


# ── Main ──────────────────────────────────────────────────────────────────────

def run_pipeline(app_dir: str | None = None, log=print) -> dict:
    """
    Download PSE PK5 data and save to PK5/pk5.parquet and PK5/pk5for.parquet.

    Parameters
    ----------
    app_dir : str
        Root app folder. Defaults to parent of this script's directory.
    log : callable
        Progress logger.

    Returns
    -------
    dict with keys: status, message, new_rows
    """
    if app_dir is None:
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    pk5_dir    = os.path.join(app_dir, "data", "pse")
    backup_dir = os.path.join(pk5_dir, "backup")
    os.makedirs(pk5_dir,    exist_ok=True)
    os.makedirs(backup_dir, exist_ok=True)

    PATH_PK5     = os.path.join(pk5_dir, "pk5.parquet")
    PATH_PK5FOR  = os.path.join(pk5_dir, "pk5for.parquet")
    PATH_PK5_XL  = os.path.join(pk5_dir, "pk5.xlsx")
    PATH_FOR_XL  = os.path.join(pk5_dir, "pk5for.xlsx")

    today     = pd.Timestamp(datetime.today().date())
    h_cutoff  = today - pd.Timedelta(days=1)   # dates <= yesterday → H

    log("=== PK5 PIPELINE START ===")

    # ── Load existing master ──────────────────────────────────────────────────
    if os.path.exists(PATH_PK5):
        df_pk5 = pd.read_parquet(PATH_PK5)
        log(f"[OK] Existing master: {df_pk5.shape}")
    else:
        df_pk5 = pd.DataFrame()
        log("[INFO] No existing master — starting from scratch")

    # ── Determine start date ──────────────────────────────────────────────────
    if not df_pk5.empty and "data_type" in df_pk5.columns:
        df_h = df_pk5[df_pk5["data_type"] == "H"]
        if not df_h.empty:
            last_h = pd.to_datetime(df_h["business_date"]).max().normalize()
        else:
            last_h = pd.Timestamp(START_DATE_DEFAULT) - pd.Timedelta(days=1)
    else:
        last_h = pd.Timestamp(START_DATE_DEFAULT) - pd.Timedelta(days=1)

    start_date = last_h + pd.Timedelta(days=1)
    end_date   = today + pd.Timedelta(days=FORECAST_HORIZON)

    log(f"[INFO] Fetching {start_date.date()} to {end_date.date()}")

    # ── Download ──────────────────────────────────────────────────────────────
    dates = pd.date_range(start_date, end_date, freq="D")
    frames = []
    for d in dates:
        log(f"  {d.date()} ...")
        df_day = _download_day(d, log)
        if not df_day.empty:
            frames.append(df_day)
            log(f"  [OK] {d.date()}: {len(df_day)} rows")
        time.sleep(PSE_THROTTLE_SEC)

    if not frames:
        log("[INFO] No new data downloaded.")
        return {"status": "ok", "message": "No new data.", "new_rows": 0}

    df_new = pd.concat(frames, ignore_index=True)
    log(f"[OK] New rows: {len(df_new)}")

    # ── Classify H / F ────────────────────────────────────────────────────────
    df_new["data_type"]    = "F"
    df_new.loc[pd.to_datetime(df_new["business_date"]) <= h_cutoff, "data_type"] = "H"
    df_new["snapshot_date"] = today

    # ── Merge master ──────────────────────────────────────────────────────────
    if df_pk5.empty:
        df_merged = df_new.copy()
    else:
        all_cols  = list(set(df_pk5.columns) | set(df_new.columns))
        df_merged = pd.concat(
            [df_pk5.reindex(columns=all_cols),
             df_new.reindex(columns=all_cols)],
            ignore_index=True,
        )
        dedup_keys = ["business_date"] + (
            ["plan_dtime"] if "plan_dtime" in df_merged.columns else [])
        df_merged = (
            df_merged
            .sort_values(dedup_keys + ["snapshot_date"])
            .drop_duplicates(subset=dedup_keys, keep="last")
            .sort_values(dedup_keys)
            .reset_index(drop=True)
        )

    log(f"[OK] Master merged: {df_merged.shape}")
    _safe_save_parquet(df_merged, PATH_PK5, backup_dir)
    log(f"[OK] Saved: {PATH_PK5}")
    _save_excel(df_merged, PATH_PK5_XL, log)

    # ── Forecast snapshot history ─────────────────────────────────────────────
    df_fcst_new = df_merged[df_merged["data_type"] == "F"].copy()
    if not df_fcst_new.empty:
        if os.path.exists(PATH_PK5FOR):
            df_hist = pd.read_parquet(PATH_PK5FOR)
        else:
            df_hist = pd.DataFrame()

        all_cols = list(set(df_hist.columns) | set(df_fcst_new.columns))
        df_for   = pd.concat(
            [df_hist.reindex(columns=all_cols),
             df_fcst_new.reindex(columns=all_cols)],
            ignore_index=True,
        )
        dedup_for = ["business_date", "snapshot_date"] + (
            ["plan_dtime"] if "plan_dtime" in df_for.columns else [])
        df_for = (
            df_for
            .sort_values(dedup_for)
            .drop_duplicates(subset=dedup_for, keep="last")
            .reset_index(drop=True)
        )
        _safe_save_parquet(df_for, PATH_PK5FOR, backup_dir)
        log(f"[OK] Saved: {PATH_PK5FOR} ({len(df_for)} rows)")
        _save_excel(df_for, PATH_FOR_XL, log)

    log("=== PK5 PIPELINE DONE ===")
    return {
        "status":   "ok",
        "message":  f"Downloaded {len(frames)} day(s), {len(df_new)} new rows.",
        "new_rows": len(df_new),
    }


# ── Standalone ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    app_dir = sys.argv[1] if len(sys.argv) > 1 else None
    result  = run_pipeline(app_dir=app_dir)
    print("\nResult:", result)
