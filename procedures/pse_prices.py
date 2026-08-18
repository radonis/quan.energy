# ============================================
# PSE PIPELINE — energy-prices
# ============================================
# Downloads 15-min SDAC and cost data from
# https://api.raporty.pse.pl/api/energy-prices
#
# Can be imported and called as run_pipeline(app_dir),
# or run standalone: python pse_prices.py

import os
import time
import datetime as dt
import requests
import pandas as pd

PSE_BASE_URL = "https://api.raporty.pse.pl/api/energy-prices"
PSE_TIMEOUT  = 30
PSE_THROTTLE = 0.2   # seconds between requests


def run_pipeline(app_dir: str | None = None, log=print) -> dict:
    """
    Download PSE energy-prices data and save to prices/pse_prices.parquet
    and prices/pse_prices.xlsx.

    Parameters
    ----------
    app_dir : str
        Root app folder. Defaults to parent of this script's directory.
    log : callable
        Progress logger (default: print).

    Returns
    -------
    dict with keys: status, message, dates_fetched, new_rows
    """

    # ── Paths ──────────────────────────────────────────────────────────────
    if app_dir is None:
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    prices_dir  = os.path.join(app_dir, "data", "rb")
    os.makedirs(prices_dir, exist_ok=True)

    PATH_PARQUET = os.path.join(prices_dir, "pse_prices.parquet")
    PATH_EXCEL   = os.path.join(prices_dir, "pse_prices.xlsx")

    log("=== PSE PIPELINE START ===")

    # ── Load existing data ─────────────────────────────────────────────────
    if os.path.exists(PATH_PARQUET):
        df_existing = pd.read_parquet(PATH_PARQUET)
        df_existing["business_date"] = pd.to_datetime(df_existing["business_date"]).dt.date
        # Use last date with actual prices — not just any date in the file
        df_priced = df_existing[df_existing["cen_cost"].notna()]
        last_date = df_priced["business_date"].max() if not df_priced.empty \
                    else dt.date(2024, 12, 31)
        log(f"[OK] Existing data: {len(df_existing)} rows, last priced date: {last_date}")
    else:
        df_existing = pd.DataFrame()
        last_date   = dt.date(2024, 12, 31)   # start from 2025-01-01
        log("[INFO] No existing data — starting from 2025-01-01")

    # ── Date range ─────────────────────────────────────────────────────────
    start_date = last_date + dt.timedelta(days=1)
    end_date   = dt.date.today()

    if start_date > end_date:
        log("[INFO] Already up to date.")
        return {"status": "ok", "message": "Already up to date.",
                "dates_fetched": [], "new_rows": 0}

    dates = [
        start_date + dt.timedelta(days=i)
        for i in range((end_date - start_date).days + 1)
    ]
    log(f"[INFO] Fetching {len(dates)} day(s): {dates[0]} to {dates[-1]}")

    # ── Download ───────────────────────────────────────────────────────────
    frames        = []
    fetched_dates = []

    for d in dates:
        log(f"  {d} ...")
        try:
            params = {
                "$filter": (
                    f"business_date ge '{d.strftime('%Y-%m-%d')}'"
                    f" and business_date le '{d.strftime('%Y-%m-%d')}'"
                ),
            }
            r = requests.get(PSE_BASE_URL, params=params, timeout=PSE_TIMEOUT)

            if r.status_code != 200:
                log(f"  [WARN] HTTP {r.status_code} for {d}")
                time.sleep(PSE_THROTTLE)
                continue

            records = r.json().get("value", [])
            if not records:
                log(f"  [WARN] No data for {d}")
                time.sleep(PSE_THROTTLE)
                continue

            df_day = pd.DataFrame(records)
            df_day["business_date"] = pd.to_datetime(df_day["business_date"]).dt.date
            df_day["dtime"]         = pd.to_datetime(df_day["dtime"])
            df_day["dtime_utc"]     = pd.to_datetime(df_day["dtime_utc"])

            frames.append(df_day)
            fetched_dates.append(d)
            log(f"  [OK] {d}: {len(df_day)} rows")

        except Exception as e:
            log(f"  [ERROR] {d}: {e}")

        time.sleep(PSE_THROTTLE)

    if not frames:
        log("[INFO] No new data downloaded.")
        return {"status": "ok", "message": "No new data available yet.",
                "dates_fetched": [], "new_rows": 0}

    df_new = pd.concat(frames, ignore_index=True)
    log(f"[OK] New rows: {len(df_new)}")

    # ── Merge + dedup ──────────────────────────────────────────────────────
    df_all = pd.concat([df_existing, df_new], ignore_index=True)
    df_all["business_date"] = pd.to_datetime(df_all["business_date"]).dt.date
    df_all["dtime"]         = pd.to_datetime(df_all["dtime"])

    df_all = (
        df_all
        .sort_values(["business_date", "dtime"])
        .drop_duplicates(["business_date", "dtime"], keep="last")
        .reset_index(drop=True)
    )
    log(f"[OK] Total rows after merge: {len(df_all)}")

    # ── Save parquet (atomic) ──────────────────────────────────────────────
    tmp = PATH_PARQUET + ".tmp"
    df_all.to_parquet(tmp, index=False)
    os.replace(tmp, PATH_PARQUET)
    log(f"[OK] Saved: {PATH_PARQUET}")

    # ── Save Excel ─────────────────────────────────────────────────────────
    try:
        df_all.to_excel(PATH_EXCEL, index=False, engine="openpyxl")
        log(f"[OK] Saved: {PATH_EXCEL}")
    except Exception as e:
        log(f"[WARN] Excel save failed: {e}")

    log("=== PSE PIPELINE DONE ===")
    return {
        "status":        "ok",
        "message":       f"Updated {len(fetched_dates)} day(s), {len(df_new)} new rows.",
        "dates_fetched": [str(d) for d in fetched_dates],
        "new_rows":      len(df_new),
    }


# ── Standalone ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    app_dir = sys.argv[1] if len(sys.argv) > 1 else None
    result  = run_pipeline(app_dir=app_dir)
    print("\nResult:", result)
