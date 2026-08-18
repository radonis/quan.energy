# ============================================
# FC PIPELINE — Forward Curve (Procedure 2)
# ============================================
# Reads:  fc/fc_coefficients.parquet  (calibrated coefficients)
#         data/otf/tge_otf_ee.parquet (market quotes)
#         fc/calendar_hourly.parquet  (hourly calendar)
# Writes: fc/fc_curves.parquet        (append-only)
#
# Procedure 1 (calibration) is in page_modules/fc_module.py — UI only.
# Callable: run_pipeline(app_dir, asof_date, calib_id, trigger, log)
# Standalone: python fc_pipeline.py [cron|manual]

import os
import sys
import uuid
import datetime as dt
import pandas as pd
import numpy as np

# ── Helpers (shared with page_modules/fc_module.py) ──────────────────────────

def normalize_ratios(ratios, hours):
    weighted_avg = sum(r * h for r, h in zip(ratios, hours)) / sum(hours)
    return [r / weighted_avg for r in ratios]


def load_calendar(fc_dir):
    """Load hourly calendar parquet. Convert from CSV if not yet done."""
    cal_path = os.path.join(fc_dir, "calendar_hourly.parquet")
    if not os.path.exists(cal_path):
        app_dir = os.path.dirname(fc_dir)
        csv_path = os.path.join(app_dir, "examples", "fc", "calendar_hourly.csv")
        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"Calendar CSV not found: {csv_path}")
        cal = pd.read_csv(csv_path, low_memory=False)
        os.makedirs(fc_dir, exist_ok=True)
        cal.to_parquet(cal_path, index=False)
    return pd.read_parquet(cal_path)


def hours_per_period(cal, year):
    """Returns dict: period_key -> hour count for given year (from calendar)."""
    cal_y = cal[cal["year"] == year]
    result = {}
    yr2 = str(year)[-2:]
    result[f"Y-{yr2}"] = len(cal_y)
    for q_col in cal_y["product_QUARTER"].dropna().unique():
        result[q_col] = int((cal_y["product_QUARTER"] == q_col).sum())
    for m_col in cal_y["product_MONTH"].dropna().unique():
        result[m_col] = int((cal_y["product_MONTH"] == m_col).sum())
    return result


def load_quotes(otf_path, asof_date, max_age_days=7):
    """Load OTF BASE quotes: last quote per product <= asof_date, not older than max_age_days."""
    otf = pd.read_parquet(otf_path)
    otf = otf[otf["segment"] == "BASE"].copy()
    otf["date"] = pd.to_datetime(otf["date"]).dt.date
    if isinstance(asof_date, str):
        asof_date = dt.date.fromisoformat(asof_date)
    min_date = asof_date - dt.timedelta(days=max_age_days)
    otf = otf[(otf["date"] <= asof_date) & (otf["date"] >= min_date)]
    otf = otf.sort_values("date").groupby("product_name").last().reset_index()
    otf["price"] = otf["dkr"]
    return otf[["date", "product_name", "price"]].dropna(subset=["price"])


def load_coefficients(fc_coeff_path, calib_id=None):
    """Return (coeff_df, calib_id) for active or specified calibration set."""
    if not os.path.exists(fc_coeff_path):
        return None, None
    df = pd.read_parquet(fc_coeff_path)
    if df.empty:
        return None, None
    if calib_id:
        coeff = df[df["calib_id"] == calib_id]
        cid = calib_id
    else:
        latest_ts = df["calib_ts"].max()
        coeff = df[df["calib_ts"] == latest_ts]
        cid = coeff["calib_id"].iloc[0] if not coeff.empty else None
    return (coeff if not coeff.empty else None), cid


# ── Procedure 2: FC Generation ────────────────────────────────────────────────

_QUARTER_MONTHS = {
    "Q1": [1, 2, 3],
    "Q2": [4, 5, 6],
    "Q3": [7, 8, 9],
    "Q4": [10, 11, 12],
}


