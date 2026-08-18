# ============================================
# PSE HIS-WLK-CAL PIPELINE
# ============================================
# Source: https://api.raporty.pse.pl/api/his-wlk-cal
# 15-minute actual KSE generation & demand breakdown:
#   demand  - actual KSE load (MW)
#   wi      - actual wind generation (MW)
#   pv      - actual PV generation (MW)
#   swm_p   - pumped storage consumption (MW)
#   jnwrb   - non-dispatchable RES (MW)
#
# Output: {app_dir}/prices/pse_wlk.parquet
#         {app_dir}/prices/pse_wlk_cursor.txt
#
# Callable: run_pipeline(app_dir, log)
# Standalone: python pse_wlk.py

import os
import time
import requests
import pandas as pd

API_URL  = "https://api.raporty.pse.pl/api/his-wlk-cal"
TIMEOUT  = 30
THROTTLE = 0.15

KEEP_COLS = ["dtime", "business_date", "period", "demand", "wi", "pv", "swm_p", "jnwrb"]


def run_pipeline(app_dir: str | None = None, log=print) -> dict:
    """
    Download PSE his-wlk-cal data and update prices/pse_wlk.parquet.

    Uses cursor-based pagination — first run downloads full history,
    subsequent runs resume from the last nextLink.

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

    prices_dir   = os.path.join(app_dir, "data", "rb")
    os.makedirs(prices_dir, exist_ok=True)
    PATH_PARQUET = os.path.join(prices_dir, "pse_wlk.parquet")
    PATH_CURSOR  = os.path.join(prices_dir, "pse_wlk_cursor.txt")

    log("=== PSE WLK PIPELINE START ===")

    # ── Load existing data ─────────────────────────────────────────────────────
    if os.path.exists(PATH_PARQUET):
        df_existing = pd.read_parquet(PATH_PARQUET)
        df_existing["business_date"] = pd.to_datetime(df_existing["business_date"]).dt.date
        last_date = df_existing["business_date"].max()
        log(f"[OK] Existing: {len(df_existing)} rows, last date: {last_date}")
    else:
        df_existing = pd.DataFrame()
        last_date   = None

    # ── Load cursor ────────────────────────────────────────────────────────────
    cursor_url = None
    if os.path.exists(PATH_CURSOR):
        with open(PATH_CURSOR) as f:
            cursor_url = f.read().strip() or None
        if cursor_url:
            log(f"[OK] Resuming from cursor")
    if not cursor_url:
        cursor_url = API_URL
        log("[INFO] No cursor — downloading full history")

    # ── Paginate ───────────────────────────────────────────────────────────────
    new_frames = []
    page       = 0
    url        = cursor_url

    while url:
        try:
            r = requests.get(url, timeout=TIMEOUT)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            log(f"[ERROR] page {page}: {e}")
            break

        records = data.get("value", [])
        if not records:
            break

        df_page = pd.DataFrame(records)
        for col in KEEP_COLS:
            if col not in df_page.columns:
                df_page[col] = None
        df_page = df_page[KEEP_COLS].copy()

        new_frames.append(df_page)
        page += 1

        next_url = data.get("nextLink")

        if page % 50 == 0:
            bd = df_page["business_date"].iloc[-1] if "business_date" in df_page.columns else "?"
            log(f"  [page {page}] up to {bd}, total new rows so far: {sum(len(f) for f in new_frames)}")

        if not next_url or next_url == url:
            # Save final cursor pointing at start of current page so next run re-checks today
            with open(PATH_CURSOR, "w") as f:
                f.write(url)
            url = None
        else:
            with open(PATH_CURSOR, "w") as f:
                f.write(next_url)
            url = next_url
            time.sleep(THROTTLE)

    if not new_frames:
        log("[INFO] No new data.")
        return {"status": "ok", "message": "No new data.", "new_rows": 0}

    # ── Merge & save ───────────────────────────────────────────────────────────
    df_new = pd.concat(new_frames, ignore_index=True)
    df_new["business_date"] = pd.to_datetime(df_new["business_date"]).dt.date
    # PSE marks DST fall-back duplicate hour as "02a:15:00" — strip the 'a'
    df_new["dtime"] = (
        df_new["dtime"].astype(str)
        .str.replace(r"(\d{2})a:", r"\1:", regex=True)
    )
    df_new["dtime"] = pd.to_datetime(df_new["dtime"], format="mixed")

    for col in ["demand", "wi", "pv", "swm_p", "jnwrb"]:
        df_new[col] = pd.to_numeric(df_new[col], errors="coerce")

    df_all = (
        pd.concat([df_existing, df_new], ignore_index=True)
        .sort_values("dtime")
        .drop_duplicates("dtime", keep="last")
        .reset_index(drop=True)
    )

    tmp = PATH_PARQUET + ".tmp"
    df_all.to_parquet(tmp, index=False)
    os.replace(tmp, PATH_PARQUET)

    log(f"[OK] pse_wlk.parquet: {len(df_all)} rows total (+{len(df_new)} new), last date: {df_all['business_date'].max()}")
    log("=== PSE WLK PIPELINE DONE ===")

    return {
        "status":   "ok",
        "message":  f"Updated {len(df_new)} new rows, last date: {df_all['business_date'].max()}",
        "new_rows": len(df_new),
    }


# ── Standalone execution ──────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    app_dir = sys.argv[1] if len(sys.argv) > 1 else None
    result  = run_pipeline(app_dir=app_dir)
    print("\nResult:", result)
