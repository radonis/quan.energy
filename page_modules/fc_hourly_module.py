"""FC Hourly Plotting — Grafik dobowo-godzinowy.
Pages: FC Ratio (calibration), FC Grafik (generation+export), FC Profil (visualization).
"""

import os
import sys
import uuid
import calendar as _cal
import datetime as dt
from io import BytesIO

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _APP_DIR)

from shared import (
    PARQUET_PATH, DE_PRICES_PATH,
    FC_DIR, FC_CURVES_PATH,
    FC_HOURLY_RATIO_PATH, FC_HOURLY_SCHEDULES_DIR,
    pl_holidays, CHART_THEME,
)

# ── Constants ──────────────────────────────────────────────────────────────────
DAY_TYPES  = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN", "HOL"]
_WD_CODE   = {0:"MON", 1:"TUE", 2:"WED", 3:"THU", 4:"FRI", 5:"SAT", 6:"SUN"}
_MPL       = {1:"Sty",2:"Lut",3:"Mar",4:"Kwi",5:"Maj",6:"Cze",
              7:"Lip",8:"Sie",9:"Wrz",10:"Paź",11:"Lis",12:"Gru"}
_IDX_LBL   = {"FIX1":"FIX1 (Fixing 1)","FIX2":"FIX2/SDAC","DE":"Spot DE"}
_DT_COLORS = {
    "MON":"#1f77b4","TUE":"#ff7f0e","WED":"#2ca02c","THU":"#d62728",
    "FRI":"#9467bd","SAT":"#8c564b","SUN":"#e377c2","HOL":"#7f7f7f"
}


# ── Day-type helpers ──────────────────────────────────────────────────────────

def _day_type(d: dt.date) -> str:
    wd = d.weekday()
    if wd == 5: return "SAT"
    if wd == 6: return "SUN"
    if d in pl_holidays(d.year): return "HOL"
    return _WD_CODE[wd]


def _dst_dates(year: int):
    """(spring_forward, fall_back) — last Sunday of March and October."""
    def _last_sun(y, mo):
        d = dt.date(y, mo, _cal.monthrange(y, mo)[1])
        while d.weekday() != 6:
            d -= dt.timedelta(1)
        return d
    return _last_sun(year, 3), _last_sun(year, 10)


# ── Data loaders ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=7200)
def _load_fix_year(year: int) -> pd.DataFrame:
    """delivery_date, hour 1-24, f1_price_PLN, sdac_price_PLN."""
    if not os.path.exists(PARQUET_PATH):
        return pd.DataFrame()
    df = pd.read_parquet(PARQUET_PATH)
    df["delivery_date"] = pd.to_datetime(df["delivery_date"]).dt.date
    df = df[df["delivery_date"].map(lambda d: d.year) == year].copy()
    df.rename(columns={"H": "hour"}, inplace=True)
    df["hour"] = pd.to_numeric(df["hour"], errors="coerce").astype("Int64")
    return df.dropna(subset=["hour"])


@st.cache_data(ttl=7200)
def _load_de_year(year: int) -> pd.DataFrame:
    """delivery_date, hour 1-24, price (EUR/MWh)."""
    if not os.path.exists(DE_PRICES_PATH):
        return pd.DataFrame()
    df = pd.read_parquet(DE_PRICES_PATH)
    df["business_date"] = pd.to_datetime(df["business_date"]).dt.date
    df = df[df["business_date"].map(lambda d: d.year) == year].copy()
    df.rename(columns={"business_date": "delivery_date"}, inplace=True)
    if "hour" not in df.columns:
        return pd.DataFrame()
    df["hour"] = pd.to_numeric(df["hour"], errors="coerce")
    if not df["hour"].empty and df["hour"].min() == 0:
        df["hour"] = df["hour"] + 1   # 0-23 → 1-24
    df["hour"] = df["hour"].astype("Int64")
    price_col = ("price_eur" if "price_eur" in df.columns
                 else next((c for c in df.columns if "price" in c.lower()), None))
    if price_col is None:
        return pd.DataFrame()
    return (df[["delivery_date", "hour", price_col]]
            .rename(columns={price_col: "price"})
            .dropna(subset=["price"]))


def _get_hourly(index: str, year: int) -> pd.DataFrame:
    """delivery_date, hour 1-24, price."""
    if index == "FIX1":
        df = _load_fix_year(year)
        if df.empty or "f1_price_PLN" not in df.columns:
            return pd.DataFrame()
        return (df[["delivery_date","hour","f1_price_PLN"]]
                .rename(columns={"f1_price_PLN":"price"})
                .dropna(subset=["price"]))
    if index == "FIX2":
        df = _load_fix_year(year)
        if df.empty or "sdac_price_PLN" not in df.columns:
            return pd.DataFrame()
        return (df[["delivery_date","hour","sdac_price_PLN"]]
                .rename(columns={"sdac_price_PLN":"price"})
                .dropna(subset=["price"]))
    return _load_de_year(year)


# ── Coverage report ───────────────────────────────────────────────────────────

def _coverage_df(index: str, year: int) -> pd.DataFrame:
    df    = _get_hourly(index, year)
    sp, fb = _dst_dates(year)
    today  = dt.date.today()
    rows   = []
    for m in range(1, 13):
        last_d   = dt.date(year, m, _cal.monthrange(year, m)[1])
        dst_cnt  = sum(1 for d in [sp, fb] if d.month == m)
        cal_days = _cal.monthrange(year, m)[1] - dst_cnt
        if df.empty or last_d >= today:
            rows.append(dict(month=m, month_name=_MPL[m], days_ok=0,
                             cal_days=cal_days, pct=0.0, dst_excl=dst_cnt, status="brak"))
            continue
        df_m = df[df["delivery_date"].map(lambda d: d.month) == m]
        ok   = int((df_m.groupby("delivery_date")["hour"].count() >= 24).sum())
        st_  = "pełny" if ok >= cal_days else ("częściowy" if ok > 0 else "brak")
        rows.append(dict(month=m, month_name=_MPL[m], days_ok=ok,
                         cal_days=cal_days,
                         pct=round(ok / max(1, cal_days) * 100, 1),
                         dst_excl=dst_cnt, status=st_))
    return pd.DataFrame(rows)


