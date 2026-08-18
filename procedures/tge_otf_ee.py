# ============================================
# TGE OTF EE PIPELINE
# ============================================
# Source: https://tge.pl/energia-elektryczna-otf
# Output: {app_dir}/prices/tge_otf_ee.parquet
#
# Callable: run_pipeline(app_dir, log)
# Standalone: python tge_otf_ee.py

import os
import re
import datetime as dt
import time
import random
import requests
import pandas as pd
from io import StringIO

OTF_URL  = "https://tge.pl/energia-elektryczna-otf?dateShow={date}"
TIMEOUT  = 30
RETRIES  = 4

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Connection": "close",
}

NA_TOKENS = {"-", "—", "", None}

EXPECTED_COLS = [
    "date", "product_name", "segment", "product_type",
    "dkr", "vol_mwh", "trades", "value_pln",
    "lop_mwh", "min_price", "max_price",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _business_days(start: dt.date, end: dt.date) -> list:
    return [
        start + dt.timedelta(days=i)
        for i in range((end - start).days + 1)
        if (start + dt.timedelta(days=i)).weekday() < 5
    ]


def _fetch_html(url: str, log) -> str:
    last_err = None
    for attempt in range(1, RETRIES + 1):
        try:
            with requests.Session() as s:
                s.headers.update(DEFAULT_HEADERS)
                r = s.get(url, timeout=TIMEOUT, allow_redirects=True)
                if r.status_code != 200:
                    raise RuntimeError(f"HTTP {r.status_code}")
                return r.text
        except Exception as e:
            last_err = e
            sleep_s = 1.2 * (1.6 ** (attempt - 1)) + random.uniform(0.0, 0.7)
            log(f"    [retry {attempt}/{RETRIES}] {e} | sleep {sleep_s:.1f}s")
            time.sleep(sleep_s)
    raise RuntimeError(f"Failed to fetch {url} | {last_err}")


def _pl_to_float(s: pd.Series) -> pd.Series:
    s = s.astype("string").str.strip()
    s = s.replace(list(NA_TOKENS), pd.NA)
    s = s.str.replace(" ", "", regex=False).str.replace(",", ".", regex=False)
    return pd.to_numeric(s, errors="coerce")


def _fix_price_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in [col for col in df.columns if "(PLN/MWh)" in str(col)]:
        def _fix(x):
            if x in NA_TOKENS:
                return pd.NA
            x = str(x).strip().replace(" ", "")
            if "," in x:
                return x
            try:
                v = float(x)
                if v >= 1000:
                    v /= 100
                return f"{v:.2f}".replace(".", ",")
            except Exception:
                return x
        df[c] = df[c].map(_fix)
    return df


def _infer_segment(contract: str) -> str:
    if not contract or contract in NA_TOKENS:
        return "UNKNOWN"
    s = str(contract).strip()
    seg = s.split("_", 1)[0] if "_" in s else s.split(" ", 1)[0]
    return re.sub(r"\s+", "", seg) or "UNKNOWN"


def _infer_product_type(product_name: str) -> str:
    """Extract Y/Q/M/W from contract name like BASE_Y-26, BASE_Q1-26, PEAK_M01-26."""
    if not product_name or str(product_name) in NA_TOKENS:
        return ""
    parts = str(product_name).split("_")
    if len(parts) >= 2:
        p = parts[1][0].upper()
        if p in ("Y", "Q", "M", "W", "S", "D"):
            return p
    return ""


def _parse_day(html: str, session_date: dt.date) -> pd.DataFrame:
    try:
        tables = pd.read_html(StringIO(html), flavor="lxml")
    except ValueError:
        return pd.DataFrame(columns=EXPECTED_COLS)

    frames = []
    for df in tables:
        df.columns = [str(c).strip() for c in df.columns]
        if "Kontrakt" not in df.columns or "DKR (PLN/MWh)" not in df.columns:
            continue

        df = _fix_price_cols(df)
        df = df.astype("string")
        df = df[[c for c in df.columns if not str(c).startswith("Unnamed")]]

        # Remove summary rows
        mask = df["Kontrakt"].str.lower().str.startswith(
            ("suma", "razem", "total"), na=False
        )
        df = df[~mask]

        flat = pd.DataFrame({
            "date":         session_date.strftime("%Y-%m-%d"),
            "product_name": df["Kontrakt"],
            "segment":      df["Kontrakt"].apply(_infer_segment),
            "product_type": df["Kontrakt"].apply(_infer_product_type),
            "dkr":          _pl_to_float(df["DKR (PLN/MWh)"]),
            "vol_mwh":      _pl_to_float(df.get("Łączny wolumen obrotu (MWh)",
                                                  pd.Series(dtype="string"))),
            "trades":       _pl_to_float(df.get("Liczba transakcji",
                                                  pd.Series(dtype="string"))),
            "value_pln":    _pl_to_float(df.get("Łączna wartość obrotu (PLN)",
                                                  pd.Series(dtype="string"))),
            "lop_mwh":      _pl_to_float(df.get("Łączna liczba otwartych pozycji LOP (MWh)",
                                                  pd.Series(dtype="string"))),
            "min_price":    _pl_to_float(df.get("Kurs min. na sesji (PLN/MWh)",
                                                  pd.Series(dtype="string"))),
            "max_price":    _pl_to_float(df.get("Kurs maks. na sesji (PLN/MWh)",
                                                  pd.Series(dtype="string"))),
        })
        flat = flat.dropna(subset=["dkr"])
        frames.append(flat)

    if not frames:
        return pd.DataFrame(columns=EXPECTED_COLS)

    return (
        pd.concat(frames, ignore_index=True)
        .drop_duplicates(subset=["date", "product_name"], keep="last")
        .reset_index(drop=True)
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def run_pipeline(app_dir: str | None = None, log=print) -> dict:
    """
    Download TGE OTF EE data and update prices/tge_otf_ee.parquet.

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

    prices_dir   = os.path.join(app_dir, "data", "otf")
    os.makedirs(prices_dir, exist_ok=True)
    PATH_PARQUET = os.path.join(prices_dir, "tge_otf_ee.parquet")

    log("=== TGE OTF EE PIPELINE START ===")

    # ── Load existing ──────────────────────────────────────────────────────────
    if os.path.exists(PATH_PARQUET):
        df_existing = pd.read_parquet(PATH_PARQUET)
        df_existing["date"] = pd.to_datetime(df_existing["date"])
        last_date = df_existing["date"].max().date()
        log(f"[OK] Existing: {len(df_existing)} rows, last date: {last_date}")
    else:
        df_existing = pd.DataFrame()
        last_date   = dt.date.today() - dt.timedelta(days=30)
        log("[INFO] No existing data — fetching last 30 days")

    # ── Date range ─────────────────────────────────────────────────────────────
    start_date = last_date + dt.timedelta(days=1)
    end_date   = dt.date.today()

    if start_date > end_date:
        log("[INFO] Already up to date.")
        return {"status": "ok", "message": "Already up to date.",
                "dates_fetched": [], "new_rows": 0}

    dates = _business_days(start_date, end_date)
    if not dates:
        log("[INFO] No trading days to fetch.")
        return {"status": "ok", "message": "No trading days in range.",
                "dates_fetched": [], "new_rows": 0}

    log(f"[INFO] Fetching {len(dates)} trading day(s): {dates[0]} to {dates[-1]}")

    # ── Fetch ──────────────────────────────────────────────────────────────────
    frames        = []
    fetched_dates = []
    errors        = []

    for i, d in enumerate(dates, 1):
        url = OTF_URL.format(date=d.strftime("%d-%m-%Y"))
        log(f"  {i}/{len(dates)}  {d} ...")
        try:
            html   = _fetch_html(url, log)
            df_day = _parse_day(html, d)
            if df_day.empty:
                log(f"  [WARN] No data for {d}")
            else:
                frames.append(df_day)
                fetched_dates.append(d)
                log(f"  [OK] {d}: {len(df_day)} rows")
        except Exception as e:
            log(f"  [ERROR] {d}: {e}")
            errors.append((d, str(e)))

        time.sleep(1.0 + random.uniform(0.0, 0.8))

    if not frames:
        log("[INFO] No new data downloaded.")
        return {"status": "ok", "message": "No new data available yet.",
                "dates_fetched": [], "new_rows": 0}

    df_new = pd.concat(frames, ignore_index=True)
    df_new["date"] = pd.to_datetime(df_new["date"], errors="coerce")
    for col in ["dkr", "vol_mwh", "trades", "value_pln", "lop_mwh", "min_price", "max_price"]:
        df_new[col] = pd.to_numeric(df_new[col], errors="coerce")

    log(f"[OK] New rows: {len(df_new)}")

    # ── Merge + dedup ──────────────────────────────────────────────────────────
    df_all = pd.concat([df_existing, df_new], ignore_index=True)
    df_all["date"] = pd.to_datetime(df_all["date"])
    df_all = (
        df_all
        .drop_duplicates(subset=["date", "product_name"], keep="last")
        .sort_values(["date", "product_name"])
        .reset_index(drop=True)
    )
    log(f"[OK] Total rows after merge: {len(df_all)}")

    if errors:
        log(f"[WARN] {len(errors)} day(s) with errors: {[str(d) for d, _ in errors]}")

    # ── Save (atomic) ──────────────────────────────────────────────────────────
    tmp = PATH_PARQUET + ".tmp"
    df_all.to_parquet(tmp, index=False)
    os.replace(tmp, PATH_PARQUET)
    log(f"[OK] Saved: {PATH_PARQUET}")

    log("=== TGE OTF EE PIPELINE DONE ===")
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
