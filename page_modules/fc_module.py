"""
page_modules/fc_module.py — Forward Curve module
Procedure 1: render_calibration()  — FC Kalibracja page
Procedure 2: render_report()       — FC Raport page
"""

import os
import sys
import uuid
import datetime as dt
import pandas as pd
import numpy as np
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from io import BytesIO

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared import (APP_DIR, OTF_EE_PATH, FC_DIR, FC_COEFF_PATH, FC_CURVES_PATH, FC_CALENDAR_PATH)

# Import pipeline helpers
_proc_dir = os.path.join(APP_DIR, "procedures")
sys.path.insert(0, _proc_dir)
from fc_pipeline import normalize_ratios, load_calendar, hours_per_period, load_quotes, load_coefficients


# ── Internal helpers ──────────────────────────────────────────────────────────

_QUARTER_MONTHS = {
    "Q1": [1, 2, 3],
    "Q2": [4, 5, 6],
    "Q3": [7, 8, 9],
    "Q4": [10, 11, 12],
}


def _agg_fn(estimator, cut):
    from scipy.stats import trim_mean
    from scipy.stats.mstats import winsorize
    fns = {
        "median":          lambda x: x.median(),
        "trimmed_mean":    lambda x: trim_mean(x.values, cut),
        "winsorized_mean": lambda x: float(winsorize(x.values, limits=cut).mean()),
        "mean":            lambda x: x.mean(),
    }
    return fns[estimator]


def _auto_k2(otf):
    """Return last full year (< current) with all 4Q + Y quoted."""
    today_year = dt.date.today().year
    otf_b = otf[otf["segment"] == "BASE"].copy()
    otf_b["pt"] = otf_b["product_name"].str.extract(r"_(.)")[0]
    otf_b["yr"] = otf_b["product_name"].str[-2:].astype(int) + 2000
    best = None
    for yr in sorted(otf_b["yr"].unique()):
        if yr >= today_year:
            continue
        n_q = otf_b[(otf_b["pt"] == "Q") & (otf_b["yr"] == yr)]["product_name"].nunique()
        n_y = otf_b[(otf_b["pt"] == "Y") & (otf_b["yr"] == yr)]["product_name"].nunique()
        if n_q == 4 and n_y == 1:
            best = yr
    return best