# ── Procedure 1: Compute ratios ───────────────────────────────────────────────

def _compute_ratios(index: str, calib_year: int):
    """
    Returns (ok, ratios_df, coverage_df, warnings, complete_months).
    ratios_df has 2304 rows: 12 months × 8 day_types × 24 hours.
    """
    sp, fb   = _dst_dates(calib_year)
    dst_set  = {sp, fb}
    today    = dt.date.today()
    df_all   = _get_hourly(index, calib_year)
    cov      = _coverage_df(index, calib_year)
    warnings = []

    # Detect complete months
    complete = []
    for m in range(1, 13):
        last_d = dt.date(calib_year, m, _cal.monthrange(calib_year, m)[1])
        if last_d >= today:
            continue
        if df_all.empty:
            continue
        df_m = df_all[
            (df_all["delivery_date"].map(lambda d: d.month) == m) &
            (~df_all["delivery_date"].isin(dst_set))
        ]
        if len(df_m) > 0:
            complete.append(m)

    # Check if mirror fills all 12
    missing_irrec = [
        m for m in range(1, 13)
        if m not in complete and (13 - m) not in complete
    ]
    if missing_irrec:
        for m in missing_irrec:
            warnings.append(
                f"Brak danych dla miesiąca {_MPL[m]} i jego lustra {_MPL[13-m]} "
                f"— kalibracja niemożliwa."
            )
        return False, None, cov, warnings, complete

    # Compute ratios for complete months
    month_ratios  = {}   # m → {(dt_code, h): ratio}
    month_hol_fb  = {}   # m → bool
    month_ss      = {}   # m → {dt_code: sample_size}
    month_cov_val = {}   # m → float
    blocked       = []

    for m in complete:
        df_m = df_all[
            (df_all["delivery_date"].map(lambda d: d.month) == m) &
            (~df_all["delivery_date"].isin(dst_set))
        ].copy()
        df_m["day_type"] = df_m["delivery_date"].map(_day_type)
        avg_m = df_m["price"].mean()

        if abs(avg_m) < 1.0:
            warnings.append(
                f"Miesiąc {_MPL[m]}: |avg_m| = {avg_m:.3f} PLN/MWh < 1 — pominięty."
            )
            blocked.append(m)
            continue

        n_cal  = _cal.monthrange(calib_year, m)[1] - (1 if m in (3, 10) else 0)
        n_days = df_m["delivery_date"].nunique()
        month_cov_val[m] = round(n_days / max(1, n_cal), 3)

        ratios_m = {}
        ss_m     = {}

        for dt_code in ["MON","TUE","WED","THU","FRI","SAT","SUN"]:
            days = df_m[df_m["day_type"] == dt_code]["delivery_date"].unique()
            ss_m[dt_code] = len(days)
            for h in range(1, 25):
                vals = df_m[(df_m["day_type"] == dt_code) & (df_m["hour"] == h)]["price"]
                ratios_m[(dt_code, h)] = (
                    round(float(vals.mean()) / avg_m, 3) if len(vals) > 0 else 1.0
                )

        # HOL — fallback to SUN if no HOL days in this month
        hol_rows = df_m[df_m["day_type"] == "HOL"]
        hol_fb   = len(hol_rows) == 0
        if hol_fb:
            for h in range(1, 25):
                ratios_m[("HOL", h)] = ratios_m.get(("SUN", h), 1.0)
            ss_m["HOL"] = 0
        else:
            ss_m["HOL"] = hol_rows["delivery_date"].nunique()
            for h in range(1, 25):
                vals = hol_rows[hol_rows["hour"] == h]["price"]
                ratios_m[("HOL", h)] = (
                    round(float(vals.mean()) / avg_m, 3) if len(vals) > 0 else 1.0
                )

        month_ratios[m] = ratios_m
        month_hol_fb[m] = hol_fb
        month_ss[m]     = ss_m

    complete = [m for m in complete if m not in blocked]

    # Verify mirrors again after blocking
    missing_irrec2 = [
        m for m in range(1, 13)
        if m not in complete and (13 - m) not in complete
    ]
    if missing_irrec2:
        for m in missing_irrec2:
            warnings.append(
                f"Miesiąc {_MPL[m]}: źródło lustra ({_MPL[13-m]}) zablokowane."
            )
        return False, None, cov, warnings, complete

    # Build 2304-row DataFrame
    rows = []
    for m in range(1, 13):
        if m in complete:
            src_m, mirrored = m, False
        else:
            src_m, mirrored = 13 - m, True

        ratios_src = month_ratios[src_m]
        hol_fb_src = month_hol_fb[src_m]
        ss_src     = month_ss[src_m]
        cov_src    = month_cov_val[src_m]

        for dt_code in DAY_TYPES:
            ss = 0 if mirrored else max(0, ss_src.get(dt_code, 0))
            for h in range(1, 25):
                rows.append({
                    "month":         m,
                    "source_month":  src_m,
                    "is_mirrored":   mirrored,
                    "day_type":      dt_code,
                    "hol_fallback":  (dt_code == "HOL" and hol_fb_src),
                    "hour":          h,
                    "ratio":         ratios_src.get((dt_code, h), 1.0),
                    "sample_size":   ss,
                    "data_coverage": 0.0 if mirrored else cov_src,
                })

    return True, pd.DataFrame(rows), cov, warnings, complete


# ── Save / load ratios ────────────────────────────────────────────────────────

def _save_ratios(ratios_df: pd.DataFrame, index: str, calib_year: int) -> str:
    os.makedirs(FC_DIR, exist_ok=True)
    cid    = str(uuid.uuid4())
    ts     = pd.Timestamp.now()
    df_new = ratios_df.copy()
    df_new["calibration_id"] = cid
    df_new["created_at"]     = ts
    df_new["index"]          = index
    df_new["ratio_year"]     = calib_year
    df_new["accepted"]       = True

    cols = ["calibration_id","created_at","index","ratio_year",
            "month","source_month","is_mirrored","day_type","hol_fallback",
            "hour","ratio","sample_size","data_coverage","accepted"]
    df_new = df_new[cols]

    if os.path.exists(FC_HOURLY_RATIO_PATH):
        existing = pd.read_parquet(FC_HOURLY_RATIO_PATH)
        out = pd.concat([existing, df_new], ignore_index=True)
    else:
        out = df_new

    out.to_parquet(FC_HOURLY_RATIO_PATH, index=False)
    return cid


