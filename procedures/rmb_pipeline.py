# ============================================
# RMB PIPELINE — Rynek Mocy Bilansujących
# ============================================
# Downloads ancillary market prices (FCR, aFRR, mFRR, RR)
# from https://api.raporty.pse.pl/api/mbp-tp
#
# Output: {app_dir}/data/rb/ancillary_prices.parquet
#
# Also provides: import_from_excel() for one-time historical load.
#
# Callable: run_pipeline(app_dir)
# Standalone: python rmb_pipeline.py

import os
import time
import datetime as dt
import requests
import pandas as pd
from urllib.parse import quote as _url_quote

# cmbp-tp = official "Ceny MBP" price report (matches raporty.pse.pl/report/cmbp-tp,
# and matches historical Excel values exactly). mbp-tp is a *different* report with
# different values — do not swap back without re-verifying against raporty.pse.pl.
PSE_BASE_URL = "https://api.raporty.pse.pl/api/cmbp-tp"
PSE_TIMEOUT  = 30
PSE_THROTTLE = 0.3


def _pse_get(base_url, date_str, timeout=PSE_TIMEOUT):
    """GET PSE API with $filter — avoids requests encoding dollar sign as %24."""
    filt = "business_date ge '{}' and business_date le '{}'".format(date_str, date_str)
    url  = base_url + "?" + chr(36) + "filter=" + _url_quote(filt)
    return requests.get(url, timeout=timeout)

_COLS_ORDER = [
    "business_date", "hour",
    "fcr_g", "fcr_d",
    "afrr_g", "afrr_d",
    "mfrrd_g", "mfrrd_d",
    "rr_g", "rr_d",
    "publication_ts",
]


def _out_path(app_dir: str) -> str:
    out_dir = os.path.join(app_dir, "data", "rb")
    os.makedirs(out_dir, exist_ok=True)
    return os.path.join(out_dir, "ancillary_prices.parquet")


def _save(df: pd.DataFrame, path: str, log=print):
    tmp = path + ".tmp"
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)
    log(f"[OK] Saved {len(df)} rows -> {path}")


# ── Excel import (one-time historical load) ───────────────────────────────────

def import_from_excel(excel_path: str, app_dir: str | None = None, log=print) -> dict:
    """
    Convert rmb.xlsx (sheets FCRg, aFRRg, RRg) to ancillary_prices.parquet.
    DOWN prices not available in Excel → stored as NaN.
    mFRR prices set equal to aFRR (as per spec v1).
    """
    if app_dir is None:
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    path = _out_path(app_dir)
    log(f"=== RMB EXCEL IMPORT: {excel_path} ===")

    xl = pd.ExcelFile(excel_path)

    # sheet → wide-format column
    sheet_col = {"FCRg": "fcr_g", "aFRRg": "afrr_g", "RRg": "rr_g"}
    dfs = {}

    for sheet, col in sheet_col.items():
        df_raw = xl.parse(sheet, header=None)
        rows = []
        for _, row in df_raw.iterrows():
            date_val = row.iloc[1]
            # Skip header and summary rows — keep only rows with a datetime in col 1
            if not isinstance(date_val, (dt.datetime, pd.Timestamp)):
                continue
            bdate = pd.Timestamp(date_val).date()
            for h in range(1, 25):
                raw = row.iloc[h + 2]   # col3 = hour 1, col26 = hour 24
                price = 0.0 if pd.isna(raw) else float(raw)
                rows.append({"business_date": bdate, "hour": h, col: price})
        dfs[sheet] = pd.DataFrame(rows)
        log(f"[OK] {sheet}: {len(rows)} rows")

    # Merge all three on (business_date, hour)
    df = (dfs["FCRg"]
          .merge(dfs["aFRRg"], on=["business_date", "hour"], how="outer")
          .merge(dfs["RRg"],   on=["business_date", "hour"], how="outer"))

    # DOWN prices not in Excel
    df["fcr_d"]   = float("nan")
    df["afrr_d"]  = float("nan")
    df["rr_d"]    = float("nan")

    # mFRR = aFRR (v1 — will be replaced when real mFRR data is available)
    df["mfrrd_g"] = df["afrr_g"]
    df["mfrrd_d"] = float("nan")

    df["publication_ts"] = pd.NaT

    df = (df[_COLS_ORDER]
          .sort_values(["business_date", "hour"])
          .drop_duplicates(["business_date", "hour"], keep="last")
          .reset_index(drop=True))

    _save(df, path, log)
    log(f"=== EXCEL IMPORT DONE: {len(df)} rows ===")
    return {"status": "ok", "rows": len(df)}


# ── API pipeline (daily incremental) ─────────────────────────────────────────

