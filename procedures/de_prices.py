"""
DE DAY-AHEAD PRICES — SMARD (Parse.bot API)

Downloads German spot (day-ahead) prices from SMARD via Parse.bot wrapper.
Aggregates 15-minute prices into hourly prices (mean).
Output: data/de/de_prices.parquet

Callable: run_pipeline(app_dir)
Standalone: python de_prices.py
            PARSE_API_KEY=<key> python de_prices.py
"""

import os
import time
import datetime as dt
import requests
import pandas as pd

SMARD_API_URL = "https://api.parse.bot/scraper/c55baad5-bf80-4113-82fa-eb7a076ee660/get_spot_prices"
API_KEY       = os.environ.get("PARSE_API_KEY", "")
THROTTLE_SEC  = 0.3
EURPLN        = 4.28


def _fetch_day(date_obj, log):
    """Fetch one day of 15-minute SMARD spot prices. Returns DataFrame or None."""
    try:
        r = requests.get(
            SMARD_API_URL,
            headers={"X-API-Key": API_KEY},
            params={
                "region": "DE",
                "date_from": date_obj.strftime("%Y-%m-%d"),
                "date_to": (date_obj + dt.timedelta(days=1)).strftime("%Y-%m-%d")
            },
            timeout=30
        )

        if r.status_code != 200:
            log(f"  [WARN] HTTP {r.status_code} for {date_obj}")
            return None

        data = r.json()
        if data.get("status") != "success" or not data.get("data", {}).get("prices"):
            log(f"  [WARN] Empty response for {date_obj}")
            return None

        prices = data["data"]["prices"]
        df = pd.DataFrame(prices)

        # Parse UTC datetime
        df["datetime_utc"] = pd.to_datetime(df["datetime_utc"], utc=True)
        df["datetime_cet"] = df["datetime_utc"].dt.tz_convert("Europe/Warsaw").dt.tz_localize(None)

        # Extract date and hour (CET, 1-24)
        df["business_date"] = df["datetime_cet"].dt.date
        df["hour_15m"]      = df["datetime_cet"].dt.hour * 4 + df["datetime_cet"].dt.minute // 15

        # Aggregate 15-min to hourly (mean per hour)
        hourly = (
            df.groupby(["business_date", "hour_15m"])
            .agg(price_eur=("price_eur_mwh", "mean"))
            .reset_index()
        )

        # Reconstruct hour (1-24)
        hourly["hour"] = (hourly["hour_15m"] // 4) + 1

        # Get datetime_utc and datetime_cet for each hour (use first 15m record)
        hour_datetimes = (
            df.groupby(["business_date", "hour_15m"])
            .agg(
                datetime_utc=("datetime_utc", "first"),
                datetime_cet=("datetime_cet", "first")
            )
            .reset_index()
        )

        hourly = hourly.merge(hour_datetimes, on=["business_date", "hour_15m"])

        # Add EUR/PLN and price in PLN
        hourly["eur_pln"] = EURPLN
        hourly["price_pln"] = (hourly["price_eur"] * EURPLN).round(4)
        hourly["source"] = "SMARD (Parse.bot)"

        # Strip timezone
        hourly["datetime_utc"] = hourly["datetime_utc"].dt.tz_localize(None)

        result = hourly[[
            "business_date", "hour",
            "datetime_cet", "datetime_utc",
            "price_eur", "eur_pln", "price_pln",
            "source"
        ]].copy()

        log(f"  [OK] {date_obj}: {len(result)} hours")
        return result

    except Exception as e:
        log(f"  [ERROR] {date_obj}: {e}")
        return None


def run_pipeline(app_dir=None, dates=None, log=print):
    """
    Download German day-ahead prices from SMARD and save to de_prices.parquet.

    Parameters
    ----------
    app_dir : str
        Root app folder. Defaults to parent of this script's directory.
    dates : list of datetime.date, optional
        Days to fetch. Defaults to backfilling from last date through yesterday.
    log : callable
        Progress logger.
    """
    if not API_KEY:
        return {"status": "error", "message": "PARSE_API_KEY not set in environment", "new_rows": 0}

    if app_dir is None:
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    out_dir = os.path.join(app_dir, "data", "de")
    os.makedirs(out_dir, exist_ok=True)

    PATH_PARQUET = os.path.join(out_dir, "de_prices.parquet")

    if dates is None:
        _yesterday = dt.date.today() - dt.timedelta(days=1)
        if os.path.exists(PATH_PARQUET):
            _existing_dates = pd.read_parquet(PATH_PARQUET, columns=["business_date"])["business_date"]
            _last_date = pd.to_datetime(_existing_dates).max().date()
            _start = _last_date + dt.timedelta(days=1)
        else:
            _start = _yesterday
        if _start > _yesterday:
            dates = [_yesterday]
        else:
            dates = [_start + dt.timedelta(days=i) for i in range((_yesterday - _start).days + 1)]

    log("=== DE PRICES PIPELINE (SMARD via Parse.bot) START ===")
    log(f"Days to fetch: {len(dates)}")

    # Load existing
    if os.path.exists(PATH_PARQUET):
        df_existing = pd.read_parquet(PATH_PARQUET)
        df_existing["datetime_cet"] = pd.to_datetime(df_existing["datetime_cet"])
        df_existing["business_date"] = pd.to_datetime(df_existing["business_date"]).dt.date
        log(f"[OK] Existing: {len(df_existing)} rows")
    else:
        df_existing = pd.DataFrame()
        log("[INFO] No existing data — starting fresh")

    # Fetch days
    frames = []
    fetched = []
    for d in dates:
        df = _fetch_day(d, log)
        if df is not None and not df.empty:
            frames.append(df)
            fetched.append(d)
        time.sleep(THROTTLE_SEC)

    if not frames:
        msg = "No data fetched."
        log(f"[WARN] {msg}")
        return {"status": "warning", "message": msg, "new_rows": 0}

    df_new = pd.concat(frames, ignore_index=True)

    # Merge + dedup (keep latest per business_date + hour)
    df_all = pd.concat([df_existing, df_new], ignore_index=True)
    df_all["datetime_cet"] = pd.to_datetime(df_all["datetime_cet"])
    df_all["business_date"] = pd.to_datetime(df_all["business_date"]).dt.date
    df_all = (
        df_all
        .sort_values(["business_date", "hour"])
        .drop_duplicates(["business_date", "hour"], keep="last")
        .reset_index(drop=True)
    )
    log(f"[OK] Total rows after merge: {len(df_all)}")

    # Save parquet (atomic)
    tmp = PATH_PARQUET + ".tmp"
    df_all.to_parquet(tmp, index=False)
    os.replace(tmp, PATH_PARQUET)
    log(f"[OK] Saved: {PATH_PARQUET}")

    log("=== DE PRICES PIPELINE DONE ===")
    msg = f"Fetched {len(fetched)} day(s), {len(df_new)} new rows. Total: {len(df_all)} rows."
    return {"status": "ok", "message": msg, "new_rows": len(df_new)}


if __name__ == "__main__":
    import sys
    app_dir = sys.argv[1] if len(sys.argv) > 1 else None
    result = run_pipeline(app_dir=app_dir)
    print("\nResult:", result)
