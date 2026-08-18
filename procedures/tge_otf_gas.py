# ============================================
# TGE OTF GAS PIPELINE
# ============================================
# Source: https://www.tge.pl/gaz-otf
# Output: {app_dir}/prices/tge_otf_gas.parquet
#
# Callable: run_pipeline(app_dir, log)
# Standalone: python tge_otf_gas.py

import os
import datetime as dt
import time
import random
import requests
import pandas as pd
from io import StringIO

TGE_URL  = "https://www.tge.pl/gaz-otf?dateShow={date}"
TIMEOUT  = 30


def run_pipeline(app_dir: str | None = None, log=print) -> dict:
    """
    Download TGE OTF Gas data and update prices/tge_otf_gas.parquet.

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

    prices_dir = os.path.join(app_dir, "data", "otf")
    os.makedirs(prices_dir, exist_ok=True)

    PATH_PARQUET = os.path.join(prices_dir, "tge_otf_gas.parquet")

    log("=== TGE OTF GAS PIPELINE START ===")

    # ── Load existing ──────────────────────────────────────────────────────────
    if os.path.exists(PATH_PARQUET):
        df_existing = pd.read_parquet(PATH_PARQUET)
        df_existing["date"] = pd.to_datetime(df_existing["date"])
        last_date = df_existing["date"].max().date()
        log(f"[OK] Existing: {len(df_existing)} rows, last date: {last_date}")
    else:
        df_existing = pd.DataFrame()
        last_date = dt.date.today() - dt.timedelta(days=30)
        log("[INFO] No existing data — fetching last 30 days")

    # ── Date range ─────────────────────────────────────────────────────────────
    start_date = last_date + dt.timedelta(days=1)
    end_date   = dt.date.today()

    if start_date > end_date:
        log("[INFO] Already up to date.")
        return {"status": "ok", "message": "Already up to date.",
                "dates_fetched": [], "new_rows": 0}

    # Only weekdays — TGE has no sessions on weekends
    dates = [
        start_date + dt.timedelta(days=i)
        for i in range((end_date - start_date).days + 1)
        if (start_date + dt.timedelta(days=i)).weekday() < 5
    ]

    if not dates:
        log("[INFO] No trading days to fetch.")
        return {"status": "ok", "message": "No trading days in range.",
                "dates_fetched": [], "new_rows": 0}

    log(f"[INFO] Fetching {len(dates)} trading day(s): {dates[0]} to {dates[-1]}")

    # ── Fetch ──────────────────────────────────────────────────────────────────
    frames        = []
    fetched_dates = []

    for i, d in enumerate(dates, 1):
        url = TGE_URL.format(date=d.strftime("%d-%m-%Y"))
        log(f"  {i}/{len(dates)}  {d} ...")
        try:
            r = requests.get(url, timeout=TIMEOUT)
            r.raise_for_status()

            tables = pd.read_html(StringIO(r.text))
            df_day = next((t for t in tables if "Kontrakt" in t.columns), None)

            if df_day is None:
                log(f"  [WARN] No table for {d}")
                time.sleep(1)
                continue

            df_day["date"] = pd.to_datetime(d)
            frames.append(df_day)
            fetched_dates.append(d)
            log(f"  [OK] {d}: {len(df_day)} rows")

        except Exception as e:
            log(f"  [ERROR] {d}: {e}")

        time.sleep(1 + random.random())

    if not frames:
        log("[INFO] No new data downloaded.")
        return {"status": "ok", "message": "No new data available yet.",
                "dates_fetched": [], "new_rows": 0}

    df_new = pd.concat(frames, ignore_index=True)
    log(f"[OK] New rows: {len(df_new)}")

    # ── Clean ──────────────────────────────────────────────────────────────────
    df_new = df_new.loc[:, ~df_new.columns.str.contains("^Unnamed")]

    price_cols = [
        "Kurs pierwszej transakcji (PLN/MWh)",
        "DKR (PLN/MWh)",
        "Kurs min. na sesji (PLN/MWh)",
        "Kurs maks. na sesji (PLN/MWh)",
    ]
    for c in price_cols:
        if c in df_new.columns:
            df_new[c] = pd.to_numeric(df_new[c], errors="coerce") / 100

    num_cols = [
        "Łączny wolumen obrotu (MWh)",
        "Liczba kontraktów",
        "Łączna wartość obrotu (PLN)",
        "Liczba transakcji",
        "Łączna liczba otwartych pozycji LOP (MWh)",
    ]
    for c in num_cols:
        if c in df_new.columns:
            df_new[c] = pd.to_numeric(df_new[c], errors="coerce")

    # Remove summary rows
    df_new = df_new[
        ~df_new["Kontrakt"].str.lower().str.contains("suma|razem", na=False)
    ]

    # Parse contract fields
    _split = df_new["Kontrakt"].str.split("_", expand=True)
    df_new["segment"]      = _split[0]
    df_new["profile"]      = _split[1] if _split.shape[1] > 1 else None
    _period                = _split[2] if _split.shape[1] > 2 else pd.Series([""] * len(df_new))
    df_new["product_type"] = _period.str[0]
    df_new["product_week"] = pd.to_numeric(_period.str.extract(r"W-(\d+)")[0], errors="coerce")
    df_new["product_year"] = pd.to_numeric("20" + _period.str.extract(r"-(\d+)$")[0], errors="coerce")

    # ── Merge + dedup ──────────────────────────────────────────────────────────
    df_all = pd.concat([df_existing, df_new], ignore_index=True)
    df_all["date"] = pd.to_datetime(df_all["date"])
    df_all = (
        df_all
        .drop_duplicates(subset=["date", "Kontrakt"], keep="last")
        .sort_values(["date", "Kontrakt"])
        .reset_index(drop=True)
    )
    log(f"[OK] Total rows after merge: {len(df_all)}")

    # ── Save (atomic) ──────────────────────────────────────────────────────────
    tmp = PATH_PARQUET + ".tmp"
    df_all.to_parquet(tmp, index=False)
    os.replace(tmp, PATH_PARQUET)
    log(f"[OK] Saved: {PATH_PARQUET}")

    log("=== TGE OTF GAS PIPELINE DONE ===")
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
