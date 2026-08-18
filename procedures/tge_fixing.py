# ============================================
# TGE PIPELINE — RDN + FixingPricesH + FixingPricesQH
# ============================================
# Can be imported and called as run_pipeline(app_dir),
# or run standalone: python tge_fixing.py

import os
import datetime as dt
import pandas as pd
import requests
from bs4 import BeautifulSoup

# ── Configurable entry point ──────────────────────────────────────────────────

def run_pipeline(app_dir: str | None = None,
                 start_date: dt.date | None = None,
                 end_date: dt.date | None = None,
                 log=print) -> dict:
    """
    Download TGE RDN data and update FixingPricesH.parquet and FixingPricesQH.parquet.

    Parameters
    ----------
    app_dir : str
        Folder containing FixingPricesH.parquet.
        Defaults to the parent of this script's directory.
    start_date : date, optional
        Force fetching from this date (overrides auto-detect).
    log : callable
        Function for progress messages (default: print).

    Returns
    -------
    dict with keys: status ("ok" | "error"), message, dates_fetched, new_rows, qh_rows
    """

    # ── Paths ──────────────────────────────────────────────────────────────
    if app_dir is None:
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    PATH_RDN = os.path.join(app_dir, "data", "arch",    "RDN_fixing.parquet")
    PATH_H   = os.path.join(app_dir, "data", "pl_spot", "FixingPricesH.parquet")
    PATH_QH  = os.path.join(app_dir, "data", "pl_spot", "FixingPricesQH.parquet")
    RDN_URL  = "https://www.tge.pl/energia-elektryczna-rdn?dateShow={date}"

    log("=== START PIPELINE ===")

    # ── Load history ───────────────────────────────────────────────────────
    if os.path.exists(PATH_RDN):
        df_rdn_history = pd.read_parquet(PATH_RDN)
        df_rdn_history["data_fix"] = pd.to_datetime(df_rdn_history["data_fix"])
        log(f"[OK] History loaded: {len(df_rdn_history)} rows, last date: {df_rdn_history['data_fix'].max().date()}")
    else:
        df_rdn_history = pd.DataFrame()
        log("[INFO] No RDN history — starting fresh")

    # ── Determine start date from last PRICED date in FixingPricesH ────────
    # Use the last date where SDAC is filled — not just any date present.
    # This ensures today is re-fetched if SDAC arrived after the last run.
    if os.path.exists(PATH_H):
        df_boot = pd.read_parquet(PATH_H)
        df_boot["fixing_date"] = pd.to_datetime(df_boot["fixing_date"])
        df_priced = df_boot[df_boot["sdac_price_PLN"].notna()]
        if not df_priced.empty:
            last_fix_date = df_priced["fixing_date"].max().date()
            log(f"[INFO] Last fully priced date (SDAC filled): {last_fix_date}")
        else:
            last_fix_date = dt.date.today() - dt.timedelta(days=7)
            log("[INFO] No priced rows yet — fetching last 7 days")
    else:
        last_fix_date = dt.date.today() - dt.timedelta(days=7)
        log("[INFO] No history at all — fetching last 7 days")

    # ── Date range to fetch ────────────────────────────────────────────────
    target_end_date = end_date if end_date is not None else dt.date.today()

    if start_date is not None:
        start = start_date
    else:
        start = last_fix_date + dt.timedelta(days=1)

    # New dates (from last priced date to today)
    new_dates = []
    if start <= target_end_date:
        new_dates = [
            start + dt.timedelta(days=i)
            for i in range((target_end_date - start).days + 1)
        ]

    # Gap detection: find missing dates between first and last date in file
    gap_dates = []
    if os.path.exists(PATH_H):
        df_boot2 = pd.read_parquet(PATH_H)
        df_boot2["fixing_date"] = pd.to_datetime(df_boot2["fixing_date"]).dt.date
        existing_dates = set(df_boot2["fixing_date"].unique())
        if existing_dates:
            first_date = min(existing_dates)
            # Check every date from first to last_fix_date for gaps
            d = first_date
            while d <= last_fix_date:
                if d not in existing_dates:
                    gap_dates.append(d)
                d += dt.timedelta(days=1)
            if gap_dates:
                log(f"[WARN] Gaps detected: {len(gap_dates)} missing date(s): "
                    f"{gap_dates[0]} ... {gap_dates[-1]}")

    dates_to_fetch = sorted(set(gap_dates + new_dates))

    if not dates_to_fetch:
        log("[INFO] Already up to date, no gaps.")
        return {"status": "ok", "message": "Already up to date.",
                "dates_fetched": [], "new_rows": 0, "qh_rows": 0}

    log(f"[INFO] Dates to fetch: {len(dates_to_fetch)} "
        f"({len(gap_dates)} gap(s) + {len(new_dates)} new)")

    # ── Helper functions ───────────────────────────────────────────────────

    def download_rdn(date_):
        url = RDN_URL.format(date=date_.strftime("%d-%m-%Y"))
        r = requests.get(url, timeout=30)
        r.raise_for_status()

        soup  = BeautifulSoup(r.content, "html.parser")
        table = soup.find("table", {"id": "rdn"})
        if table is None:
            return pd.DataFrame()

        rows = table.find_all("tr")

        headers = []
        for th in rows[1].find_all("th"):
            colspan = int(th.get("colspan", 1))
            headers.extend([th.text.strip()] * colspan)

        data = []
        for row in rows[2:]:
            tds = row.find_all("td")
            if tds:
                data.append([td.text.strip() for td in tds])

        df = pd.DataFrame(data)
        if len(headers) == df.shape[1]:
            df.columns = headers

        df["dateShow"] = date_
        return df

    def clean_df(df):
        for col in df.columns:
            if isinstance(df[col], pd.DataFrame):
                continue
            df[col] = (
                df[col]
                .replace("-", pd.NA)
                .astype(str)
                .str.replace(" ", "", regex=False)
                .str.replace(",", ".", regex=False)
            )
            try:
                df[col] = df[col].astype(float)
            except Exception:
                pass
        return df

    def build_fact(df_raw):
        # col 0 = Data dostawy  (e.g. "2026-04-12_H01")
        # col 1 = Typ instrumentu  (60 = hourly, 15 = quarter-hour)
        # col 2 = Fixing I  [PLN/MWh]
        # col 7 = Fixing II / SDAC  [PLN/MWh]

        df = pd.DataFrame()
        df["data_deliv"]    = df_raw.iloc[:, 0].astype(str)
        df["instrument"]    = pd.to_numeric(df_raw.iloc[:, 1], errors="coerce")
        df["f1_price_PLN"]  = pd.to_numeric(df_raw.iloc[:, 2], errors="coerce")
        df["sdac_price_PLN"]= pd.to_numeric(df_raw.iloc[:, 7], errors="coerce")

        # Keep ONLY hourly products (instrument type 60 = 60-minute)
        # Quarter-hour products (15-min) would corrupt the H column
        df = df[df["instrument"] == 60].copy()

        return df

    def build_fact_qh(df_raw):
        # col 0 = Data dostawy  (e.g. "2026-06-12_Q00:15")
        # col 1 = Typ instrumentu  (15 = quarter-hour)
        # col 2 = Fixing I  [PLN/MWh]
        # col 3 = Wolumen F1  [MW]
        # col 7 = Fixing II / SDAC  [PLN/MWh]
        # col 8 = Wolumen SDAC  [MW]

        df = pd.DataFrame()
        df["data_deliv"]     = df_raw.iloc[:, 0].astype(str)
        df["instrument"]     = pd.to_numeric(df_raw.iloc[:, 1], errors="coerce")
        df["f1_price_PLN"]   = pd.to_numeric(df_raw.iloc[:, 2], errors="coerce")
        df["volume_mw"]      = pd.to_numeric(df_raw.iloc[:, 3], errors="coerce")
        df["sdac_price_PLN"] = pd.to_numeric(df_raw.iloc[:, 7], errors="coerce")
        df["sdac_volume_mw"] = pd.to_numeric(df_raw.iloc[:, 8], errors="coerce")

        # Keep ONLY 15-min products (instrument type 15)
        df = df[df["instrument"] == 15].copy()

        return df

    def parse_qh_slot(code):
        """Parse 'YYYY-MM-DD_QHH:MM' (end-time) -> (date_str, H:int, Q:int).

        TGE names 15-min slots by their END time:
          Q00:15 = 00:00-00:15 -> H=1, Q=1
          Q01:00 = 00:45-01:00 -> H=1, Q=4
          Q01:15 = 01:00-01:15 -> H=2, Q=1
        """
        date_str, q_part = code.split("_Q")
        hh, mm = map(int, q_part.split(":"))
        start_total = hh * 60 + mm - 15        # start minute of this slot
        H = start_total // 60 + 1              # 1-based hour (1-24)
        Q = (start_total % 60) // 15 + 1       # 1-based quarter (1-4)
        return date_str, H, Q

    # ── Download loop ──────────────────────────────────────────────────────
    frames    = []
    frames_qh = []
    fetched_dates = []

    for d in dates_to_fetch:
        log(f"  Fetching {d} ...")
        try:
            df_raw = download_rdn(d)
            if df_raw.empty:
                log(f"  [WARN] No data for {d}")
                continue
            df_raw = clean_df(df_raw)

            # 15-min (always attempt, even if hourly is empty)
            df_fact_qh = build_fact_qh(df_raw)
            if not df_fact_qh.empty:
                df_fact_qh["data_fix"] = pd.to_datetime(d)
                frames_qh.append(df_fact_qh)

            # Hourly
            df_fact = build_fact(df_raw)
            if df_fact.empty:
                log(f"  [WARN] No hourly rows for {d}")
                continue
            df_fact["data_fix"] = pd.to_datetime(d)
            frames.append(df_fact)
            fetched_dates.append(d)
            log(f"  [OK] {d}: {len(df_fact)} hourly rows, {len(df_fact_qh)} QH rows")
        except Exception as e:
            log(f"  [ERROR] {d}: {e}")

    if not frames:
        log("[INFO] No new data downloaded.")
        return {"status": "ok", "message": "No new data available yet.",
                "dates_fetched": [], "new_rows": 0, "qh_rows": 0}

    df_new = pd.concat(frames, ignore_index=True)

    # ── Merge + dedup ──────────────────────────────────────────────────────
    df_all = pd.concat([df_rdn_history, df_new], ignore_index=True)
    df_all["data_fix"] = pd.to_datetime(df_all["data_fix"])
    df_all = (
        df_all
        .sort_values("data_fix")
        .drop_duplicates(["data_fix", "data_deliv"], keep="last")
    )
    log(f"[OK] RDN total rows: {len(df_all)}")

    # ── Save RDN (atomic) ──────────────────────────────────────────────────
    tmp = PATH_RDN + ".tmp"
    df_all.to_parquet(tmp, index=False)
    os.replace(tmp, PATH_RDN)
    log("[OK] RDN_fixing.parquet saved")

    # ── Build FixingPricesH ────────────────────────────────────────────────
    # Build new H rows only from freshly downloaded data (df_new),
    # then merge with the existing FixingPricesH.parquet so history is preserved.

    df_n = df_new.copy()
    parts               = df_n["data_deliv"].str.rsplit("_", n=1)
    df_n["delivery_date"]= pd.to_datetime(parts.str[0], errors="coerce")
    df_n["H"]            = parts.str[1].str.extract(r"(\d+)").astype(int)
    df_n["fixing_date"]  = df_n["data_fix"].dt.normalize()

    df_h_new = (
        df_n
        .groupby(["fixing_date", "delivery_date", "H"], as_index=False)
        .agg(
            f1_price_PLN  =("f1_price_PLN",   "mean"),
            sdac_price_PLN=("sdac_price_PLN",  "mean"),
        )
    )
    df_h_new["spread_f1_sdac"] = df_h_new["f1_price_PLN"] - df_h_new["sdac_price_PLN"]

    # Drop anomalous rows where delivery_date <= fixing_date (e.g. same-day data)
    df_h_new = df_h_new[df_h_new["delivery_date"] > df_h_new["fixing_date"]].copy()

    # Load and merge with existing FixingPricesH
    if os.path.exists(PATH_H):
        df_h_existing = pd.read_parquet(PATH_H)
        df_h_existing["fixing_date"]   = pd.to_datetime(df_h_existing["fixing_date"])
        df_h_existing["delivery_date"] = pd.to_datetime(df_h_existing["delivery_date"])
    else:
        df_h_existing = pd.DataFrame()

    df_h = (
        pd.concat([df_h_existing, df_h_new], ignore_index=True)
        .sort_values(["fixing_date", "H"])
        .drop_duplicates(["fixing_date", "H"], keep="last")
        .drop_duplicates(["delivery_date", "H"], keep="last")
        .reset_index(drop=True)
    )
    log(f"[OK] FixingPricesH rows: {len(df_h)}  (+{len(df_h_new)} new)")

    # ── Save FixingPricesH (atomic) ────────────────────────────────────────
    tmp = PATH_H + ".tmp"
    df_h.sort_values(["fixing_date", "H"]).to_parquet(tmp, index=False)
    os.replace(tmp, PATH_H)
    log("[OK] FixingPricesH.parquet saved")

    # ── Build FixingPricesQH ───────────────────────────────────────────────
    qh_rows = 0
    if frames_qh:
        df_qh_new = pd.concat(frames_qh, ignore_index=True)

        # Parse Q slot codes -> delivery_date, H, Q
        _parsed = df_qh_new["data_deliv"].apply(
            lambda c: pd.Series(parse_qh_slot(c), index=["_date_str", "_H", "_Q"])
        )
        df_qh_new["delivery_date"] = pd.to_datetime(_parsed["_date_str"]).dt.date
        df_qh_new["H"]             = _parsed["_H"].astype(int)
        df_qh_new["Q"]             = _parsed["_Q"].astype(int)
        df_qh_new["fixing_date"]   = df_qh_new["data_fix"].dt.date

        df_qh_new = df_qh_new[[
            "fixing_date", "delivery_date", "H", "Q",
            "f1_price_PLN", "volume_mw", "sdac_price_PLN", "sdac_volume_mw",
        ]].copy()

        # Drop anomalous rows where delivery_date <= fixing_date
        df_qh_new = df_qh_new[df_qh_new["delivery_date"] > df_qh_new["fixing_date"]].copy()

        # Load and merge with existing FixingPricesQH
        if os.path.exists(PATH_QH):
            df_qh_existing = pd.read_parquet(PATH_QH)
        else:
            df_qh_existing = pd.DataFrame()

        df_qh = (
            pd.concat([df_qh_existing, df_qh_new], ignore_index=True)
            .sort_values(["fixing_date", "delivery_date", "H", "Q"])
            .drop_duplicates(["fixing_date", "delivery_date", "H", "Q"], keep="last")
            .reset_index(drop=True)
        )
        qh_rows = len(df_qh_new)
        log(f"[OK] FixingPricesQH rows: {len(df_qh)}  (+{qh_rows} new)")

        tmp = PATH_QH + ".tmp"
        df_qh.to_parquet(tmp, index=False)
        os.replace(tmp, PATH_QH)
        log("[OK] FixingPricesQH.parquet saved")
    else:
        log("[INFO] No 15-min data collected — FixingPricesQH not updated")

    log("=== PIPELINE DONE ===")
    return {
        "status":        "ok",
        "message":       f"Updated {len(fetched_dates)} day(s), {len(df_new)} hourly rows, {qh_rows} QH rows.",
        "dates_fetched": [str(d) for d in fetched_dates],
        "new_rows":      len(df_new),
        "qh_rows":       qh_rows,
    }


# ── Standalone execution ──────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    app_dir = sys.argv[1] if len(sys.argv) > 1 else None
    result  = run_pipeline(app_dir=app_dir)
    print("\nResult:", result)
