"""
DE Spot Price Pipeline — netztransparenz.de API
Downloads hourly German EPEX SPOT day-ahead prices.

Endpoint : GET /api/v1/data/Spotmarktpreise/{dateFrom}/{dateTo}
Response : CSV semicolon-separated, price in ct/kWh
Output   : prices/de_spot.parquet

Columns:
  datetime_utc   — UTC start of hour
  date           — UTC date
  hour_utc       — 0-23
  price_eur_mwh  — EUR/MWh  (ct/kWh × 10)

Callable : run_pipeline(app_dir, dates, log)
Standalone:
  python prices/de_spot.py                        # yesterday
  python prices/de_spot.py 2024-01-01 2024-03-31  # date range
"""

import os
import sys
import time
import datetime as dt
import requests
import pandas as pd
from io import StringIO

CLIENT_ID     = "cm_app_ntp_id_fed7cedbb22045b6b26eebef52f1df98"
CLIENT_SECRET = "ntp_eBBbHiFZ9kqvq3if3LBY"
TOKEN_URL     = "https://identity.netztransparenz.de/users/connect/token"
BASE_URL      = "https://ds.netztransparenz.de/api/v1"
TIMEOUT       = 30
THROTTLE      = 0.3


def _get_token(log=print):
    r = requests.post(TOKEN_URL, data={
        "grant_type":    "client_credentials",
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }, timeout=TIMEOUT)
    if not r.ok:
        log(f"  [ERROR] Token failed: {r.status_code} {r.reason}")
        return None
    return r.json()["access_token"]


def _fetch_day(token, date_obj, log):
    """Fetch one UTC calendar day of spot prices. Returns DataFrame or None."""
    d_from = date_obj.strftime("%Y-%m-%dT00:00:00")
    next_day = date_obj + dt.timedelta(days=1)
    d_to   = next_day.strftime("%Y-%m-%dT00:00:00")
    url     = f"{BASE_URL}/data/Spotmarktpreise/{d_from}/{d_to}"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        r = requests.get(url, headers=headers, timeout=TIMEOUT)
        if r.status_code != 200:
            log(f"  [WARN] HTTP {r.status_code} for {date_obj}")
            return None
        text = r.text.strip()
        if not text:
            log(f"  [WARN] Empty response for {date_obj}")
            return None

        df = pd.read_csv(StringIO(text), sep=";", decimal=",")
        df.columns = [c.strip() for c in df.columns]

        # Build UTC datetime from Datum (DD.MM.YYYY) + von (HH:MM)
        df["datetime_utc"] = pd.to_datetime(
            df["Datum"].astype(str) + " " + df["von"].astype(str),
            dayfirst=True,
        )

        price_col = next(c for c in df.columns if "Spotmarktpreis" in c)
        df["price_eur_mwh"] = pd.to_numeric(df[price_col], errors="coerce") * 10

        df["date"]       = df["datetime_utc"].dt.date
        df["hour_utc"]   = df["datetime_utc"].dt.hour
        df["minute_utc"] = df["datetime_utc"].dt.minute

        result = df[["datetime_utc", "date", "hour_utc", "minute_utc", "price_eur_mwh"]].dropna(
            subset=["price_eur_mwh"]
        )
        log(f"  [OK] {date_obj}: {len(result)} rows")
        return result

    except Exception as e:
        log(f"  [ERROR] {date_obj}: {e}")
        return None


def run_pipeline(app_dir=None, dates=None, log=print):
    """
    Download DE EPEX SPOT DA prices and append to prices/de_spot.parquet.

    Parameters
    ----------
    app_dir : str
        Root app folder. Defaults to parent of this script's directory.
    dates : list of datetime.date, optional
        Days to fetch. Defaults to backfilling from the day after the last
        date already in de_spot.parquet through yesterday (so a missed day —
        e.g. nobody clicked Update — gets caught up automatically next run,
        instead of leaving a silent gap).
    log : callable
    """
    if app_dir is None:
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    prices_dir   = os.path.join(app_dir, "data", "de")
    PATH_PARQUET = os.path.join(prices_dir, "de_spot.parquet")

    if dates is None:
        _yesterday = dt.date.today() - dt.timedelta(days=1)
        if os.path.exists(PATH_PARQUET):
            _existing_dates = pd.read_parquet(PATH_PARQUET, columns=["date"])["date"]
            _last_date = pd.to_datetime(_existing_dates).max().date()
            _start = _last_date + dt.timedelta(days=1)
        else:
            _start = _yesterday
        if _start > _yesterday:
            dates = [_yesterday]   # already up to date — still check yesterday
        else:
            dates = [_start + dt.timedelta(days=i) for i in range((_yesterday - _start).days + 1)]

    log("=== DE SPOT PIPELINE START ===")
    log(f"Days to fetch: {len(dates)}")

    # Load existing
    if os.path.exists(PATH_PARQUET):
        df_existing = pd.read_parquet(PATH_PARQUET)
        df_existing["datetime_utc"] = pd.to_datetime(df_existing["datetime_utc"])
        df_existing["date"]         = pd.to_datetime(df_existing["date"]).dt.date
        log(f"[OK] Existing: {len(df_existing)} rows")
    else:
        df_existing = pd.DataFrame()
        log("[INFO] No existing data — starting fresh")

    # Authenticate
    token = _get_token(log)
    if not token:
        return {"status": "error", "message": "Auth token failed.", "new_rows": 0}
    log("[OK] Token acquired")

    # Fetch days
    frames, fetched = [], []
    for d in dates:
        df = _fetch_day(token, d, log)
        if df is not None and not df.empty:
            frames.append(df)
            fetched.append(d)
        time.sleep(THROTTLE)

    if not frames:
        msg = "No data fetched."
        log(f"[WARN] {msg}")
        return {"status": "warning", "message": msg, "new_rows": 0}

    df_new = pd.concat(frames, ignore_index=True)

    # Merge + dedup (keep latest value per UTC hour)
    df_all = pd.concat([df_existing, df_new], ignore_index=True)
    df_all["datetime_utc"] = pd.to_datetime(df_all["datetime_utc"])
    df_all["date"]         = pd.to_datetime(df_all["date"]).dt.date
    df_all = (
        df_all
        .sort_values("datetime_utc")
        .drop_duplicates("datetime_utc", keep="last")
        .reset_index(drop=True)
    )
    df_all["date"]       = pd.to_datetime(df_all["datetime_utc"]).dt.date
    df_all["hour_utc"]   = pd.to_datetime(df_all["datetime_utc"]).dt.hour
    df_all["minute_utc"] = pd.to_datetime(df_all["datetime_utc"]).dt.minute
    log(f"[OK] Total rows after merge: {len(df_all)}")

    # Atomic save
    tmp = PATH_PARQUET + ".tmp"
    df_all.to_parquet(tmp, index=False)
    os.replace(tmp, PATH_PARQUET)
    log(f"[OK] Saved: {PATH_PARQUET}")
    log("=== DE SPOT PIPELINE DONE ===")

    msg = f"Fetched {len(fetched)} day(s), {len(df_new)} new rows. Total: {len(df_all)} rows."
    return {"status": "ok", "message": msg, "new_rows": len(df_new)}


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        d_from = dt.date.fromisoformat(sys.argv[1])
        d_to   = dt.date.fromisoformat(sys.argv[2])
        days   = [d_from + dt.timedelta(days=i) for i in range((d_to - d_from).days + 1)]
    else:
        days = None   # let run_pipeline() auto-backfill since the last saved date

    result = run_pipeline(dates=days)
    print("\nResult:", result)