@st.cache_data(ttl=120)
def _load_active_ratios() -> pd.DataFrame:
    """Latest accepted calibration per (index, ratio_year)."""
    if not os.path.exists(FC_HOURLY_RATIO_PATH):
        return pd.DataFrame()
    df = pd.read_parquet(FC_HOURLY_RATIO_PATH)
    df = df[df["accepted"] == True]
    if df.empty:
        return df
    latest_ids = (df.sort_values("created_at")
                    .groupby(["index","ratio_year"])["calibration_id"]
                    .last())
    return df[df["calibration_id"].isin(latest_ids.values)].copy()


def _active_calibrations_table() -> pd.DataFrame:
    df = _load_active_ratios()
    if df.empty:
        return pd.DataFrame()
    return (df.groupby(["index","ratio_year"])["created_at"]
              .max().reset_index()
              .rename(columns={"index":"Indeks","ratio_year":"Rok",
                               "created_at":"Ostatnia kalibracja"}))


# ── FC curve prices ───────────────────────────────────────────────────────────

def _fc_prices_from_curve(target_year: int) -> dict:
    """Latest FC run for target_year → {month: price} or {}."""
    if not os.path.exists(FC_CURVES_PATH):
        return {}
    df = pd.read_parquet(FC_CURVES_PATH)
    df = df[df["year"] == target_year]
    if df.empty:
        return {}
    latest_ts = df["run_ts"].max()
    df = df[df["run_ts"] == latest_ts]
    return dict(zip(df["month_num"].astype(int), df["month_price"].round(4)))


# ── Procedure 2: Generate schedule ────────────────────────────────────────────

def _ratios_for_variant(index: str, variant: str, weight_pct: int,
                         ratios_df: pd.DataFrame) -> dict:
    """Returns {(month, day_type, hour): ratio}."""
    if variant != "SYNTH":
        yr  = int(variant)
        sub = ratios_df[(ratios_df["index"] == index) & (ratios_df["ratio_year"] == yr)]
        return {(r.month, r.day_type, r.hour): r.ratio for r in sub.itertuples()}

    w   = weight_pct / 100.0
    r25 = ratios_df[(ratios_df["index"] == index) & (ratios_df["ratio_year"] == 2025)]
    r26 = ratios_df[(ratios_df["index"] == index) & (ratios_df["ratio_year"] == 2026)]
    lut25 = {(r.month, r.day_type, r.hour): r.ratio for r in r25.itertuples()}
    lut26 = {(r.month, r.day_type, r.hour): r.ratio for r in r26.itertuples()}
    return {
        k: w * lut25.get(k, 1.0) + (1 - w) * lut26.get(k, 1.0)
        for k in (lut25.keys() | lut26.keys())
    }


def _generate_schedule(index: str, variant: str, weight_pct: int,
                        target_year: int, fc_prices: dict,
                        ratios_df: pd.DataFrame):
    """Returns (schedule_df, diag_df, warnings)."""
    ratio_lut = _ratios_for_variant(index, variant, weight_pct, ratios_df)
    sp, fb    = _dst_dates(target_year)
    warnings  = []

    # Step 1: raw prices per (date, hour), with DST handling
    # month_raws[m] = list of raw floats (NaN for spring H3; double entry for fall H3)
    month_raws   = {m: [] for m in range(1, 13)}
    # raw_records = list of (date, hour, raw) for building schedule
    raw_records  = []
    n_days = 365 + (1 if _cal.isleap(target_year) else 0)

    for i in range(n_days):
        d    = dt.date(target_year, 1, 1) + dt.timedelta(i)
        m    = d.month
        fc_m = fc_prices.get(m)
        if fc_m is None:
            continue
        dt_code = _day_type(d)
        for h in range(1, 25):
            if d == sp and h == 3:
                # Spring-forward: H3 missing
                raw_records.append((d, h, float("nan")))
                # NaN excluded from normalization mean — don't add to month_raws
                continue
            raw = fc_m * ratio_lut.get((m, dt_code, h), 1.0)
            raw_records.append((d, h, raw))
            month_raws[m].append(raw)
            if d == fb and h == 3:
                # Fall-back: H3 counted twice in normalization
                month_raws[m].append(raw)

    # Step 2: compute k_m per month
    k_map     = {}
    diag_rows = []
    for m in range(1, 13):
        fc_m = fc_prices.get(m)
        if fc_m is None:
            warnings.append(f"Brak ceny FC dla {_MPL[m]}")
            k_map[m] = 1.0
            continue
        raws = [r for r in month_raws[m] if not np.isnan(r)]
        if not raws:
            k_map[m] = 1.0
            continue
        avg_raw   = float(np.mean(raws))
        k_m       = fc_m / avg_raw if abs(avg_raw) > 1e-9 else 1.0
        k_map[m]  = k_m
        avg_post  = avg_raw * k_m
        flag      = abs(k_m - 1.0) > 0.03
        diag_rows.append({
            "Miesiąc":    _MPL[m],
            "Cena FC":    round(fc_m, 2),
            "Śr. raw":    round(avg_raw, 2),
            "k_m":        round(k_m, 4),
            "Śr. final":  round(avg_post, 2),
            "Godzin":     len(raws),
            "Flaga":      "⚠️" if flag else "✓",
        })
        if abs(avg_post - fc_m) > 0.01:
            warnings.append(
                f"Test arbitrage-free: {_MPL[m]} diff={abs(avg_post-fc_m):.4f} PLN/MWh"
            )

    # Step 3: build schedule (deduplicate fall-back double hour)
    seen  = set()
    srows = []
    for date_, h, raw in raw_records:
        key = (date_, h)
        if key in seen:
            continue
        seen.add(key)
        m     = date_.month
        k_m   = k_map.get(m, 1.0)
        price = float("nan") if np.isnan(raw) else round(raw * k_m, 2)
        srows.append({"date": date_, "hour": h,
                      "day_type": _day_type(date_), "price": price})

    sched = pd.DataFrame(srows).sort_values(["date","hour"]).reset_index(drop=True)
    diag  = pd.DataFrame(diag_rows)
    return sched, diag, warnings