def run_pipeline(app_dir, asof_date=None, calib_id=None, trigger="cron", log=print,
                 max_age_days=7, target_years=None):
    sys.path.insert(0, app_dir)
    from shared import OTF_EE_PATH, FC_DIR, FC_COEFF_PATH, FC_CURVES_PATH

    os.makedirs(FC_DIR, exist_ok=True)

    if asof_date is None:
        asof_date = dt.date.today()
    elif isinstance(asof_date, str):
        asof_date = dt.date.fromisoformat(asof_date)

    log(f"FC Pipeline | asof={asof_date} | trigger={trigger}")

    cal = load_calendar(FC_DIR)
    log("Calendar loaded")

    coeff, cid = load_coefficients(FC_COEFF_PATH, calib_id)
    if coeff is None:
        log("ERROR: No calibration set found. Run FC Kalibracja first.")
        return None
    log(f"Coefficients: calib_id={cid}")

    quotes = load_quotes(OTF_EE_PATH, asof_date, max_age_days)
    log(f"Quotes loaded: {len(quotes)} products")

    # Target years: Y quote valid within max_age_days
    y_q = quotes[quotes["product_name"].str.match(r"^BASE_Y-\d{2}$")].copy()
    y_q["year"] = y_q["product_name"].str[-2:].astype(int) + 2000
    if target_years:
        y_q = y_q[y_q["year"].isin(target_years)]

    if y_q.empty:
        log("No valid Y quotes. Nothing to generate.")
        return None

    log(f"Target years: {sorted(y_q['year'].tolist())}")

    # Build coefficient dicts from calibration
    q_coeffs = dict(zip(coeff[coeff["level"] == "Q"]["period"],
                        coeff[coeff["level"] == "Q"]["ratio_norm"]))
    m_coeffs = dict(zip(coeff[coeff["level"] == "M"]["period"],
                        coeff[coeff["level"] == "M"]["ratio_norm"]))

    curve_id = str(uuid.uuid4())
    run_ts = pd.Timestamp.now()
    rows = []
    global_warnings = []

    for _, y_row in y_q.iterrows():
        year = int(y_row["year"])
        y_price = float(y_row["price"])
        yr2 = str(year)[-2:]

        hmap = hours_per_period(cal, year)
        H_Y = hmap.get(f"Y-{yr2}", 8760)

        # Re-normalize Q coefficients with year R hours
        q_keys = [f"Q{i}" for i in range(1, 5)]
        q_raw = [q_coeffs.get(f"Q{i}", 1.0) for i in range(1, 5)]
        q_h = [hmap.get(f"Q-{i}-{yr2}", 0) for i in range(1, 5)]
        q_norm = normalize_ratios(q_raw, q_h) if sum(q_h) > 0 else q_raw
        q_norm_r = dict(zip(q_keys, q_norm))

        # Quarter-level anchoring
        q_market = {}
        for qi in range(1, 5):
            prod = f"BASE_Q-{qi}-{yr2}"
            row = quotes[quotes["product_name"] == prod]
            if not row.empty:
                q_market[f"Q{qi}"] = float(row["price"].iloc[0])

        unquoted_q = [q for q in q_keys if q not in q_market]
        if q_market:
            residual_v = y_price * H_Y - sum(
                q_market[q] * hmap.get(f"Q-{q[1]}-{yr2}", 0) for q in q_market
            )
            denom_q = sum(q_norm_r[q] * hmap.get(f"Q-{q[1]}-{yr2}", 0) for q in unquoted_q)
            k_q = residual_v / denom_q if denom_q > 0 else y_price
        else:
            k_q = y_price

        q_prices = {}
        q_sources = {}
        fallback_q = None
        for qi in range(1, 5):
            q = f"Q{qi}"
            if q in q_market:
                q_prices[q] = q_market[q]
                q_sources[q] = "market"
            else:
                p = k_q * q_norm_r[q]
                if p <= 0:
                    p = y_price * q_norm_r[q]
                    q_sources[q] = "fallback"
                    fallback_q = f"Q residual ≤0, year {year}"
                else:
                    q_sources[q] = "residual"
                q_prices[q] = p

        # Consistency check when all 4Q quoted
        if len(q_market) == 4:
            q_wavg = sum(q_prices[f"Q{i}"] * hmap.get(f"Q-{i}-{yr2}", 0) for i in range(1, 5)) / H_Y
            if abs(q_wavg - y_price) > 0.5:
                global_warnings.append(
                    f"Year {year}: market Q inconsistent with Y (diff={q_wavg - y_price:+.2f} PLN/MWh)"
                )

        # Month-level anchoring per quarter
        for qi in range(1, 5):
            q = f"Q{qi}"
            q_price_final = q_prices[q]
            H_Q = hmap.get(f"Q-{qi}-{yr2}", 0)
            months_nums = _QUARTER_MONTHS[q]

            # Re-normalize M coefficients for this quarter with year R hours
            m_keys_q = [f"M{mn}" for mn in months_nums]
            m_raw_q = [m_coeffs.get(f"M{mn}", 1.0) for mn in months_nums]
            m_h_q = [hmap.get(f"M-{mn:02d}-{yr2}", 0) for mn in months_nums]
            m_norm_q = normalize_ratios(m_raw_q, m_h_q) if sum(m_h_q) > 0 else m_raw_q
            m_norm_r = dict(zip(m_keys_q, m_norm_q))

            # Month market quotes
            m_market = {}
            for mn in months_nums:
                prod = f"BASE_M-{mn:02d}-{yr2}"
                row = quotes[quotes["product_name"] == prod]
                if not row.empty:
                    m_market[f"M{mn}"] = float(row["price"].iloc[0])

            unquoted_m = [f"M{mn}" for mn in months_nums if f"M{mn}" not in m_market]
            if m_market:
                residual_vm = q_price_final * H_Q - sum(
                    m_market[mk] * hmap.get(f"M-{int(mk[1:]):02d}-{yr2}", 0) for mk in m_market
                )
                denom_m = sum(
                    m_norm_r[mk] * hmap.get(f"M-{int(mk[1:]):02d}-{yr2}", 0) for mk in unquoted_m
                )
                k_m = residual_vm / denom_m if denom_m > 0 else q_price_final
            else:
                k_m = q_price_final

            for mn in months_nums:
                mk = f"M{mn}"
                h_m = hmap.get(f"M-{mn:02d}-{yr2}", 0)
                first_day = dt.date(year, mn, 1)
                warn = fallback_q

                if mk in m_market:
                    m_price = m_market[mk]
                    source = "market"
                else:
                    m_price = k_m * m_norm_r[mk]
                    if m_price <= 0:
                        m_price = q_price_final * m_norm_r[mk]
                        source = "fallback"
                        warn = (warn or "") + f" | M residual ≤0: M{mn}"
                    else:
                        source = q_sources[q] if q_sources[q] != "market" else "residual"

                rows.append({
                    "curve_id":   curve_id,
                    "run_ts":     run_ts,
                    "asof_date":  asof_date,
                    "calib_id":   cid,
                    "trigger":    trigger,
                    "year":       year,
                    "month_num":  mn,
                    "quarter":    q,
                    "date":       first_day,
                    "hours":      h_m,
                    "MvsY":       round(m_price / y_price, 6) if y_price else None,
                    "month_price": round(m_price, 4),
                    "source":     source,
                    "y_price":    y_price,
                    "warning":    warn or None,
                })

    if not rows:
        log("No curve rows generated.")
        return None

    df_new = pd.DataFrame(rows)

    # Final consistency check
    for year, grp in df_new.groupby("year"):
        y_price = grp["y_price"].iloc[0]
        check = (grp["month_price"] * grp["hours"]).sum() / grp["hours"].sum()
        diff = abs(check - y_price)
        if diff > 1e-3:
            log(f"WARNING year {year}: weighted avg {check:.4f} ≠ Y_price {y_price:.4f} (diff={diff:.6f})")
        else:
            log(f"Year {year}: ✓ weighted avg = {check:.4f} (tolerance OK)")

    # Append-only save
    if os.path.exists(FC_CURVES_PATH):
        df_existing = pd.read_parquet(FC_CURVES_PATH)
        df_out = pd.concat([df_existing, df_new], ignore_index=True)
    else:
        df_out = df_new

    df_out.to_parquet(FC_CURVES_PATH, index=False)
    log(f"Saved {len(df_new)} rows → fc_curves.parquet (total {len(df_out)})")

    for w in global_warnings:
        log(f"WARNING: {w}")

    return curve_id


if __name__ == "__main__":
    _app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _trigger = sys.argv[1] if len(sys.argv) > 1 else "cron"
    run_pipeline(_app_dir, trigger=_trigger)
