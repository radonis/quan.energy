"""
RB Prices pipeline — manages RB_prices_Q.parquet and RB_prices_H.parquet.

RB_prices_Q  — 15-min balancing market data (master, source of truth)
RB_prices_H  — hourly aggregates derived from Q (never edited directly)

source: F = forecast (price-fcst API), H = history (energy-prices API)

Columns available in both F and H:  cen_cost, cor_cost, ceb_pp_cost, ceb_sr_cost, balance
F only: contracting
H only: sk_cost, csdac_pln, balance_power, sk_cost_power
"""

import os, time, datetime as dt, requests
import pandas as pd

APP_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
Q_PATH   = os.path.join(APP_DIR, "data", "rb", "RB_prices_Q.parquet")
H_PATH   = os.path.join(APP_DIR, "data", "rb", "RB_prices_H.parquet")
PSE_PATH = os.path.join(APP_DIR, "data", "rb", "pse_prices.parquet")


from urllib.parse import quote as _url_quote

def _pse_get(base_url, date_str, timeout=30):
    """GET PSE API with $filter — avoids requests encoding dollar sign as %24."""
    filt = "business_date ge '{}' and business_date le '{}'".format(date_str, date_str)
    url  = base_url + "?" + chr(36) + "filter=" + _url_quote(filt)
    return requests.get(url, timeout=timeout)

FCST_URL    = "https://api.raporty.pse.pl/api/price-fcst"
CONFIRM_URL = "https://api.raporty.pse.pl/api/energy-prices"
TIMEOUT, THROTTLE = 30, 0.2

COLS_BOTH = ["cen_cost", "cor_cost", "ceb_pp_cost", "ceb_sr_cost", "balance"]
COLS_F    = ["contracting"]
COLS_H    = ["sk_cost", "csdac_pln", "balance_power", "sk_cost_power"]
ALL_PRICE_COLS = COLS_BOTH + COLS_F + COLS_H


def _fetch_day_fcst(date_obj, log):
    d = date_obj.strftime("%Y-%m-%d")
    try:
        r = _pse_get(FCST_URL, d, TIMEOUT)
        if r.status_code != 200:
            log(f"  [WARN] HTTP {r.status_code} for {d}"); return None
        records = r.json().get("value", [])
        if not records:
            log(f"  [WARN] No forecast data for {d}"); return None
        df = pd.DataFrame(records)
        df["business_date"] = pd.to_datetime(df["business_date"]).dt.date
        df["dtime"]         = pd.to_datetime(df["dtime"])
        df["dtime_utc"]     = pd.to_datetime(df.get("dtime_utc", pd.NaT))
        df["cen_cost"]    = pd.to_numeric(df.get("cen_fcst",    pd.NA), errors="coerce")
        df["cor_cost"]    = pd.to_numeric(df.get("cor_fcst",    pd.NA), errors="coerce")
        df["ceb_pp_cost"] = pd.to_numeric(df.get("ckoeb_fcst",  pd.NA), errors="coerce")
        df["ceb_sr_cost"] = pd.to_numeric(df.get("ceb_sr_fcst", pd.NA), errors="coerce")
        df["balance"]     = pd.to_numeric(df.get("imb_energy",  pd.NA), errors="coerce")
        df["contracting"] = df.get("contracting", pd.NA)
        keep = ["dtime","dtime_utc","business_date","period","period_utc",
                "publication_ts","cen_cost","cor_cost","ceb_pp_cost",
                "ceb_sr_cost","balance","contracting"]
        df = df[[c for c in keep if c in df.columns]].copy()
        log(f"  [OK] {d}: {len(df)} rows (forecast)"); return df
    except Exception as e:
        log(f"  [ERROR] {d}: {e}"); return None