def _run_calibration(otf, cal, year_target, date_from, date_to,
                     estimator_qy, cut_qy, estimator_mq, cut_mq):
    """
    Run Procedure 1 calibration.
    Returns (result_dict, error_str). On success error_str is None.
    """
    yr2 = str(year_target)[-2:]
    cal_y = cal[cal["year"] == year_target]

    otf_b = otf[otf["segment"] == "BASE"].copy()
    otf_b["date"] = pd.to_datetime(otf_b["date"]).dt.date
    otf_filt = otf_b[(otf_b["date"] >= date_from) & (otf_b["date"] <= date_to)]

    fn_qy = _agg_fn(estimator_qy, cut_qy)
    fn_mq = _agg_fn(estimator_mq, cut_mq)

    # ── Q vs Y ────────────────────────────────────────────────────────────────
    q_products = [f"BASE_Q-{i}-{yr2}" for i in range(1, 5)]
    y_product = f"BASE_Y-{yr2}"
    all_qy = set(q_products + [y_product])

    otf_qy = otf_filt[otf_filt["product_name"].isin(all_qy)]
    dates_sets = otf_qy.groupby("date")["product_name"].apply(set)
    valid_dates = dates_sets[dates_sets.apply(lambda s: all_qy.issubset(s))].index.tolist()

    if not valid_dates:
        return None, (f"Brak dat z kompletnymi notowaniami Q1–Q4 + Y dla roku {year_target}. "
                      "Wybierz inny rok bazowy lub rozszerz zakres dat.")

    # Hours per quarter for year_target
    q_hours = {f"Q{i}": int((cal_y["product_QUARTER"] == f"Q-{i}-{yr2}").sum()) for i in range(1, 5)}

    rows_qy = []
    otf_qy_v = otf_filt[otf_filt["product_name"].isin(all_qy) & otf_filt["date"].isin(valid_dates)]
    for date, grp in otf_qy_v.groupby("date"):
        grp_d = grp.set_index("product_name")["dkr"]
        y_p = float(grp_d[y_product])
        for i in range(1, 5):
            q_p = float(grp_d[f"BASE_Q-{i}-{yr2}"])
            rows_qy.append({"date": date, "quarter": f"Q{i}", "q_price": q_p,
                            "y_price": y_p, "QvsY_pct": q_p / y_p, "hours": q_hours[f"Q{i}"]})
    df_qvsy = pd.DataFrame(rows_qy)

    qvsy_raw = []
    for qi in range(1, 5):
        q = f"Q{qi}"
        vals = df_qvsy[df_qvsy["quarter"] == q]["QvsY_pct"]
        qvsy_raw.append({"quarter": q, "ratio_raw": fn_qy(vals),
                         "hours": q_hours[q], "n_obs": len(vals)})
    df_qvsy_est = pd.DataFrame(qvsy_raw)
    df_qvsy_est["ratio_norm"] = normalize_ratios(
        df_qvsy_est["ratio_raw"].tolist(), df_qvsy_est["hours"].tolist()
    )

    # Verify Q/Y normalization
    check_qy = sum(r * h for r, h in zip(df_qvsy_est["ratio_norm"], df_qvsy_est["hours"])) / sum(df_qvsy_est["hours"])

    # ── M vs Q ────────────────────────────────────────────────────────────────
    rows_mq = []
    missing_quarters = []
    for qi in range(1, 5):
        q_prod = f"BASE_Q-{qi}-{yr2}"
        months_str = [f"{m:02d}" for m in _QUARTER_MONTHS[f"Q{qi}"]]
        m_prods = [f"BASE_M-{m}-{yr2}" for m in months_str]
        req = set(m_prods + [q_prod])

        otf_mq = otf_filt[otf_filt["product_name"].isin(req)]
        dates_mq = otf_mq.groupby("date")["product_name"].apply(set)
        valid_mq = dates_mq[dates_mq.apply(lambda s: req.issubset(s))].index.tolist()

        if not valid_mq:
            missing_quarters.append(f"Q{qi}")
            continue

        otf_mq_v = otf_mq[otf_mq["date"].isin(valid_mq)]
        for date, grp in otf_mq_v.groupby("date"):
            grp_d = grp.set_index("product_name")["dkr"]
            q_p = float(grp_d[q_prod])
            for m_str, mn in zip(months_str, _QUARTER_MONTHS[f"Q{qi}"]):
                m_prod = f"BASE_M-{m_str}-{yr2}"
                if m_prod not in grp_d.index:
                    continue
                m_p = float(grp_d[m_prod])
                h_m = int((cal_y["product_MONTH"] == f"M-{m_str}-{yr2}").sum())
                rows_mq.append({"date": date, "quarter": f"Q{qi}",
                                "month": f"M{mn}", "month_num": mn,
                                "m_price": m_p, "q_price": q_p,
                                "MvsQ_pct": m_p / q_p, "hours": h_m})

    df_mvsq = pd.DataFrame(rows_mq) if rows_mq else pd.DataFrame(
        columns=["date", "quarter", "month", "month_num", "m_price", "q_price", "MvsQ_pct", "hours"]
    )

    # Aggregate & normalize M/Q per quarter
    mvsq_rows = []
    for qi in range(1, 5):
        q = f"Q{qi}"
        for mn in _QUARTER_MONTHS[q]:
            mk = f"M{mn}"
            m_str = f"{mn:02d}"
            h_m = int((cal_y["product_MONTH"] == f"M-{m_str}-{yr2}").sum())
            mask = (df_mvsq["quarter"] == q) & (df_mvsq["month"] == mk) if not df_mvsq.empty else pd.Series([], dtype=bool)
            grp_vals = df_mvsq.loc[mask, "MvsQ_pct"] if not df_mvsq.empty and mask.any() else pd.Series(dtype=float)
            if len(grp_vals) > 0:
                r_raw = fn_mq(grp_vals)
                n_obs = len(grp_vals)
            else:
                r_raw = 1.0
                n_obs = 0
            mvsq_rows.append({"quarter": q, "month": mk, "month_num": mn,
                              "ratio_raw": r_raw, "hours": h_m, "n_obs": n_obs})

    df_mvsq_est = pd.DataFrame(mvsq_rows)
    norm_parts = []
    for q in [f"Q{i}" for i in range(1, 5)]:
        sub = df_mvsq_est[df_mvsq_est["quarter"] == q].copy()
        ratios = sub["ratio_raw"].tolist()
        hours = sub["hours"].tolist()
        sub["ratio_norm"] = normalize_ratios(ratios, hours) if sum(hours) > 0 else ratios
        norm_parts.append(sub)
    df_mvsq_est = pd.concat(norm_parts, ignore_index=True)

    check_mq = {}
    for q in [f"Q{i}" for i in range(1, 5)]:
        sub = df_mvsq_est[df_mvsq_est["quarter"] == q]
        check_mq[q] = sum(r * h for r, h in zip(sub["ratio_norm"], sub["hours"])) / sub["hours"].sum()

    return {
        "df_qvsy":       df_qvsy,
        "df_mvsq":       df_mvsq,
        "qvsy_estimates": df_qvsy_est,
        "mvsq_estimates": df_mvsq_est,
        "year_target":   year_target,
        "n_valid_dates": len(valid_dates),
        "missing_q":     missing_quarters,
        "check_qy":      check_qy,
        "check_mq":      check_mq,
        "params": dict(year_target=year_target, date_from=date_from, date_to=date_to,
                       estimator_qy=estimator_qy, cut_qy=cut_qy,
                       estimator_mq=estimator_mq, cut_mq=cut_mq),
    }, None