def run_pipeline(app_dir: str | None = None, log=print) -> dict:
    """
    Download RMB prices from PSE API (mbp-tp) and append to parquet.

    Parameters
    ----------
    app_dir : str
        Root app folder. Defaults to parent of this script's directory.
    log : callable
        Progress logger.

    Returns
    -------
    dict with keys: status, message, dates_fetched, new_rows
    """
    if app_dir is None:
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    path = _out_path(app_dir)

    log("=== RMB PIPELINE START ===")

    # ── Load existing ──────────────────────────────────────────────────────────
    if os.path.exists(path):
        df_existing = pd.read_parquet(path)
        df_existing["business_date"] = pd.to_datetime(df_existing["business_date"]).dt.date
        last_date = df_existing["business_date"].max()
        log(f"[OK] Existing: {len(df_existing)} rows, last date: {last_date}")
    else:
        df_existing = pd.DataFrame()
        last_date   = dt.date(2024, 6, 13)   # day before Excel data starts
        log("[INFO] No existing data — fetching from 2024-06-14")

    start_date = last_date + dt.timedelta(days=1)
    # The main auction settles around 10:00 on day D for delivery on D+1, so
    # results for "tomorrow" are already published right after the auction —
    # always include it, don't wait until it becomes "today".
    end_date   = dt.date.today() + dt.timedelta(days=1)

    if start_date > end_date:
        log("[INFO] Already up to date.")
        return {"status": "ok", "message": "Already up to date.",
                "dates_fetched": [], "new_rows": 0}

    dates = [start_date + dt.timedelta(days=i)
             for i in range((end_date - start_date).days + 1)]
    log(f"[INFO] Fetching {len(dates)} day(s): {dates[0]} → {dates[-1]}")

    # ── Download ───────────────────────────────────────────────────────────────
    frames, fetched = [], []

    for d in dates:
        log(f"  {d} ...")
        try:
            r = _pse_get(PSE_BASE_URL, str(d))

            if r.status_code != 200:
                log(f"  [WARN] HTTP {r.status_code}: {r.text[:200]}")
                time.sleep(PSE_THROTTLE)
                continue

            records = r.json().get("value", [])
            if not records:
                log(f"  [WARN] No data for {d}")
                time.sleep(PSE_THROTTLE)
                continue

            df_day = pd.DataFrame(records)
            df_day["business_date"] = pd.to_datetime(df_day["business_date"]).dt.date
            # dtime is the END of the hour: 01:00=h1, ..., 23:00=h23, next-day 00:00=h24
            df_day["hour"] = pd.to_datetime(df_day["dtime"]).dt.hour
            df_day.loc[df_day["hour"] == 0, "hour"] = 24
            df_day["publication_ts"] = pd.to_datetime(df_day["publication_ts"])

            # Keep relevant columns
            keep = ["business_date", "hour",
                    "fcr_g", "fcr_d",
                    "afrr_g", "afrr_d",
                    "mfrrd_g", "mfrrd_d",
                    "rr_g", "rr_d",
                    "publication_ts"]
            for c in keep:
                if c not in df_day.columns:
                    df_day[c] = float("nan")
            df_day = df_day[keep]

            frames.append(df_day)
            fetched.append(d)
            log(f"  [OK] {len(df_day)} rows")

        except Exception as e:
            log(f"  [ERROR] {d}: {e}")

        time.sleep(PSE_THROTTLE)

    if not frames:
        log("[INFO] No new data downloaded.")
        return {"status": "ok", "message": "No new data available yet.",
                "dates_fetched": [], "new_rows": 0}

    df_new = pd.concat(frames, ignore_index=True)
    log(f"[OK] New rows: {len(df_new)}")

    # ── Merge + dedup ──────────────────────────────────────────────────────────
    df_all = pd.concat([df_existing, df_new], ignore_index=True)
    df_all["business_date"] = pd.to_datetime(df_all["business_date"]).dt.date
    df_all = (df_all
              .sort_values(["business_date", "hour"])
              .drop_duplicates(["business_date", "hour"], keep="last")
              .reset_index(drop=True))
    log(f"[OK] Total rows after merge: {len(df_all)}")

    _save(df_all, path, log)
    log("=== RMB PIPELINE DONE ===")
    return {
        "status":        "ok",
        "message":       f"Updated {len(fetched)} day(s), {len(df_new)} new rows.",
        "dates_fetched": [str(d) for d in fetched],
        "new_rows":      len(df_new),
    }


# ── Standalone ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    app_dir = sys.argv[1] if len(sys.argv) > 1 else None
    result  = run_pipeline(app_dir=app_dir)
    print("\nResult:", result)