# ── Save / list schedules ─────────────────────────────────────────────────────

def _save_schedule(sched: pd.DataFrame, index: str, variant: str,
                   weight_pct: int, target_year: int,
                   fc_prices: dict, fc_source: str,
                   calibration_ids: list) -> str:
    os.makedirs(FC_HOURLY_SCHEDULES_DIR, exist_ok=True)
    ts     = pd.Timestamp.now()
    ts_str = ts.strftime("%Y%m%d_%H%M%S")
    w_str  = f"_w{weight_pct}" if variant == "SYNTH" else ""
    fname  = f"schedule_{target_year}_{index}_{variant}{w_str}_{ts_str}.parquet"
    fpath  = os.path.join(FC_HOURLY_SCHEDULES_DIR, fname)

    df = sched.copy()
    df["date"]         = pd.to_datetime(df["date"])
    df["year"]         = target_year
    df["index"]        = index
    df["variant"]      = variant
    df["weight_pct"]   = float(weight_pct) if variant == "SYNTH" else float("nan")
    df["fc_source"]    = fc_source
    df["calib_ids"]    = ",".join(calibration_ids)
    df["generated_at"] = ts
    for m in range(1, 13):
        df[f"fc_m{m:02d}"] = float(fc_prices.get(m, float("nan")))

    df.to_parquet(fpath, index=False)
    return fname


def _list_schedules() -> list:
    if not os.path.exists(FC_HOURLY_SCHEDULES_DIR):
        return []
    files = sorted(
        [f for f in os.listdir(FC_HOURLY_SCHEDULES_DIR) if f.endswith(".parquet")],
        reverse=True
    )
    result = []
    for f in files:
        try:
            df = pd.read_parquet(os.path.join(FC_HOURLY_SCHEDULES_DIR, f),
                                 columns=["year","index","variant","weight_pct",
                                          "fc_source","generated_at"])
            r = df.iloc[0]
            result.append({
                "file":       f,
                "year":       int(r["year"]),
                "index":      str(r["index"]),
                "variant":    str(r["variant"]),
                "weight_pct": (int(r["weight_pct"])
                               if pd.notna(r.get("weight_pct")) else None),
                "fc_source":  str(r["fc_source"]),
                "generated_at": r["generated_at"],
            })
        except Exception:
            pass
    return result


# ── Excel export ──────────────────────────────────────────────────────────────

