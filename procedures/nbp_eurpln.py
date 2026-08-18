# ============================================
# EUR/PLN EXCHANGE RATE — NBP API
# ============================================
# Downloads EUR/PLN mid-rate (table A) from
# api.nbp.pl for every business day.
#
# Adds 30-day forward forecast (status = F)
# equal to the last known actual rate.
#
# Output (in prices/):
#   EURPLN_Rate.parquet / EURPLN_Rate.xlsx
#
# Columns:
#   date       — calendar date
#   rate       — EUR/PLN mid-rate
#   status     — H (historical) | F (forecast)
#
# Callable: run_pipeline(app_dir)
# Standalone: python nbp_eurpln.py

import os
import time
import datetime as dt
import requests
import pandas as pd

API_BASE     = "https://api.nbp.pl/api/exchangerates/rates/a/eur"
CHUNK_DAYS   = 365      # NBP hard limit is 367 — stay safe at 365
FORECAST_DAYS = 30
THROTTLE_SEC = 0.3


def run_pipeline(app_dir: str | None = None, log=print) -> dict:
    """
    Download EUR/PLN exchange rates from NBP and save to prices/.

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

    out_dir = os.path.join(app_dir, "data", "market")
    os.makedirs(out_dir, exist_ok=True)

    PATH_PARQUET = os.path.join(out_dir, "EURPLN_Rate.parquet")
    PATH_EXCEL   = os.path.join(out_dir, "EURPLN_Rate.xlsx")

    log("=== EUR/PLN RATE PIPELINE START ===")

    # ── Load existing historical rows only ────────────────────────────────
    if os.path.exists(PATH_PARQUET):
        df_existing = pd.read_parquet(PATH_PARQUET)
        df_existing = df_existing[df_existing["status"] == "H"].copy()
        if not df_existing.empty:
            df_existing["date"] = pd.to_datetime(df_existing["date"]).dt.date
            last_date = df_existing["date"].max()
            log(f"[OK] Existing: {len(df_existing)} rows, last date: {last_date}")
        else:
            last_date = dt.date(2024, 12, 31)
            log("[INFO] No existing historical data — starting from 2025-01-01")
    else:
        df_existing = pd.DataFrame()
        last_date   = dt.date(2024, 12, 31)
        log("[INFO] No existing data — starting from 2025-01-01")

    # ── Date range ────────────────────────────────────────────────────────
    start_date = last_date + dt.timedelta(days=1)
    end_date   = dt.date.today()

    frames    = []
    new_count = 0

    if start_date <= end_date:
        # Build 365-day chunks
        chunks, cur = [], start_date
        while cur <= end_date:
            chunk_end = min(cur + dt.timedelta(days=CHUNK_DAYS - 1), end_date)
            chunks.append((cur, chunk_end))
            cur = chunk_end + dt.timedelta(days=1)

        log(f"[INFO] {len(chunks)} chunk(s): {start_date} to {end_date}")

        for chunk_start, chunk_end in chunks:
            log(f"  {chunk_start} to {chunk_end} ...")
            try:
                url = f"{API_BASE}/{chunk_start}/{chunk_end}/?format=json"
                r   = requests.get(url, timeout=30)

                if r.status_code == 404:
                    # NBP returns 404 when there are no rates in the range
                    # (e.g. only weekends / holidays)
                    log(f"  [WARN] No rates (holiday/weekend range?)")
                    time.sleep(THROTTLE_SEC)
                    continue

                if r.status_code != 200:
                    log(f"  [WARN] HTTP {r.status_code}: {r.text[:120]}")
                    time.sleep(THROTTLE_SEC)
                    continue

                rates = r.json().get("rates", [])
                if not rates:
                    log(f"  [WARN] No rates in response")
                    time.sleep(THROTTLE_SEC)
                    continue

                df_chunk = pd.DataFrame(rates)
                df_chunk = df_chunk.rename(columns={"effectiveDate": "date", "mid": "rate"})
                df_chunk["date"]   = pd.to_datetime(df_chunk["date"]).dt.date
                df_chunk["rate"]   = pd.to_numeric(df_chunk["rate"], errors="coerce")
                df_chunk["status"] = "H"
                df_chunk = df_chunk[["date", "rate", "status"]].copy()

                frames.append(df_chunk)
                log(f"  [OK] {len(df_chunk)} rows")

            except Exception as e:
                log(f"  [ERROR] {chunk_start}: {e}")

            time.sleep(THROTTLE_SEC)
    else:
        log("[INFO] Already up to date.")

    # ── Merge historical ──────────────────────────────────────────────────
    if frames:
        df_new    = pd.concat(frames, ignore_index=True)
        new_count = len(df_new)
        log(f"[OK] New rows: {new_count}")

        df_hist = pd.concat([df_existing, df_new], ignore_index=True) \
                  if not df_existing.empty else df_new
    elif not df_existing.empty:
        df_hist = df_existing.copy()
    else:
        log("[ERROR] No data at all.")
        return {"status": "error", "message": "No data available.", "new_rows": 0}

    df_hist["date"] = pd.to_datetime(df_hist["date"]).dt.date
    df_hist = (
        df_hist
        .sort_values("date")
        .drop_duplicates("date", keep="last")
        .reset_index(drop=True)
    )
    log(f"[OK] Historical rows after merge: {len(df_hist)}")

    # ── Build 30-day forecast ─────────────────────────────────────────────
    last_rate      = float(df_hist.sort_values("date").iloc[-1]["rate"])
    last_hist_date = df_hist["date"].max()

    forecast_rows = [
        {"date":   last_hist_date + dt.timedelta(days=i),
         "rate":   last_rate,
         "status": "F"}
        for i in range(1, FORECAST_DAYS + 1)
    ]
    df_forecast = pd.DataFrame(forecast_rows)
    log(f"[OK] Forecast rows: {len(df_forecast)}  (rate: {last_rate:.4f})")

    df_all = pd.concat([df_hist, df_forecast], ignore_index=True)
    log(f"[OK] Total rows (H + F): {len(df_all)}")

    # ── Save parquet (atomic) ─────────────────────────────────────────────
    tmp = PATH_PARQUET + ".tmp"
    df_all.to_parquet(tmp, index=False)
    os.replace(tmp, PATH_PARQUET)
    log(f"[OK] Saved: {PATH_PARQUET}")

    # ── Save Excel ────────────────────────────────────────────────────────
    try:
        df_all.to_excel(PATH_EXCEL, index=False, engine="openpyxl")
        log(f"[OK] Saved: {PATH_EXCEL}")
    except Exception as e:
        log(f"[WARN] Excel save failed: {e}")

    log("=== EUR/PLN RATE PIPELINE DONE ===")
    return {
        "status":   "ok",
        "message":  f"{len(df_hist)} historical rows + {len(df_forecast)} forecast rows.",
        "new_rows": new_count,
    }


# ── Standalone ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    app_dir = sys.argv[1] if len(sys.argv) > 1 else None
    result  = run_pipeline(app_dir=app_dir)
    print("\nResult:", result)