def _fetch_day_confirm(date_obj, log):
    d = date_obj.strftime("%Y-%m-%d")
    try:
        r = _pse_get(CONFIRM_URL, d, TIMEOUT)
        if r.status_code != 200:
            log(f"  [WARN] HTTP {r.status_code} for {d}"); return None
        records = r.json().get("value", [])
        if not records:
            log(f"  [WARN] No confirmed data for {d}"); return None
        df = pd.DataFrame(records)
        df["business_date"] = pd.to_datetime(df["business_date"]).dt.date
        df["dtime"]         = pd.to_datetime(df["dtime"])
        df["dtime_utc"]     = pd.to_datetime(df.get("dtime_utc", pd.NaT))
        for col in ["cen_cost","cor_cost","ceb_pp_cost","ceb_sr_cost",
                    "balance","sk_cost","csdac_pln","balance_power","sk_cost_power"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        keep = ["dtime","dtime_utc","business_date","period","period_utc",
                "publication_ts","cen_cost","cor_cost","ceb_pp_cost","ceb_sr_cost",
                "balance","sk_cost","csdac_pln","balance_power","sk_cost_power"]
        df = df[[c for c in keep if c in df.columns]].copy()
        log(f"  [OK] {d}: {len(df)} rows (confirmed)"); return df
    except Exception as e:
        log(f"  [ERROR] {d}: {e}"); return None


def _save_to_Q(df_new, source, dates, log):
    df_new = df_new.copy()
    df_new["source"] = source
    if os.path.exists(Q_PATH):
        q = pd.read_parquet(Q_PATH)
        q["business_date"] = pd.to_datetime(q["business_date"]).dt.date
        q["dtime"]         = pd.to_datetime(q["dtime"])
        # Replace only the exact timestamps present in df_new — not the whole
        # day — so quarters not covered by this update (e.g. not yet confirmed)
        # keep their existing value instead of being wiped out.
        q = q[~q["dtime"].isin(df_new["dtime"])]
        q_final = pd.concat([q, df_new], ignore_index=True)
    else:
        q_final = df_new
    q_final = q_final.sort_values(["business_date","dtime"]).reset_index(drop=True)
    tmp = Q_PATH + ".tmp"
    q_final.to_parquet(tmp, index=False)
    os.replace(tmp, Q_PATH)
    log(f"  [OK] RB_prices_Q: {len(q_final)} total rows")
    return q_final


def rebuild_H_from_Q(dates=None):
    if not os.path.exists(Q_PATH):
        raise FileNotFoundError("RB_prices_Q.parquet not found")
    q = pd.read_parquet(Q_PATH)
    q["dtime"]         = pd.to_datetime(q["dtime"])
    q["business_date"] = pd.to_datetime(q["business_date"]).dt.date
    q["H"] = ((q["dtime"].dt.hour * 60 + q["dtime"].dt.minute - 1) // 60 + 1)
    q = q[(q["H"] >= 1) & (q["H"] <= 24)].dropna(subset=["cen_cost"])
    q_rebuild = q[q["business_date"].isin(dates)] if dates is not None else q
    num_cols = [c for c in ALL_PRICE_COLS
                if c in q_rebuild.columns and c != "contracting"
                and pd.api.types.is_numeric_dtype(q_rebuild[c])]
    agg_dict = {col: (col, "mean") for col in num_cols}
    agg_dict["source"] = ("source", lambda x: "F" if "F" in x.values else "H")
    h_new = (
        q_rebuild.groupby(["business_date","H"]).agg(**agg_dict)
        .reset_index().rename(columns={"business_date": "delivery_date"})
    )
    for col in num_cols:
        if col in h_new.columns:
            h_new[col] = h_new[col].round(4)
    if os.path.exists(H_PATH) and dates is not None:
        h_existing = pd.read_parquet(H_PATH)
        h_existing["delivery_date"] = pd.to_datetime(h_existing["delivery_date"]).dt.date
        h_existing = h_existing[~h_existing["delivery_date"].isin(dates)]
        h_final = pd.concat([h_existing, h_new], ignore_index=True)
    else:
        h_final = h_new
    h_final = h_final.sort_values(["delivery_date","H"]).reset_index(drop=True)
    tmp = H_PATH + ".tmp"
    h_final.to_parquet(tmp, index=False)
    os.replace(tmp, H_PATH)
    return len(h_new)


def fast_load(dates=None, log=print):
    if dates is None:
        # price-fcst only fills in each quarter near real time, so "today" is
        # usually incomplete until the day ends — always refresh "yesterday"
        # too so it gets backfilled to a full 24h once it's no longer today.
        _today = dt.date.today()
        dates = [_today - dt.timedelta(days=1), _today]
    log(f"=== FAST LOAD (price-fcst) — {len(dates)} day(s) ===")
    frames, fetched = [], []
    for d in dates:
        df = _fetch_day_fcst(d, log)
        if df is not None:
            frames.append(df); fetched.append(d)
        time.sleep(THROTTLE)
    if not frames:
        return {"status": "ok", "message": "No forecast data.", "dates_fetched": [], "new_rows": 0}
    df_new = pd.concat(frames, ignore_index=True)
    _save_to_Q(df_new, source="F", dates=fetched, log=log)
    n_h = rebuild_H_from_Q(dates=fetched)
    msg = f"Fast load: {len(fetched)} day(s), {len(df_new)} Q rows, {n_h} H rows"
    log(msg)
    return {"status": "ok", "message": msg,
            "dates_fetched": [str(d) for d in fetched], "new_rows": len(df_new)}


def confirm_prices(log=print):
    if not os.path.exists(Q_PATH):
        return {"status": "error", "message": "RB_prices_Q.parquet not found"}
    q = pd.read_parquet(Q_PATH)
    q["business_date"] = pd.to_datetime(q["business_date"]).dt.date
    dates_F = sorted(q[q["source"] == "F"]["business_date"].unique())
    if not dates_F:
        log("No F records to confirm.")
        return {"status": "ok", "message": "Nothing to confirm.", "dates_fetched": [], "new_rows": 0}
    log(f"=== CONFIRM PRICES — {len(dates_F)} day(s) ===")
    frames, fetched, not_yet = [], [], []
    for d in dates_F:
        df = _fetch_day_confirm(d, log)
        if df is None:
            time.sleep(THROTTLE)
            continue
        # PSE sometimes publishes a partial confirm record (e.g. csdac_pln only,
        # cen_cost still missing for some quarters). Only replace the quarters
        # that actually have a confirmed cen_cost — the rest keep their
        # existing F (forecast) row so we don't lose data we already have.
        df_valid = df[df["cen_cost"].notna()]
        if not df_valid.empty:
            frames.append(df_valid); fetched.append(d)
            if len(df_valid) < len(df):
                log(f"  [PARTIAL] {d}: {len(df_valid)}/{len(df)} quarters confirmed — rest kept as forecast")
        else:
            not_yet.append(d)
            log(f"  [WAIT] {d}: confirm data has no cen_cost yet — keeping forecast")
        time.sleep(THROTTLE)
    if not frames:
        msg = "Confirmed data not yet available." if not not_yet else \
              f"cen_cost not yet confirmed for {len(not_yet)} day(s) — kept forecast."
        return {"status": "ok", "message": msg, "dates_fetched": [], "new_rows": 0}
    df_new = pd.concat(frames, ignore_index=True)
    _save_to_Q(df_new, source="H", dates=fetched, log=log)
    n_h = rebuild_H_from_Q(dates=fetched)
    msg = f"Confirmed {len(fetched)} day(s), {len(df_new)} Q rows (F->H)"
    if not_yet:
        msg += f"; {len(not_yet)} day(s) still pending (cen_cost not published)"
    log(msg)
    return {"status": "ok", "message": msg,
            "dates_fetched": [str(d) for d in fetched], "new_rows": len(df_new)}


def migrate_enrich(log=print):
    """One-time: enrich existing Q with extra columns from pse_prices.parquet."""
    if not os.path.exists(Q_PATH):
        return {"status": "error", "message": "RB_prices_Q.parquet not found"}
    if not os.path.exists(PSE_PATH):
        return {"status": "error", "message": "pse_prices.parquet not found"}
    log("Loading files...")
    q   = pd.read_parquet(Q_PATH)
    pse = pd.read_parquet(PSE_PATH)
    q["dtime"]   = pd.to_datetime(q["dtime"])
    pse["dtime"] = pd.to_datetime(pse["dtime"])
    extra_cols = ["cor_cost","ceb_pp_cost","ceb_sr_cost",
                  "balance","sk_cost","csdac_pln","balance_power","sk_cost_power"]
    pse_sub = pse[["dtime"] + [c for c in extra_cols if c in pse.columns]].copy()
    for col in [c for c in extra_cols if c in pse_sub.columns]:
        pse_sub[col] = pd.to_numeric(pse_sub[col], errors="coerce")
    q_merged = q.merge(pse_sub, on="dtime", how="left", suffixes=("", "_pse"))
    for col in extra_cols:
        pse_col = col + "_pse"
        if pse_col in q_merged.columns:
            if col not in q_merged.columns:
                q_merged[col] = q_merged[pse_col]
            else:
                q_merged[col] = q_merged[col].fillna(q_merged[pse_col])
            q_merged.drop(columns=[pse_col], inplace=True)
        elif col not in q_merged.columns:
            q_merged[col] = pd.NA
    q_merged = q_merged.sort_values(["business_date","dtime"]).reset_index(drop=True)
    tmp = Q_PATH + ".tmp"
    q_merged.to_parquet(tmp, index=False)
    os.replace(tmp, Q_PATH)
    log(f"[OK] RB_prices_Q enriched: {len(q_merged)} rows")
    n_h = rebuild_H_from_Q(dates=None)
    log(f"[OK] RB_prices_H rebuilt: {n_h} rows")
    return {"status": "ok", "message": f"Done: {len(q_merged)} Q rows, {n_h} H rows"}


def load_rb_q() -> pd.DataFrame:
    if not os.path.exists(Q_PATH): return pd.DataFrame()
    df = pd.read_parquet(Q_PATH)
    df["dtime"]         = pd.to_datetime(df["dtime"])
    df["business_date"] = pd.to_datetime(df["business_date"]).dt.date
    return df


def load_rb_h() -> pd.DataFrame:
    if not os.path.exists(H_PATH): return pd.DataFrame()
    df = pd.read_parquet(H_PATH)
    df["delivery_date"] = pd.to_datetime(df["delivery_date"]).dt.date
    return df


def run_pipeline(app_dir=None, log=print):
    return confirm_prices(log=log)


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "fast"
    if cmd == "migrate":   print(migrate_enrich())
    elif cmd == "confirm": print(confirm_prices())
    else:                  print(fast_load())