def _save_calibration(result):
    """Append calibration result to fc_coefficients.parquet."""
    calib_id = str(uuid.uuid4())
    calib_ts = pd.Timestamp.now()
    p = result["params"]
    qvsy = result["qvsy_estimates"]
    mvsq = result["mvsq_estimates"]

    rows = []
    for _, row in qvsy.iterrows():
        rows.append({
            "calib_id": calib_id, "calib_ts": calib_ts,
            "year_target": p["year_target"],
            "date_from": p["date_from"], "date_to": p["date_to"],
            "estimator_qy": p["estimator_qy"], "cut_qy": p["cut_qy"],
            "estimator_mq": p["estimator_mq"], "cut_mq": p["cut_mq"],
            "level": "Q", "period": row["quarter"],
            "ratio_raw": row["ratio_raw"], "ratio_norm": row["ratio_norm"],
            "n_obs": row["n_obs"],
        })
    for _, row in mvsq.iterrows():
        rows.append({
            "calib_id": calib_id, "calib_ts": calib_ts,
            "year_target": p["year_target"],
            "date_from": p["date_from"], "date_to": p["date_to"],
            "estimator_qy": p["estimator_qy"], "cut_qy": p["cut_qy"],
            "estimator_mq": p["estimator_mq"], "cut_mq": p["cut_mq"],
            "level": "M", "period": row["month"],
            "ratio_raw": row["ratio_raw"], "ratio_norm": row["ratio_norm"],
            "n_obs": row["n_obs"],
        })

    df_new = pd.DataFrame(rows)
    os.makedirs(FC_DIR, exist_ok=True)
    if os.path.exists(FC_COEFF_PATH):
        df_old = pd.read_parquet(FC_COEFF_PATH)
        df_out = pd.concat([df_old, df_new], ignore_index=True)
    else:
        df_out = df_new
    df_out.to_parquet(FC_COEFF_PATH, index=False)
    return calib_id


def _preview_curve(result, otf, cal, year_preview):
    """Build a quick forward curve for preview (no save). Returns df with month_price."""
    qvsy = result["qvsy_estimates"].set_index("quarter")["ratio_norm"].to_dict()
    mvsq = result["mvsq_estimates"].set_index(["quarter", "month"])["ratio_norm"].to_dict()
    yr2 = str(year_preview)[-2:]
    hmap = hours_per_period(cal, year_preview)

    quotes = load_quotes(OTF_EE_PATH, dt.date.today(), max_age_days=30)
    y_row = quotes[quotes["product_name"] == f"BASE_Y-{yr2}"]
    if y_row.empty:
        return None
    y_price = float(y_row["price"].iloc[0])

    # Re-normalize for year_preview
    q_keys = [f"Q{i}" for i in range(1, 5)]
    q_raw = [qvsy.get(f"Q{i}", 1.0) for i in range(1, 5)]
    q_h = [hmap.get(f"Q-{i}-{yr2}", 0) for i in range(1, 5)]
    q_norm = normalize_ratios(q_raw, q_h) if sum(q_h) > 0 else q_raw
    q_norm_r = dict(zip(q_keys, q_norm))
    H_Y = hmap.get(f"Y-{yr2}", 8760)

    # Pure coeff curve (no reconciliation for preview — just coefficients × Y)
    rows = []
    for qi in range(1, 5):
        q = f"Q{qi}"
        q_price = y_price * q_norm_r[q]
        for mn in _QUARTER_MONTHS[q]:
            mk = f"M{mn}"
            m_raw = [mvsq.get((q, f"M{m}"), 1.0) for m in _QUARTER_MONTHS[q]]
            m_h = [hmap.get(f"M-{m:02d}-{yr2}", 0) for m in _QUARTER_MONTHS[q]]
            m_norm = normalize_ratios(m_raw, m_h) if sum(m_h) > 0 else m_raw
            m_norm_r = dict(zip([f"M{m}" for m in _QUARTER_MONTHS[q]], m_norm))
            h_m = hmap.get(f"M-{mn:02d}-{yr2}", 0)
            m_price = q_price * m_norm_r[mk]
            rows.append({"quarter": q, "month_num": mn,
                         "date": dt.date(year_preview, mn, 1),
                         "hours": h_m, "month_price": m_price, "y_price": y_price})
    return pd.DataFrame(rows) if rows else None


def _load_otf():
    return pd.read_parquet(OTF_EE_PATH)


def _load_cal():
    return load_calendar(FC_DIR)


# ── Page 1: FC Kalibracja ─────────────────────────────────────────────────────