def _build_excel(sched: pd.DataFrame, index: str, variant: str,
                 weight_pct: int, target_year: int,
                 fc_prices: dict, diag: pd.DataFrame) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        wb      = writer.book
        fmt_num = wb.add_format({"num_format": "0.00"})
        fmt_hdr = wb.add_format({"bold": True, "bg_color": "#D9E1F2", "border": 1})
        fmt_nan = wb.add_format({"bg_color": "#F2F2F2"})

        # Year matrix sheet
        yr_str = str(target_year)
        ws     = wb.add_worksheet(yr_str)
        writer.sheets[yr_str] = ws

        n_days = 365 + (1 if _cal.isleap(target_year) else 0)
        dates  = [dt.date(target_year, 1, 1) + dt.timedelta(i) for i in range(n_days)]

        ws.write(0, 0, "Data", fmt_hdr)
        for hi in range(1, 25):
            ws.write(0, hi, hi, fmt_hdr)

        price_lut = {}
        for r in sched.itertuples():
            price_lut[(r.date, r.hour)] = r.price

        sp, _ = _dst_dates(target_year)

        for ri, d in enumerate(dates, 1):
            ws.write(ri, 0, d.strftime("%Y-%m-%d"), fmt_hdr)
            for hi in range(1, 25):
                p = price_lut.get((d, hi))
                if d == sp and hi == 3:
                    ws.write_blank(ri, hi, None, fmt_nan)
                elif p is None or (isinstance(p, float) and np.isnan(p)):
                    ws.write_blank(ri, hi, None)
                else:
                    ws.write_number(ri, hi, float(p), fmt_num)

        # META sheet
        meta_ws = wb.add_worksheet("META")
        writer.sheets["META"] = meta_ws
        w_str = f"w={weight_pct}%" if variant == "SYNTH" else variant

        # Header info (rows 0-4)
        for ri, (k, v) in enumerate([
            ("Indeks",        index),
            ("Wariant ratio", w_str),
            ("Rok docelowy",  str(target_year)),
            ("Źródło cen FC", "Krzywa FC"),
            ("Wygenerowano",  pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")),
        ]):
            meta_ws.write(ri, 0, k, fmt_hdr)
            meta_ws.write(ri, 1, v)
        ri = 6  # blank row 5, table starts row 6

        # Hours per month for target_year (DST-aware)
        sp_y, fb_y = _dst_dates(target_year)
        m_hours = {}
        for m in range(1, 13):
            h = _cal.monthrange(target_year, m)[1] * 24
            if sp_y.month == m: h -= 1
            if fb_y.month == m: h += 1
            m_hours[m] = h
        total_h = sum(m_hours.values())
        wavg    = (sum(float(fc_prices.get(m, 0)) * m_hours[m]
                       for m in range(1, 13)) / total_h)

        # Column headers
        meta_ws.write(ri, 0, "Miesiąc",           fmt_hdr)
        meta_ws.write(ri, 1, "Cena FC (PLN/MWh)", fmt_hdr)
        meta_ws.write(ri, 2, "Godzin",            fmt_hdr)
        ri += 1

        for m in range(1, 13):
            meta_ws.write(ri, 0, _MPL[m])
            meta_ws.write_number(ri, 1, round(float(fc_prices.get(m, 0)), 2), fmt_num)
            meta_ws.write_number(ri, 2, m_hours[m])
            ri += 1

        # Rok — weighted average
        meta_ws.write(ri, 0, "Rok", fmt_hdr)
        meta_ws.write_number(ri, 1, round(wavg, 2), fmt_num)
        meta_ws.write_number(ri, 2, total_h)
        ri += 2

        # k_m section
        if not diag.empty and "k_m" in diag.columns:
            meta_ws.write(ri, 0, "=== Współczynniki k_m ===", fmt_hdr)
            ri += 1
            for _, row in diag.iterrows():
                meta_ws.write(ri, 0, row["Miesiąc"])
                meta_ws.write_number(ri, 1, float(row["k_m"]), fmt_num)
                ri += 1

    return output.getvalue()


# ═══════════════════════════════════════════════════════════════════════════════
# Page: FC Manual
# ═══════════════════════════════════════════════════════════════════════════════

def render_fc_manual():
    st.header("FC Hourly — Instrukcja obsługi")

    st.markdown("""
### Ogólna zasada
Moduł działa dwuetapowo: najpierw **kalibracja** (raz na jakiś czas), potem **generacja** (na żądanie).

---

### Krok 1 — FC Ratio (kalibracja)

Wchodzisz tu gdy chcesz zaktualizować profil godzinowy.

1. Wybierz **indeks** (FIX1 / FIX2 / DE) i **rok kalibracji** (2025 lub 2026)
2. Kliknij **"Wylicz ratio"**
3. System pokazuje:
   - **Pokrycie danych** — które miesiące mają komplet danych, które są uzupełnione lustrem (np. Lip ← Cze). Dla 2026 miesiące Jul–Gru będą zawsze lustrzane dopóki nie miną
   - **Heatmapę ratio** — wybierz miesiąc, zobaczysz macierz typ dnia × godzina. Wartość 0.722 oznacza że ta godzina jest o 27.8% tańsza od średniej miesiąca
   - **Profile dobowe** — linie dla każdego typu dnia
4. Jeśli wyniki wyglądają sensownie → **"Akceptuj i zapisz"**

**Kiedy rekalibrować:** gdy przybywa nowy pełny miesiąc 2026 (np. w sierpniu masz już lipiec) — warto uruchomić ponownie dla 2026, bo lustro zastąpi się prawdziwymi danymi.

Dla **FIX1 i DE**: kalibracja 2025 i 2026 będą działać bez problemów.
Dla **FIX2**: 2025 jest niemożliwe (za mało danych), 2026 działa (Jan–Jun real + lustro).

---

### Krok 2 — FC Grafik (generacja)

Tu generujesz grafik godzinowy dla roku docelowego (np. 2027).

1. Wybierz **rok docelowy** (2027/2028/2029), **indeks**, **wariant ratio**:
   - `2025` — tylko profil z 2025 r.
   - `2026` — tylko profil z 2026 r.
   - `SYNTH` — mieszanka obu (suwak: 50% = po równo, 100% = tylko 2025, 0% = tylko 2026)
2. Wybierz **źródło cen FC**:
   - *Krzywa FC* — automatycznie pobiera ostatni run z FC Raport (12 cen miesięcznych)
   - *Import ręczny* — wpisujesz 12 liczb samodzielnie
3. Kliknij **"Generuj"**
4. Sprawdź **diagnostykę** — tabela k_m. Wartości blisko 1.0 są OK. Podświetlone na pomarańczowo (>±3%) sygnalizują że struktura tygodniowa roku docelowego różni się od kalibracyjnego (np. 2027 ma inny układ świąt)
5. Podgląd w dwóch zakładkach: heatmapa roku lub tabela miesięczna
6. **"Zapisz grafik"** — zapisuje do pliku Parquet (lista pojawia się na dole)
7. **"Generuj Excel"** → **"Pobierz Excel"** — plik z macierzą dat × godzin + arkusz META

---

### Krok 3 — FC Profil (wizualizacja)

Porównujesz zapisane generacje.

- Wybierz rok/indeks → zakres (cały rok lub miesiąc) → agregację dni (wszystkie/robocze/weekend/konkretny typ)
- **Multi-select wariantów** — możesz nałożyć na jeden wykres 2025 vs 2026 vs SYNTH żeby zobaczyć różnicę w kształcie profilu

---

### Typowy workflow co miesiąc

```
1. Wejdź do FC Ratio  → rekalibruj FIX1 rok 2026 (nowy miesiąc zastąpi lustro)
2. Wejdź do FC Raport → wygeneruj / odśwież krzywą FC dla 2027
3. Wejdź do FC Grafik → Generuj → Zapisz → Eksport Excel
```
""")


# ═══════════════════════════════════════════════════════════════════════════════
# Page: FC Ratio
# ═══════════════════════════════════════════════════════════════════════════════

def render_fc_ratio():
    st.header("FC Ratio — Kalibracja profili godzinowych")

    active = _active_calibrations_table()
    if not active.empty:
        with st.expander("Aktywne kalibracje", expanded=False):
            st.dataframe(active, use_container_width=True, hide_index=True)

    st.subheader("Parametry kalibracji")
    c1, c2 = st.columns(2)
    index      = c1.selectbox("Indeks", list(_IDX_LBL.keys()),
                               format_func=lambda x: _IDX_LBL[x])
    calib_year = c2.selectbox("Rok kalibracji", [2025, 2026], index=1)

    if st.button("Wylicz ratio", type="primary"):
        with st.spinner("Liczenie ratio…"):
            ok, ratios_df, cov, warnings, complete = _compute_ratios(index, calib_year)
        st.session_state["fcratio"] = dict(
            ok=ok, ratios=ratios_df, cov=cov, warnings=warnings,
            complete=complete, index=index, calib_year=calib_year
        )

    res = st.session_state.get("fcratio")
    if res is None:
        return

    for w in res["warnings"]:
        st.warning(w)

    # Coverage
    st.subheader("Pokrycie danych")
    cov_d = res["cov"].copy()
    if res["ok"]:
        cov_d["Lustro"] = cov_d["month"].map(
            lambda m: f"← {_MPL[13-m]}" if m not in res["complete"] else ""
        )
    else:
        cov_d["Lustro"] = ""
    cov_d = cov_d.rename(columns={
        "month_name":"Miesiąc","days_ok":"Dni OK","cal_days":"Dni kal.",
        "pct":"Pokrycie %","dst_excl":"DST wyklucz.","status":"Status"
    })[["Miesiąc","Dni OK","Dni kal.","Pokrycie %","DST wyklucz.","Status","Lustro"]]
    st.dataframe(cov_d, use_container_width=True, hide_index=True)

    if not res["ok"]:
        st.error("Kalibracja niemożliwa — patrz komunikaty powyżej.")
        return

    ratios_df = res["ratios"]

    # Ratio heatmap + line chart
    st.subheader("Tabela i wykres ratio")
    sel_m = st.selectbox(
        "Miesiąc", sorted(ratios_df["month"].unique()),
        format_func=lambda m: _MPL[m]
    )
    df_m    = ratios_df[ratios_df["month"] == sel_m]
    is_mir  = bool(df_m["is_mirrored"].iloc[0])
    hol_fb  = bool(df_m[df_m["day_type"] == "HOL"]["hol_fallback"].any())

    if is_mir:
        src = int(df_m["source_month"].iloc[0])
        st.info(f"Miesiąc lustrzany — dane z {_MPL[src]}")
    if hol_fb:
        st.info("HOL: brak świąt pon–pt w tym miesiącu — ratio skopiowane z SUN")

    # Sample sizes info
    ss_info = (df_m.groupby("day_type")["sample_size"].first()
                   .reindex(DAY_TYPES).fillna(0).astype(int))
    ss_str = "  |  ".join(f"{dt}:{n}" for dt, n in ss_info.items())
    st.caption(f"Liczba dni w próbie: {ss_str}")

    pivot = (df_m.pivot_table(index="day_type", columns="hour",
                              values="ratio", aggfunc="first")
               .reindex(DAY_TYPES))
    pivot.columns = [str(int(h)) for h in pivot.columns]

    tab_heat, tab_line = st.tabs(["Heatmapa", "Profile dobowe"])

    with tab_heat:
        fig = go.Figure(go.Heatmap(
            z=np.round(pivot.values, 3).tolist(),
            x=[str(h) for h in range(1, 25)],
            y=DAY_TYPES,
            colorscale="RdYlGn", zmid=1.0,
            colorbar_title="ratio",
            text=np.round(pivot.values, 3).astype(str),
            texttemplate="%{text}", textfont={"size": 7},
        ))
        fig.update_layout(**CHART_THEME, height=320,
                          title=f"Ratio — {_IDX_LBL[res['index']]} {res['calib_year']} / {_MPL[sel_m]}",
                          xaxis_title="Godzina", yaxis_title="Typ dnia")
        st.plotly_chart(fig, use_container_width=True)

    with tab_line:
        fig2 = go.Figure()
        for dt_code in DAY_TYPES:
            row = df_m[df_m["day_type"] == dt_code].sort_values("hour")
            if row.empty:
                continue
            fig2.add_trace(go.Scatter(
                x=row["hour"].tolist(), y=row["ratio"].tolist(),
                name=dt_code, mode="lines",
                line=dict(color=_DT_COLORS.get(dt_code, "#333"))
            ))
        fig2.add_hline(y=1.0, line_dash="dash", line_color="#999", line_width=1)
        fig2.update_layout(**CHART_THEME, height=350,
                           xaxis_title="Godzina", yaxis_title="Ratio",
                           xaxis=dict(tickvals=list(range(1, 25))))
        st.plotly_chart(fig2, use_container_width=True)

    # Accept & save
    st.subheader("Akceptacja")
    col_save, col_clear = st.columns([2, 1])
    if col_save.button("Akceptuj i zapisz", type="primary"):
        cid = _save_ratios(ratios_df, res["index"], res["calib_year"])
        st.cache_data.clear()
        st.success(f"Zapisano kalibrację {res['index']} {res['calib_year']}. ID: {cid[:8]}…")
        st.session_state.pop("fcratio", None)
        st.rerun()
    if col_clear.button("Wyczyść"):
        st.session_state.pop("fcratio", None)
        st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# Page: FC Grafik
# ═══════════════════════════════════════════════════════════════════════════════

def render_fc_grafik():
    st.header("FC Grafik — Generacja grafika godzinowego")

    ratios_df = _load_active_ratios()
    if ratios_df.empty:
        st.warning("Brak aktywnych kalibracji. Wykonaj kalibrację na stronie FC Ratio.")
        return

    active_cal = _active_calibrations_table()

    # Parameters
    st.subheader("Parametry generacji")
    c1, c2, c3 = st.columns(3)

    target_year = c1.selectbox("Rok docelowy", [2027, 2028, 2029])
    avail_idx   = sorted(active_cal["Indeks"].unique().tolist())
    index       = c2.selectbox("Indeks", avail_idx,
                                format_func=lambda x: _IDX_LBL.get(x, x))

    avail_years = sorted(
        active_cal[active_cal["Indeks"] == index]["Rok"].astype(int).unique().tolist()
    )
    variants = [str(y) for y in avail_years]
    if len(avail_years) >= 2:
        variants.append("SYNTH")

    variant    = c3.selectbox("Wariant ratio", variants,
                               index=len(variants)-1 if variants else 0)
    weight_pct = 50
    if variant == "SYNTH":
        weight_pct = st.slider("Waga ratio 2025 (%)", 0, 100, 50, step=5,
                                help="100% = tylko 2025 | 0% = tylko 2026")

    # FC prices
    st.subheader("Ceny miesięczne FC")
    fc_source = st.radio("Źródło", ["Krzywa FC", "Import ręczny"], horizontal=True)
    fc_curve  = _fc_prices_from_curve(target_year)

    if fc_source == "Krzywa FC":
        if fc_curve and len(fc_curve) == 12:
            fc_prices = fc_curve
            df_show   = pd.DataFrame([
                {"Miesiąc": _MPL[m], "Cena FC (PLN/MWh)": round(v, 2)}
                for m, v in sorted(fc_prices.items())
            ])
            st.dataframe(df_show, use_container_width=True, hide_index=True)
        else:
            st.warning(f"Brak pełnej krzywej FC dla {target_year}. "
                       "Wygeneruj na stronie FC Raport lub użyj importu ręcznego.")
            fc_prices = {}
    else:
        st.write("Wprowadź 12 miesięcznych cen BASE (PLN/MWh):")
        cols_inp  = st.columns(4)
        fc_prices = {}
        for i, m in enumerate(range(1, 13)):
            default = round(float(fc_curve[m]), 2) if fc_curve and m in fc_curve else 350.0
            fc_prices[m] = cols_inp[i % 4].number_input(
                _MPL[m], value=default, step=0.01, key=f"fc_man_{m}"
            )

    if len(fc_prices) < 12:
        st.info("Uzupełnij 12 miesięcznych cen FC, aby wygenerować grafik.")
        return

    # Generate
    if st.button("Generuj", type="primary"):
        with st.spinner("Generowanie grafika…"):
            sched, diag, warnings = _generate_schedule(
                index, variant, weight_pct, target_year, fc_prices, ratios_df
            )
        st.session_state["fcgrafik"] = dict(
            sched=sched, diag=diag, warnings=warnings,
            index=index, variant=variant, weight_pct=weight_pct,
            target_year=target_year, fc_prices=fc_prices.copy(), fc_source=fc_source
        )

    res = st.session_state.get("fcgrafik")
    if res is None:
        return

    for w in res["warnings"]:
        st.warning(w)

    # Diagnostics
    st.subheader("Diagnostyka")
    diag = res["diag"].copy()

    def _style_km(val):
        try:
            if abs(float(val) - 1.0) > 0.03:
                return "background-color:#FFD9C0;color:#8B2200"
        except Exception:
            pass
        return ""

    st.dataframe(
        diag.style.applymap(_style_km, subset=["k_m"]),
        use_container_width=True, hide_index=True
    )

    sched = res["sched"]

    # Preview tabs
    st.subheader("Podgląd")
    tab_h, tab_t = st.tabs(["Heatmapa roku", "Tabela miesięczna"])

    with tab_h:
        sched_piv = sched.copy()
        sched_piv["date_str"] = sched_piv["date"].map(str)
        piv_heat = sched_piv.pivot_table(
            index="hour", columns="date_str", values="price", aggfunc="first"
        )
        fig_h = go.Figure(go.Heatmap(
            z=piv_heat.values.tolist(),
            x=piv_heat.columns.tolist(),
            y=piv_heat.index.tolist(),
            colorscale="RdYlGn_r",
            colorbar_title="PLN/MWh",
        ))
        w_label = f" w={res['weight_pct']}%" if res["variant"] == "SYNTH" else ""
        fig_h.update_layout(
            **CHART_THEME, height=460,
            title=f"Grafik {res['target_year']} — {res['index']} / {res['variant']}{w_label}",
            xaxis_title="Data", yaxis_title="Godzina",
            xaxis=dict(tickangle=-45, nticks=24)
        )
        st.plotly_chart(fig_h, use_container_width=True)

    with tab_t:
        sel_m2 = st.selectbox("Miesiąc", range(1, 13),
                               format_func=lambda m: _MPL[m], key="grafik_tbl_m")
        df_m2  = sched[sched["date"].map(lambda d: d.month) == sel_m2].copy()
        if df_m2.empty:
            st.info("Brak danych.")
        else:
            df_m2["dzień"] = df_m2["date"].map(lambda d: d.strftime("%d.%m"))
            piv_m = (df_m2.pivot_table(index="hour", columns="dzień",
                                       values="price", aggfunc="first")
                       .round(2))
            piv_m.index.name = "H"
            st.dataframe(piv_m, use_container_width=True)

    # Action buttons
    col_sv, col_ex = st.columns(2)
    with col_sv:
        if st.button("Zapisz grafik"):
            rdf = _load_active_ratios()
            cal_ids = []
            yrs = [2025, 2026] if res["variant"] == "SYNTH" else [int(res["variant"])]
            for yr in yrs:
                sub = rdf[(rdf["index"] == res["index"]) & (rdf["ratio_year"] == yr)]
                if not sub.empty:
                    cal_ids.append(str(sub["calibration_id"].iloc[0]))
            fname = _save_schedule(
                sched=res["sched"], index=res["index"], variant=res["variant"],
                weight_pct=res["weight_pct"], target_year=res["target_year"],
                fc_prices=res["fc_prices"], fc_source=res["fc_source"],
                calibration_ids=cal_ids
            )
            st.success(f"Zapisano: {fname}")

    with col_ex:
        if st.button("Generuj Excel"):
            w_s = f"_w{res['weight_pct']}" if res["variant"] == "SYNTH" else ""
            st.session_state["fcgrafik_xl_name"] = (
                f"FC_grafik_{res['target_year']}_{res['index']}"
                f"_{res['variant']}{w_s}.xlsx"
            )
            st.session_state["fcgrafik_xl_data"] = _build_excel(
                sched=res["sched"], index=res["index"], variant=res["variant"],
                weight_pct=res["weight_pct"], target_year=res["target_year"],
                fc_prices=res["fc_prices"], diag=res["diag"]
            )
        if st.session_state.get("fcgrafik_xl_data") is not None:
            st.download_button(
                "Pobierz Excel",
                data=st.session_state["fcgrafik_xl_data"],
                file_name=st.session_state.get("fcgrafik_xl_name", "FC_grafik.xlsx"),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

    # Saved schedules
    st.subheader("Zapisane generacje")
    schedules = _list_schedules()
    if not schedules:
        st.info("Brak zapisanych generacji.")
        return

    for s in schedules:
        ts_s  = pd.Timestamp(s["generated_at"]).strftime("%Y-%m-%d %H:%M")
        w_inf = f" w={s['weight_pct']}%" if s["variant"] == "SYNTH" and s["weight_pct"] is not None else ""
        label = f"**{s['year']}** | {s['index']} | {s['variant']}{w_inf} | {ts_s}"
        c1s, c2s, c3s = st.columns([5, 1, 1])
        c1s.markdown(label)

        if c2s.button("XLS", key=f"rexp_{s['file']}"):
            fpath_s = os.path.join(FC_HOURLY_SCHEDULES_DIR, s["file"])
            df_s    = pd.read_parquet(fpath_s)
            fc_p    = {m: float(df_s[f"fc_m{m:02d}"].iloc[0])
                       for m in range(1, 13) if f"fc_m{m:02d}" in df_s.columns}
            xl_d    = _build_excel(
                sched=df_s[["date","hour","day_type","price"]],
                index=s["index"], variant=s["variant"],
                weight_pct=int(s["weight_pct"] or 50),
                target_year=s["year"], fc_prices=fc_p, diag=pd.DataFrame()
            )
            w_sf = f"_w{int(s['weight_pct'])}" if s["variant"] == "SYNTH" and s["weight_pct"] else ""
            st.download_button(
                "Pobierz", data=xl_d,
                file_name=f"FC_grafik_{s['year']}_{s['index']}_{s['variant']}{w_sf}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key=f"dl_{s['file']}"
            )

        if c3s.button("Usuń", key=f"del_{s['file']}"):
            st.session_state[f"confirm_del_{s['file']}"] = True

        if st.session_state.get(f"confirm_del_{s['file']}"):
            st.warning(f"Usunąć plik `{s['file']}`?")
            ca, cb = st.columns(2)
            if ca.button("Tak, usuń", key=f"yes_{s['file']}"):
                os.remove(os.path.join(FC_HOURLY_SCHEDULES_DIR, s["file"]))
                st.session_state.pop(f"confirm_del_{s['file']}", None)
                st.rerun()
            if cb.button("Anuluj", key=f"no_{s['file']}"):
                st.session_state.pop(f"confirm_del_{s['file']}", None)
                st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# Page: FC Profil
# ═══════════════════════════════════════════════════════════════════════════════

def render_fc_profil():
    st.header("FC Profil — Wizualizacja profili dobowych")

    schedules = _list_schedules()
    if not schedules:
        st.info("Brak zapisanych generacji. Wygeneruj grafik na stronie FC Grafik.")
        return

    # Unique (year, index) pairs
    pairs       = sorted({(s["year"], s["index"]) for s in schedules})
    pair_labels = [f"{y} / {_IDX_LBL.get(i, i)}" for y, i in pairs]
    sel_pi      = st.selectbox("Generacja / rok", range(len(pairs)),
                                format_func=lambda i: pair_labels[i])
    sel_year, sel_idx = pairs[sel_pi]

    pair_sched = [s for s in schedules
                  if s["year"] == sel_year and s["index"] == sel_idx]

    c1, c2, c3 = st.columns(3)

    # Scope
    scope_opts = ["Cały rok"] + [_MPL[m] for m in range(1, 13)]
    scope      = c1.selectbox("Zakres", scope_opts)
    sel_month_num = next(
        (m for m in range(1, 13) if _MPL[m] == scope), None
    ) if scope != "Cały rok" else None

    # Day aggregation
    agg_opts = ["Wszystkie dni", "Dni robocze (MON–FRI)",
                "Weekend+Święta (SAT,SUN,HOL)"] + DAY_TYPES
    agg      = c2.selectbox("Agregacja dni", agg_opts)
    if agg == "Wszystkie dni":
        day_filter = None
    elif agg == "Dni robocze (MON–FRI)":
        day_filter = ["MON","TUE","WED","THU","FRI"]
    elif agg.startswith("Weekend"):
        day_filter = ["SAT","SUN","HOL"]
    else:
        day_filter = [agg]

    # Variant multi-select
    variant_map = {}
    for s in pair_sched:
        w_inf = f" w={s['weight_pct']}%" if s["variant"] == "SYNTH" and s["weight_pct"] is not None else ""
        lbl = f"{s['variant']}{w_inf}"
        if lbl not in variant_map:
            variant_map[lbl] = s["file"]
    sel_variants = c3.multiselect("Warianty ratio", list(variant_map.keys()),
                                   default=list(variant_map.keys())[:1])

    if not sel_variants:
        st.info("Wybierz co najmniej jeden wariant.")
        return

    palette = ["#1f77b4","#ff7f0e","#2ca02c","#d62728","#9467bd","#8c564b"]
    fig     = go.Figure()

    for ci, vlbl in enumerate(sel_variants):
        fpath = os.path.join(FC_HOURLY_SCHEDULES_DIR, variant_map[vlbl])
        try:
            df = pd.read_parquet(fpath)
        except Exception:
            st.warning(f"Nie można wczytać: {variant_map[vlbl]}")
            continue

        df["date"] = pd.to_datetime(df["date"]).dt.date
        if sel_month_num:
            df = df[df["date"].map(lambda d: d.month) == sel_month_num]
        if day_filter:
            df = df[df["day_type"].isin(day_filter)]

        grp = (df.dropna(subset=["price"])
                 .groupby("hour")
                 .agg(mean_price=("price","mean"), n_days=("date","nunique"))
                 .reset_index())

        fig.add_trace(go.Scatter(
            x=grp["hour"].tolist(),
            y=grp["mean_price"].round(2).tolist(),
            name=vlbl, mode="lines+markers",
            line=dict(color=palette[ci % len(palette)], width=2),
            customdata=grp["n_days"].tolist(),
            hovertemplate="H%{x}: %{y:.2f} PLN/MWh | próba: %{customdata} dni<extra></extra>"
        ))

    scope_s = scope if scope != "Cały rok" else "cały rok"
    agg_s   = agg if agg != "Wszystkie dni" else "wszystkie dni"
    fig.update_layout(
        **CHART_THEME, height=440,
        title=f"Profil dobowy — {sel_year} / {_IDX_LBL.get(sel_idx, sel_idx)} | {scope_s} | {agg_s}",
        xaxis_title="Godzina", yaxis_title="PLN/MWh",
        xaxis=dict(tickvals=list(range(1, 25))),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0)
    )
    st.plotly_chart(fig, use_container_width=True)

    # Average table
    if st.checkbox("Pokaż tabelę wartości"):
        tbl_rows = []
        for vlbl in sel_variants:
            fpath = os.path.join(FC_HOURLY_SCHEDULES_DIR, variant_map[vlbl])
            try:
                df = pd.read_parquet(fpath)
                df["date"] = pd.to_datetime(df["date"]).dt.date
                if sel_month_num:
                    df = df[df["date"].map(lambda d: d.month) == sel_month_num]
                if day_filter:
                    df = df[df["day_type"].isin(day_filter)]
                grp = (df.dropna(subset=["price"])
                         .groupby("hour")["price"].mean().round(2)
                         .rename(vlbl))
                tbl_rows.append(grp)
            except Exception:
                pass
        if tbl_rows:
            tbl = pd.concat(tbl_rows, axis=1)
            tbl.index.name = "Godzina"
            st.dataframe(tbl, use_container_width=True)
