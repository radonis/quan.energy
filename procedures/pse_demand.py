# ============================================
# PSE KSE LOAD PIPELINE
# ============================================
# Source: https://api.raporty.pse.pl/api/kse-load
# 15-minute actual and forecast KSE demand.
#
# Output: {app_dir}/prices/pse_demand.parquet
#         {app_dir}/prices/pse_demand_cursor.txt  (last nextLink for resume)
#
# Callable: run_pipeline(app_dir, log)
# Standalone: python pse_demand.py

import os
import datetime as dt
import time
import requests
import pandas as pd

API_URL  = "https://api.raporty.pse.pl/api/kse-load"
TIMEOUT  = 30
THROTTLE = 0.15


def run_pipeline(app_dir: str | None = None, log=print) -> dict:
    """
    Download PSE KSE LOAD data and update prices/pse_demand.parquet.

    On first run paginates from the API's oldest record forward, saving
    a cursor file so subsequent runs resume exactly where they left off.

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

    prices_dir   = os.path.join(app_dir, "data", "pse")
    os.makedirs(prices_dir, exist_ok=True)
    PATH_PARQUET = os.path.join(prices_dir, "pse_demand.parquet")
    PATH_CURSOR  = os.path.join(prices_dir, "pse_demand_cursor.txt")

    log("=== PSE DEMAND PIPELINE START ===")

    # ── Load existing data ─────────────────────────────────────────────────────
    if os.path.exists(PATH_PARQUET):
        df_existing = pd.read_parquet(PATH_PARQUET)
        df_existing["business_date"] = pd.to_datetime(df_existing["business_date"]).dt.date
        last_date = df_existing["business_date"].max()
        log(f"[OK] Existing: {len(df_existing)} rows, last date: {last_date}")
    else:
        df_existing = pd.DataFrame()
        last_date   = None
        log("[INFO] No existing data — starting from scratch")

    # ── Load cursor (resume URL) ───────────────────────────────────────────────
    if os.path.exists(PATH_CURSOR):
        with open(PATH_CURSOR) as f:
            start_url = f.read().strip()
        log(f"[OK] Resuming from cursor")
    else:
        start_url = API_URL
        log("[INFO] No cursor — paginating from start")

    # ── Paginate ───────────────────────────────────────────────────────────────
    today      = dt.date.today()
    all_new    = []
    url        = start_url
    params     = {}
    pages      = 0
    last_link  = None

    while url:
        try:
            r = requests.get(url, params=params, timeout=TIMEOUT)
            if r.status_code != 200:
                log(f"  [WARN] HTTP {r.status_code}: {r.text[:120]}")
                break
            body   = r.json()
            batch  = body.get("value", [])
            if not batch:
                break

            all_new.extend(batch)
            pages += 1
            next_link = body.get("nextLink")
            last_link = next_link or url  # save the last working cursor

            # Stop if the latest record in this batch is already tomorrow
            batch_dates = {v.get("business_date", "") for v in batch}
            max_date_str = max(d for d in batch_dates if d)
            if max_date_str and dt.date.fromisoformat(max_date_str) > today:
                break

            if next_link:
                url    = next_link
                params = {}
            else:
                break

        except Exception as e:
            log(f"  [ERROR] page {pages}: {e}")
            break

        time.sleep(THROTTLE)

    log(f"[OK] Fetched {len(all_new)} raw records in {pages} pages")

    if not all_new:
        log("[INFO] No new records.")
        return {"status": "ok", "message": "No new data.", "new_rows": 0}

    # ── Build DataFrame ────────────────────────────────────────────────────────
    df_new = pd.DataFrame(all_new)
    df_new["business_date"] = pd.to_datetime(df_new["business_date"]).dt.date
    # PSE marks DST-ambiguous hours as "02a:15:00" — strip the letter suffix
    for _tc in ["dtime", "dtime_utc"]:
        df_new[_tc] = (
            df_new[_tc].astype(str)
            .str.replace(r"(\d{2})([ab]):", r"\1:", regex=True)
        )
    df_new["dtime"]     = pd.to_datetime(df_new["dtime"],     errors="coerce")
    df_new["dtime_utc"] = pd.to_datetime(df_new["dtime_utc"], errors="coerce")
    for col in ["load_actual", "load_fcst"]:
        if col in df_new.columns:
            df_new[col] = pd.to_numeric(df_new[col], errors="coerce")

    # ── Merge + dedup ──────────────────────────────────────────────────────────
    df_all = pd.concat([df_existing, df_new], ignore_index=True)
    df_all["dtime"] = pd.to_datetime(df_all["dtime"])
    df_all = (
        df_all
        .sort_values("dtime")
        .drop_duplicates("dtime", keep="last")
        .reset_index(drop=True)
    )
    log(f"[OK] Total rows after merge: {len(df_all)} "
        f"({df_all['business_date'].nunique()} days)")

    # ── Atomic save ────────────────────────────────────────────────────────────
    tmp = PATH_PARQUET + ".tmp"
    df_all.to_parquet(tmp, index=False)
    os.replace(tmp, PATH_PARQUET)
    log(f"[OK] Saved: {PATH_PARQUET}")

    # Save cursor for next run
    if last_link:
        with open(PATH_CURSOR, "w") as f:
            f.write(last_link)
        log(f"[OK] Cursor saved")

    log("=== PSE DEMAND PIPELINE DONE ===")
    return {
        "status":   "ok",
        "message":  f"Fetched {len(df_new)} rows for {df_new['business_date'].nunique()} days.",
        "new_rows": len(df_new),
    }


if __name__ == "__main__":
    import sys
    app_dir = sys.argv[1] if len(sys.argv) > 1 else None
    result  = run_pipeline(app_dir=app_dir)
    print("\nResult:", result)