_CALIB_CHEATSHEET = """
**K1 — Zakres historii notowań (data od / data do)**
Filtr dat OTF wchodzących do estymacji. Rekomendacja: **2023-01-01 → dziś** — wyklucza zniekształcenia
z kryzysu gazowego 2021-2022, zachowuje "nową normalność" z wyższą penetracją OZE.
Winsorized/trimmed mean radzi sobie z outlierami, ale mniejsza ich liczba = czystszy sygnał.

**K2 — Rok bazowy estymacji**
Rok, z którego pochodzą jednoczesne notowania Q+Y (i M+Q) do wyliczenia rozkładów sezonowych.
Wybierz **ostatni pełny rok z kompletem 4 kwartałów + rok** (domyślnie auto-wykrywany).
Współczynniki z K2 są transferowane na wszystkie lata docelowe z re-normalizacją godzinową.

**K3 — Estymator Q/Y** | K4 — parametr odcięcia (domyślnie 0.10)
Zalecany: **winsorized_mean** — przy setkach obserwacji łagodnie przycina 10% skrajności z każdej strony,
zachowuje więcej informacji niż median. Mean — tylko jeśli dane są czyste (bez kryzysów w oknie K1).

**K5 — Estymator M/Q** | K6 — parametr odcięcia (domyślnie 0.15)
Zalecany: **trimmed_mean** — produkty miesięczne mają mniej obserwacji (kwotowane kilka tygodni),
więc twardsze odcięcie (15%) jest bezpieczniejsze niż winsorized. Wyższy K6 kompensuje węższą próbę.

---
*Kalibracja jest jednorazowa — zapisane współczynniki działają do czasu ręcznej aktualizacji.
Cron generuje krzywą codziennie z aktywnym zestawem (Procedura 2), nigdy nie kalibruje automatycznie.*
"""


def render_calibration():
    st.header("FC Kalibracja — współczynniki sezonowe")

    with st.expander("Ściąga: opis parametrów K1–K6", expanded=False):
        st.markdown(_CALIB_CHEATSHEET)

    # Load data
    try:
        otf = _load_otf()
        cal = _load_cal()
    except Exception as e:
        st.error(f"Błąd ładowania danych: {e}")
        return

    otf["date"] = pd.to_datetime(otf["date"]).dt.date
    k2_default = _auto_k2(otf)

    # ── Parametry K1–K6 ───────────────────────────────────────────────────────
    with st.expander("Parametry kalibracji K1–K6", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            k1_from = st.date_input("K1 Data od", value=dt.date(2020, 1, 1), key="fc_k1_from")
            k1_to   = st.date_input("K1 Data do", value=dt.date.today(), key="fc_k1_to")
            k2_year = st.number_input("K2 Rok bazowy", min_value=2020, max_value=2030,
                                      value=k2_default or 2025, key="fc_k2")
        with c2:
            k3 = st.selectbox("K3 Estymator Q/Y", ["winsorized_mean", "trimmed_mean", "median", "mean"],
                              index=0, key="fc_k3")
            k4 = st.number_input("K4 Odcięcie Q/Y", min_value=0.0, max_value=0.49, value=0.10,
                                 step=0.01, format="%.2f", key="fc_k4")
            k5 = st.selectbox("K5 Estymator M/Q", ["trimmed_mean", "winsorized_mean", "median", "mean"],
                              index=0, key="fc_k5")
            k6 = st.number_input("K6 Odcięcie M/Q", min_value=0.0, max_value=0.49, value=0.15,
                                 step=0.01, format="%.2f", key="fc_k6")

    if st.button("Kalibruj", type="primary", key="fc_calibrate_btn"):
        with st.spinner("Kalibracja..."):
            result, err = _run_calibration(
                otf, cal, int(k2_year),
                k1_from, k1_to, k3, k4, k5, k6
            )
        if err:
            st.error(err)
            st.session_state.pop("fc_calib_result", None)
        else:
            st.session_state["fc_calib_result"] = result
            st.success(f"Kalibracja OK — {result['n_valid_dates']} dat z kompletem Q+Y")

    result = st.session_state.get("fc_calib_result")
    if result is None:
        # History table
        _render_calib_history()
        return

    # ── Diagnostyka ───────────────────────────────────────────────────────────
    if result["missing_q"]:
        st.warning(f"Brakujące kwartały w M/Q: {', '.join(result['missing_q'])} (brak notowań M+Q jednocześnie)")

    st.subheader("Diagnostyka rozkładów Q/Y")
    df_qvsy = result["df_qvsy"]
    fig_qy = go.Figure()
    for qi in range(1, 5):
        q = f"Q{qi}"
        vals = df_qvsy[df_qvsy["quarter"] == q]["QvsY_pct"]
        fig_qy.add_trace(go.Box(y=vals, name=q, boxmean=True))
    fig_qy.add_hline(y=1.0, line_dash="dash", line_color="red", annotation_text="Y = 1.0")
    fig_qy.update_layout(title="Stosunek Q/Y per kwartał", yaxis_title="Q/Y", height=350,
                         plot_bgcolor="white", paper_bgcolor="white")
    st.plotly_chart(fig_qy, use_container_width=True)

    st.subheader("Diagnostyka rozkładów M/Q")
    df_mvsq = result["df_mvsq"]
    if not df_mvsq.empty:
        avail_q = sorted(df_mvsq["quarter"].unique())
        ncols = min(2, len(avail_q))
        nrows = (len(avail_q) + ncols - 1) // ncols
        fig_mq = make_subplots(rows=nrows, cols=ncols,
                               subplot_titles=[f"{q} ({['M1-M3','M4-M6','M7-M9','M10-M12'][int(q[1])-1]})" for q in avail_q])
        for idx, q in enumerate(avail_q):
            r, c = idx // ncols + 1, idx % ncols + 1
            for mn in _QUARTER_MONTHS[q]:
                mk = f"M{mn}"
                vals = df_mvsq[(df_mvsq["quarter"] == q) & (df_mvsq["month"] == mk)]["MvsQ_pct"]
                fig_mq.add_trace(go.Box(y=vals, name=mk, boxmean=True), row=r, col=c)
        fig_mq.add_hline(y=1.0, line_dash="dash", line_color="red")
        fig_mq.update_layout(height=380 * nrows, showlegend=False,
                             plot_bgcolor="white", paper_bgcolor="white")
        st.plotly_chart(fig_mq, use_container_width=True)
    else:
        st.info("Brak danych M/Q (brak dat z kompletem 3M + Q)")

    # ── Tabele współczynników ─────────────────────────────────────────────────
    st.subheader("Współczynniki Q/Y")
    qvsy_est = result["qvsy_estimates"]

    def _style_nobs(val, thresh_warn=10, thresh_err=0):
        if val == thresh_err:
            return "background-color: #ffcccc"
        if val < thresh_warn:
            return "background-color: #fff3cd"
        return ""

    q_disp = qvsy_est[["quarter", "ratio_raw", "ratio_norm", "n_obs", "hours"]].copy()
    q_disp.columns = ["Kwartał", "Surowy", "Znorm.", "N obs", "Godziny"]
    st.dataframe(q_disp.style.format({"Surowy": "{:.4f}", "Znorm.": "{:.4f}"}), use_container_width=True)

    check_qy = result["check_qy"]
    if abs(check_qy - 1.0) < 1e-6:
        st.success(f"Sprawdzenie Q/Y: średnia ważona = {check_qy:.6f} ✓")
    else:
        st.error(f"Sprawdzenie Q/Y: średnia ważona = {check_qy:.6f} ✗ (oczekiwano 1.0)")

    st.subheader("Współczynniki M/Q")
    mvsq_est = result["mvsq_estimates"]
    m_disp = mvsq_est[["quarter", "month", "ratio_raw", "ratio_norm", "n_obs", "hours"]].copy()
    m_disp.columns = ["Kwartał", "Miesiąc", "Surowy", "Znorm.", "N obs", "Godziny"]

    def _row_style(row):
        if row["N obs"] == 0:
            return ["background-color: #ffcccc"] * len(row)
        if row["N obs"] < 10:
            return ["background-color: #fff3cd"] * len(row)
        return [""] * len(row)

    st.dataframe(
        m_disp.style.apply(_row_style, axis=1).format({"Surowy": "{:.4f}", "Znorm.": "{:.4f}"}),
        use_container_width=True
    )

    check_mq = result["check_mq"]
    all_mq_ok = all(abs(v - 1.0) < 1e-6 for v in check_mq.values())
    if all_mq_ok:
        st.success(f"Sprawdzenie M/Q: wszystkie kwartały ✓ (średnie ważone = 1.0)")
    else:
        for q, v in check_mq.items():
            if abs(v - 1.0) >= 1e-6:
                st.error(f"Sprawdzenie M/Q {q}: {v:.6f} ✗")
            else:
                st.success(f"Sprawdzenie M/Q {q}: {v:.6f} ✓")

    # ── Podgląd krzywej ───────────────────────────────────────────────────────
    st.subheader("Podgląd krzywej (ad-hoc, bez zapisu)")
    today_year = dt.date.today().year
    avail_y_years = []
    otf_y = otf[otf["product_name"].str.match(r"^BASE_Y-\d{2}$")]
    for _, rw in otf_y.iterrows():
        yr = int(str(rw["product_name"])[-2:]) + 2000
        if yr >= today_year:
            avail_y_years.append(yr)
    avail_y_years = sorted(set(avail_y_years))

    preview_year = st.selectbox("Rok podglądu", avail_y_years,
                                index=0 if avail_y_years else 0, key="fc_preview_year")
    if avail_y_years:
        df_prev = _preview_curve(result, otf, cal, int(preview_year))
        if df_prev is not None:
            y_p = df_prev["y_price"].iloc[0]
            fig_prev = go.Figure()
            colors = {"Q1": "#4C72B0", "Q2": "#55A868", "Q3": "#C44E52", "Q4": "#8172B2"}
            for q in [f"Q{i}" for i in range(1, 5)]:
                sub = df_prev[df_prev["quarter"] == q]
                fig_prev.add_trace(go.Bar(
                    x=sub["date"].astype(str), y=sub["month_price"],
                    name=q, marker_color=colors[q]
                ))
            fig_prev.add_hline(y=y_p, line_dash="dash", line_color="red",
                               annotation_text=f"Y-{str(preview_year)[-2:]} = {y_p:.2f}")
            fig_prev.update_layout(barmode="stack", height=380,
                                   yaxis_title="PLN/MWh", xaxis_title="Miesiąc",
                                   title=f"Krzywa forward {preview_year} (współczynnikowa)",
                                   plot_bgcolor="white", paper_bgcolor="white")
            st.plotly_chart(fig_prev, use_container_width=True)
        else:
            st.info(f"Brak ważnego notowania BASE_Y-{str(preview_year)[-2:]} dla podglądu")

    # ── Zapisz ────────────────────────────────────────────────────────────────
    st.divider()
    c1, c2 = st.columns([1, 3])
    with c1:
        if st.button("Zapisz jako aktywne", type="primary", key="fc_save_btn"):
            calib_id = _save_calibration(result)
            st.success(f"Zapisano kalibrację: {calib_id[:8]}…")
            st.session_state.pop("fc_calib_result", None)
            st.rerun()

    _render_calib_history()


def _render_calib_history():
    if not os.path.exists(FC_COEFF_PATH):
        return
    df = pd.read_parquet(FC_COEFF_PATH)
    if df.empty:
        return
    summary = (df.groupby(["calib_id", "calib_ts", "year_target", "estimator_qy", "estimator_mq"])
               .first().reset_index()[["calib_id", "calib_ts", "year_target", "estimator_qy", "estimator_mq"]])
    latest_ts = summary["calib_ts"].max()
    summary["Aktywny"] = summary["calib_ts"] == latest_ts
    summary["calib_id_short"] = summary["calib_id"].str[:8] + "…"
    summary["calib_ts"] = summary["calib_ts"].dt.strftime("%Y-%m-%d %H:%M")
    disp = summary[["calib_ts", "calib_id_short", "year_target", "estimator_qy", "estimator_mq", "Aktywny"]]
    disp.columns = ["Timestamp", "ID (skrót)", "Rok bazowy", "Est. Q/Y", "Est. M/Q", "Aktywny"]
    st.subheader("Historia kalibracji")
    st.dataframe(disp, use_container_width=True)


# ── Page 2: FC Raport ─────────────────────────────────────────────────────────

def render_report():
    st.header("FC Raport — krzywa forward")

    os.makedirs(FC_DIR, exist_ok=True)

    if not os.path.exists(FC_COEFF_PATH):
        st.warning("Brak kalibracji. Uruchom stronę FC Kalibracja i zapisz aktywne współczynniki.")
        return

    # ── Generuj FC ────────────────────────────────────────────────────────────
    with st.expander("Parametry generowania G1–G4"):
        c1, c2 = st.columns(2)
        with c1:
            g1 = st.date_input("G1 As-of date", value=dt.date.today(), key="fc_g1")
            g2 = st.number_input("G2 Maks. wiek notowania (dni)", min_value=1, max_value=30,
                                 value=7, key="fc_g2")
        with c2:
            all_coeff = pd.read_parquet(FC_COEFF_PATH) if os.path.exists(FC_COEFF_PATH) else pd.DataFrame()
            calib_options = []
            if not all_coeff.empty:
                for _, row in all_coeff.drop_duplicates("calib_id").iterrows():
                    ts = pd.to_datetime(row["calib_ts"]).strftime("%Y-%m-%d %H:%M")
                    calib_options.append(f"{ts} | {row['calib_id'][:8]}… (K2={row['year_target']})")
            g4_sel = st.selectbox("G4 Zestaw współczynników", ["Najnowszy (domyślnie)"] + calib_options, key="fc_g4")
            g4_id = None if g4_sel == "Najnowszy (domyślnie)" else g4_sel.split("|")[1].strip().split("…")[0].strip()

    if st.button("Generuj FC", type="primary", key="fc_generate_btn"):
        import sys as _sys
        _sys.path.insert(0, os.path.join(APP_DIR, "procedures"))
        from fc_pipeline import run_pipeline
        log_lines = []
        curve_id = run_pipeline(
            APP_DIR, asof_date=g1, calib_id=g4_id,
            trigger="manual", log=log_lines.append, max_age_days=int(g2)
        )
        if curve_id:
            st.success(f"FC wygenerowana: curve_id = {curve_id[:8]}…")
            for line in log_lines:
                st.caption(line)
        else:
            st.error("Generowanie nieudane — sprawdź parametry lub dane wejściowe.")
            for line in log_lines:
                st.caption(line)

    # ── Selector przebiegu ────────────────────────────────────────────────────
    if not os.path.exists(FC_CURVES_PATH):
        st.info("Brak wyników FC. Wygeneruj FC używając przycisku powyżej.")
        return

    df_all = pd.read_parquet(FC_CURVES_PATH)
    if df_all.empty:
        st.info("Brak wyników FC.")
        return

    runs = (df_all.drop_duplicates("curve_id")
            [["curve_id", "run_ts", "asof_date", "calib_id", "trigger"]]
            .sort_values("run_ts", ascending=False))
    run_labels = []
    for _, row in runs.iterrows():
        ts = pd.to_datetime(row["run_ts"]).strftime("%Y-%m-%d %H:%M")
        asof = str(row["asof_date"])
        run_labels.append(f"{ts} | asof {asof} | {row['trigger']} | {str(row['curve_id'])[:8]}…")

    sel_run_label = st.selectbox("Przebieg FC", run_labels, index=0, key="fc_run_sel")
    sel_idx = run_labels.index(sel_run_label)
    sel_curve_id = runs.iloc[sel_idx]["curve_id"]
    df_run = df_all[df_all["curve_id"] == sel_curve_id].copy()

    # Header info
    run_meta = runs.iloc[sel_idx]
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("As-of date", str(run_meta["asof_date"]))
    col2.metric("Run ts", pd.to_datetime(run_meta["run_ts"]).strftime("%Y-%m-%d %H:%M"))
    col3.metric("Trigger", run_meta["trigger"])
    col4.metric("Calib ID", str(run_meta["calib_id"])[:8] + "…")

    # Warnings
    warns = df_run[df_run["warning"].notna()]["warning"].unique()
    for w in warns:
        st.warning(w)

    # ── Selektory raportu ─────────────────────────────────────────────────────
    avail_years = sorted(df_run["year"].unique())
    c1, c2 = st.columns([1, 1])
    with c1:
        sel_year = st.selectbox("Rok", avail_years, index=0, key="fc_rep_year")
    with c2:
        gran = st.radio("Granulacja", ["Q", "M"], index=0, horizontal=True, key="fc_gran")

    df_year = df_run[df_run["year"] == sel_year].sort_values("month_num")
    y_price = df_year["y_price"].iloc[0]

    # ── Tabela cen ────────────────────────────────────────────────────────────
    st.subheader(f"Ceny {sel_year}" + (" — kwartalna" if gran == "Q" else " — miesięczna"))
    _SRC_BADGE = {"market": "🟢 market", "residual": "🔵 model", "fallback": "🔴 fallback"}

    if gran == "Q":
        q_rows = []
        for q in [f"Q{i}" for i in range(1, 5)]:
            sub = df_year[df_year["quarter"] == q]
            q_price = (sub["month_price"] * sub["hours"]).sum() / sub["hours"].sum()
            h_total = sub["hours"].sum()
            src = "market" if all(s == "market" for s in sub["source"]) else (
                "fallback" if any(s == "fallback" for s in sub["source"]) else "residual"
            )
            q_rows.append({"Kwartał": q, "Godziny": int(h_total),
                           "Cena (PLN/MWh)": round(q_price, 2), "Źródło": _SRC_BADGE.get(src, src)})
        q_rows.append({"Kwartał": "— ROK —", "Godziny": int(df_year["hours"].sum()),
                       "Cena (PLN/MWh)": round(y_price, 2), "Źródło": "—"})
        st.dataframe(pd.DataFrame(q_rows), use_container_width=True, hide_index=True)
    else:
        m_rows = []
        for _, row in df_year.iterrows():
            m_rows.append({"Miesiąc": f"M{row['month_num']:02d}", "Kwartał": row["quarter"],
                           "Godziny": int(row["hours"]), "MvsY": round(row["MvsY"], 4),
                           "Cena (PLN/MWh)": round(row["month_price"], 2),
                           "Źródło": _SRC_BADGE.get(row["source"], row["source"])})
        m_rows.append({"Miesiąc": "— ROK —", "Kwartał": "—", "Godziny": int(df_year["hours"].sum()),
                       "MvsY": 1.0, "Cena (PLN/MWh)": round(y_price, 2), "Źródło": "—"})
        st.dataframe(pd.DataFrame(m_rows), use_container_width=True, hide_index=True)

    # ── Wykres ────────────────────────────────────────────────────────────────
    st.subheader("Wykres krzywej")
    _COLORS = {"Q1": "#4C72B0", "Q2": "#55A868", "Q3": "#C44E52", "Q4": "#8172B2"}
    fig = go.Figure()
    for q in [f"Q{i}" for i in range(1, 5)]:
        sub = df_year[df_year["quarter"] == q]
        has_market = any(sub["source"] == "market")
        fig.add_trace(go.Bar(
            x=sub["date"].astype(str), y=sub["month_price"],
            name=q, marker_color=_COLORS[q],
            marker_line_color="black" if has_market else _COLORS[q],
            marker_line_width=2 if has_market else 0,
        ))
    fig.add_hline(y=y_price, line_dash="dash", line_color="red",
                  annotation_text=f"Y-{str(sel_year)[-2:]} = {y_price:.2f}")
    fig.update_layout(barmode="stack", height=420, yaxis_title="PLN/MWh",
                      title=f"Krzywa forward {sel_year}  (obramowanie = notowanie rynkowe)",
                      plot_bgcolor="white", paper_bgcolor="white")
    st.plotly_chart(fig, use_container_width=True)

    # ── Kalkulator wyceny kontraktu ───────────────────────────────────────────
    st.divider()
    st.subheader("Kalkulator wyceny kontraktu")
    df_fc_all_years = df_run.copy()
    min_fc_date = dt.date(df_fc_all_years["year"].min(), 1, 1)
    max_fc_date = dt.date(df_fc_all_years["year"].max(), 12, 1)

    c1, c2 = st.columns(2)
    with c1:
        kal_from = st.text_input("Od (RRRR-MM)", value=f"{sel_year}-01", key="fc_kal_from")
    with c2:
        kal_to = st.text_input("Do (RRRR-MM)", value=f"{sel_year}-12", key="fc_kal_to")

    contract_result = None
    if st.button("Wycen kontrakt", key="fc_kal_btn"):
        try:
            def _parse_ym(s):
                parts = s.strip().split("-")
                return dt.date(int(parts[0]), int(parts[1]), 1)
            d_from = _parse_ym(kal_from)
            d_to = _parse_ym(kal_to)
            mask = (df_fc_all_years["date"] >= d_from) & (df_fc_all_years["date"] <= d_to)
            df_contract = df_fc_all_years[mask].copy()
            if df_contract.empty:
                st.error("Brak danych FC dla podanego zakresu. Sprawdź czy lata są w docelowych.")
            else:
                total_val = (df_contract["month_price"] * df_contract["hours"]).sum()
                total_h = df_contract["hours"].sum()
                contract_price = total_val / total_h
                contract_result = {"price": contract_price, "hours": total_h,
                                   "months": len(df_contract), "df": df_contract}
                st.metric("Cena kontraktu", f"{contract_price:.2f} PLN/MWh")
                st.caption(f"{len(df_contract)} miesięcy | {int(total_h)} godzin")
        except Exception as e:
            st.error(f"Błąd: {e}")

    if contract_result:
        df_c = contract_result["df"]
        nearest_y = df_fc_all_years[df_fc_all_years["year"] == avail_years[0]]["y_price"].iloc[0]
        fig_kal = go.Figure()
        # Szare tło — wszystkie miesiące
        fig_kal.add_trace(go.Bar(x=df_fc_all_years["date"].astype(str),
                                 y=df_fc_all_years["month_price"],
                                 name="Wszystkie miesiące", marker_color="lightgray"))
        # Niebieskie — kontrakt
        fig_kal.add_trace(go.Bar(x=df_c["date"].astype(str), y=df_c["month_price"],
                                 name="Kontrakt", marker_color="steelblue"))
        fig_kal.add_hline(y=contract_result["price"], line_color="green",
                          annotation_text=f"Cena kontraktu: {contract_result['price']:.2f}")
        fig_kal.add_hline(y=nearest_y, line_dash="dash", line_color="red",
                          annotation_text=f"Y = {nearest_y:.2f}")
        fig_kal.update_layout(barmode="overlay", height=400, yaxis_title="PLN/MWh",
                              plot_bgcolor="white", paper_bgcolor="white")
        st.plotly_chart(fig_kal, use_container_width=True)

    # ── Eksport XLSX ──────────────────────────────────────────────────────────
    st.divider()
    if st.button("Eksport do Excel (.xlsx)", key="fc_export_btn"):
        buf = BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            # Arkusz 1: Raport
            if gran == "Q":
                rep_rows = []
                for q in [f"Q{i}" for i in range(1, 5)]:
                    sub = df_year[df_year["quarter"] == q]
                    q_price = (sub["month_price"] * sub["hours"]).sum() / sub["hours"].sum()
                    rep_rows.append({"Kwartał": q, "Godziny": int(sub["hours"].sum()),
                                     "Cena (PLN/MWh)": round(q_price, 2)})
                pd.DataFrame(rep_rows).to_excel(writer, sheet_name="Raport", index=False)
            else:
                df_year[["month_num", "quarter", "hours", "MvsY", "month_price", "source"]].to_excel(
                    writer, sheet_name="Raport", index=False)

            # Arkusz 2: FC pełna
            fc_full = df_run[["month_num", "quarter", "MvsY", "month_price", "year", "hours", "date", "source", "y_price"]].copy()
            fc_full.to_excel(writer, sheet_name="FC pełna", index=False)

            # Arkusz 3: Kontrakt (jeśli policzony)
            if contract_result:
                dc = contract_result["df"][["date", "year", "month_num", "quarter", "hours", "month_price"]].copy()
                dc.loc[len(dc)] = ["RAZEM", "", "", "", contract_result["hours"], contract_result["price"]]
                dc.to_excel(writer, sheet_name="Kontrakt", index=False)

            # Arkusz 4: Meta
            meta_rows = [
                ["asof_date", str(run_meta["asof_date"])],
                ["run_ts", str(run_meta["run_ts"])],
                ["calib_id", str(run_meta["calib_id"])],
                ["trigger", run_meta["trigger"]],
            ]
            if not all_coeff.empty:
                c_row = all_coeff[all_coeff["calib_id"] == run_meta["calib_id"]]
                if not c_row.empty:
                    r = c_row.iloc[0]
                    meta_rows += [
                        ["year_target", r["year_target"]],
                        ["estimator_qy", r["estimator_qy"]], ["cut_qy", r["cut_qy"]],
                        ["estimator_mq", r["estimator_mq"]], ["cut_mq", r["cut_mq"]],
                        ["date_from", str(r["date_from"])], ["date_to", str(r["date_to"])],
                    ]
            for w in warns:
                meta_rows.append(["warning", w])
            pd.DataFrame(meta_rows, columns=["Parametr", "Wartość"]).to_excel(
                writer, sheet_name="Meta", index=False)

        buf.seek(0)
        asof_str = str(run_meta["asof_date"]).replace("-", "")
        st.download_button("Pobierz XLSX", data=buf,
                           file_name=f"FC_{sel_year}_{asof_str}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           key="fc_xlsx_dl")
