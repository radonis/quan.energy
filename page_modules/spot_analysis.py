# page_modules/spot_analysis.py
# SPOT Daily and SPOTS History pages

import streamlit as st
import pandas as pd
import io, os, importlib.util, calendar as _cal
from datetime import date, timedelta
from shared import APP_DIR, load_prices, load_prices_qh, is_workday

# ── Product definitions ───────────────────────────────────────────────────────
# PEAK/LowPEAK/HighPEAK apply only on working days (Mon-Fri, excl. PL public
# holidays). OFFPEAK is the complement of "peak hours on a working day" — so
# it absorbs ALL hours of weekends/holidays, not just H23-H07. HolidaysX is a
# separate, narrower view restricted to weekends + public holidays only.
# PeakAll ignores day type entirely (the simple hour-range-only definition).
_BASE_H     = list(range(1, 25))
_PEAK_H     = list(range(8, 23))
_LOWPEAK_H  = list(range(8, 18))
_HIGHPEAK_H = list(range(18, 23))
_OFFPEAK_H  = list(range(1, 8)) + [23, 24]

_PRODUCTS = ["BASE", "PEAK", "LowPEAK", "HighPEAK", "OFFPEAK",
             "HolidaysBase", "HolidaysPeak", "HolidaysOffPeak", "PeakAll"]
_SELECTABLE_PRODUCTS = [p for p in _PRODUCTS if p != "BASE"]

_PROD_LABEL = {
    "BASE":            "H01–H24",
    "PEAK":            "H08–H22",
    "LowPEAK":         "H08–H17",
    "HighPEAK":        "H18–H22",
    "OFFPEAK":         "H23–H07*",
    "HolidaysBase":    "H01–H24",
    "HolidaysPeak":    "H08–H22",
    "HolidaysOffPeak": "H23–H07",
    "PeakAll":         "H08–H22",
}
_PROD_SCOPE = {
    "BASE":            "all days",
    "PEAK":            "only on working days",
    "LowPEAK":         "only on working days",
    "HighPEAK":        "only on working days",
    "OFFPEAK":         "all, except peak hours on working days*",
    "HolidaysBase":    "weekends & public holidays",
    "HolidaysPeak":    "weekends & public holidays",
    "HolidaysOffPeak": "weekends & public holidays",
    "PeakAll":         "all days (ignores day type)",
}


def _hours_for_product(product: str, workday: bool) -> list:
    """Hour-of-day list applicable for `product`, given whether the day is a
    working day or a weekend/public holiday. Returns [] if the product
    doesn't apply to that day type at all."""
    if product == "BASE":
        return _BASE_H
    if product == "PeakAll":
        return _PEAK_H
    if product == "PEAK":
        return _PEAK_H if workday else []
    if product == "LowPEAK":
        return _LOWPEAK_H if workday else []
    if product == "HighPEAK":
        return _HIGHPEAK_H if workday else []
    if product == "OFFPEAK":
        return _OFFPEAK_H if workday else _BASE_H
    if product == "HolidaysBase":
        return [] if workday else _BASE_H
    if product == "HolidaysPeak":
        return [] if workday else _PEAK_H
    if product == "HolidaysOffPeak":
        return [] if workday else _OFFPEAK_H
    return []

_BTN_STYLE = """
<style>
button[kind="secondary"][data-testid="baseButton-secondary"] { display:none; }
div[data-testid="stButton"] button[data-testid="update-fix1"],
div[data-testid="stButton"] button[data-testid="update-fix2"] {
    background-color: #c0392b !important;
    color: white !important;
    border: none !important;
}
</style>
"""

# ── Helpers ───────────────────────────────────────────────────────────────────

def _prod_avg(prices_by_h: dict, hours: list) -> float:
    vals = [v for h in hours if pd.notna(v := prices_by_h.get(h, float("nan")))]
    return sum(vals) / len(vals) if vals else float("nan")


def _run_pipeline(fixing_date: date, log):
    path = os.path.join(APP_DIR, "procedures", "tge_fixing.py")
    spec = importlib.util.spec_from_file_location("tge_fixing", path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.run_pipeline(
        app_dir=APP_DIR,
        start_date=fixing_date,
        end_date=fixing_date,
        log=log,
    )


def _df_height(n_rows: int, row_px: int = 35, header_px: int = 38) -> int:
    return n_rows * row_px + header_px


def _product_legend():
    st.divider()
    st.caption("**Product definitions**")
    leg = pd.DataFrame([
        {"Product": p, "Hours": _PROD_LABEL[p], "Applies to": _PROD_SCOPE[p]}
        for p in _PRODUCTS
    ])
    st.dataframe(leg, hide_index=True, use_container_width=False,
                 height=_df_height(len(leg)))
    st.caption(
        "*OFFPEAK = all hours not in PEAK on a working day — so it includes "
        "every hour of weekends/public holidays, not just H23–H07."
    )


# ── Red button CSS ────────────────────────────────────────────────────────────
_RED_BTN_CSS = """
<style>
div[data-testid="stButton"] > button[kind="primary"] {
    background-color: #c0392b !important;
    color: white !important;
    border: none !important;
}
</style>
"""


# ── Page 1: SPOT Daily ───────────────────────────────────────────────────────

def render_spot_daily():
    prices_h  = load_prices()
    prices_qh = load_prices_qh()

    st.title("SPOT Daily")

    # ── Controls row ─────────────────────────────────────────────────────────
    cc1, cc2, cc3, cc4, cc5, _ = st.columns([0.5, 0.28, 1.1, 0.28, 0.9, 2.5])

    fixing   = cc1.selectbox("Fixing", ["F1", "F2"], key="sd_fixing")

    # Date navigation
    if "sd_date" not in st.session_state:
        st.session_state["sd_date"] = date.today()

    cc2.markdown("<div style='margin-top:26px'>", unsafe_allow_html=True)
    if cc2.button("◀", key="sd_prev"):
        st.session_state["sd_date"] -= timedelta(days=1)
        st.rerun()
    cc2.markdown("</div>", unsafe_allow_html=True)

    sel_date = cc3.date_input("Delivery date", value=st.session_state["sd_date"],
                               key="sd_date_input")
    st.session_state["sd_date"] = sel_date

    cc4.markdown("<div style='margin-top:26px'>", unsafe_allow_html=True)
    if cc4.button("▶", key="sd_next"):
        st.session_state["sd_date"] += timedelta(days=1)
        st.rerun()
    cc4.markdown("</div>", unsafe_allow_html=True)

    price_col = "f1_price_PLN"  if fixing == "F1" else "sdac_price_PLN"
    vol_col   = "volume_mw"     if fixing == "F1" else "sdac_volume_mw"

    # ── Load data for selected date ───────────────────────────────────────────
    day_h  = prices_h[prices_h["delivery_date"] == sel_date].sort_values("H")
    day_qh = (prices_qh[prices_qh["delivery_date"] == sel_date].sort_values(["H", "Q"])
              if not prices_qh.empty else pd.DataFrame())

    has_h    = not day_h.empty and day_h[price_col].notna().any()
    has_qh_p = not day_qh.empty and price_col in day_qh.columns and day_qh[price_col].notna().any()
    has_qh_v = (not day_qh.empty and vol_col in day_qh.columns
                and day_qh[vol_col].notna().any())

    if not has_h and not has_qh_p:
        st.warning(
            f"No {fixing} data for {sel_date.strftime('%d.%m.%Y')}. "
            f"Use SPOT > Update to download missing data."
        )
        _product_legend()
        st.stop()

    # ── Build hourly base table ───────────────────────────────────────────────
    if has_qh_p:
        hourly = day_qh.groupby("H").agg(price=(price_col, "mean")).reset_index()
        if has_qh_v:
            vol_agg = day_qh.groupby("H").agg(volume=(vol_col, "sum")).reset_index()
            hourly  = hourly.merge(vol_agg, on="H", how="left")
        else:
            hourly["volume"] = float("nan")
    else:
        hourly = day_h[["H", price_col]].rename(columns={price_col: "price"}).copy()
        hourly["volume"] = float("nan")

    hourly = pd.DataFrame({"H": range(1, 25)}).merge(hourly, on="H", how="left")

    # ── QH toggle ────────────────────────────────────────────────────────────
    show_qh = False
    if has_qh_p:
        show_qh = st.checkbox("Show 15-min (QH) detail", value=False, key="sd_show_qh")

    # ── Build display dataframe ───────────────────────────────────────────────
    date_str = sel_date.strftime("%d.%m.%Y")
    pcol_hdr = f"Price {fixing} [PLN/MWh]"
    vcol_hdr = "Volume [MW]"

    if show_qh:
        rows = []
        for _, r in day_qh.iterrows():
            v = r[vol_col] if has_qh_v and vol_col in r.index else float("nan")
            rows.append({
                "Date": date_str,
                "Slot": f"H{int(r.H):02d}Q{int(r.Q)}",
                pcol_hdr: f"{r[price_col]:.2f}" if pd.notna(r.get(price_col)) else "—",
                vcol_hdr: f"{v:,.0f}" if pd.notna(v) else "—",
            })
        disp_df   = pd.DataFrame(rows)
        n_rows    = len(disp_df)
        total_vol = day_qh[vol_col].sum() if has_qh_v else None
    else:
        rows = []
        for _, r in hourly.iterrows():
            v = r.get("volume", float("nan"))
            rows.append({
                "Date": date_str,
                "Hour": f"H{int(r.H):02d}",
                pcol_hdr: f"{r['price']:.2f}" if pd.notna(r["price"]) else "—",
                vcol_hdr: f"{v:,.0f}" if pd.notna(v) else "—",
            })
        disp_df   = pd.DataFrame(rows)
        n_rows    = 24
        total_vol = hourly["volume"].sum(skipna=True) if has_qh_v else None

    # ── Hourly table + Product summary side by side ───────────────────────────
    prices_map = hourly.set_index("H")["price"].to_dict()
    valid_p    = [v for v in prices_map.values() if pd.notna(v)]
    _sd_is_wd  = is_workday(sel_date)

    if _sd_is_wd:
        st.caption(f"**{date_str}** is a **working day** — PEAK-family rows apply.")
    else:
        st.caption(
            f"**{date_str}** is a **weekend/public holiday** — PEAK/LowPEAK/HighPEAK "
            "show \"—\" (workdays only); see Holidays* rows."
        )

    _col_h, _col_s, _ = st.columns([2, 2, 4])

    with _col_h:
        st.dataframe(disp_df, use_container_width=False, hide_index=True,
                     height=_df_height(n_rows))
        if total_vol is not None and not pd.isna(total_vol):
            st.markdown(f"**Total volume: {total_vol:,.0f} MW**")

    with _col_s:
        met_rows = []
        for prod in _PRODUCTS:
            hours = _hours_for_product(prod, _sd_is_wd)
            avg = _prod_avg(prices_map, hours)
            met_rows.append({
                "Product":             prod,
                "Hours":               _PROD_LABEL[prod],
                f"{fixing} [PLN/MWh]": f"{avg:.2f}" if not pd.isna(avg) else "—",
            })
        if valid_p:
            p_min, p_max = min(valid_p), max(valid_p)
            met_rows += [
                {"Product": "Min",    "Hours": "—",         f"{fixing} [PLN/MWh]": f"{p_min:.2f}"},
                {"Product": "Max",    "Hours": "—",         f"{fixing} [PLN/MWh]": f"{p_max:.2f}"},
                {"Product": "Spread", "Hours": "Max − Min", f"{fixing} [PLN/MWh]": f"{p_max - p_min:.2f}"},
            ]
        met_df = pd.DataFrame(met_rows)
        st.dataframe(met_df, use_container_width=False, hide_index=True,
                     height=_df_height(len(met_df)))

    # ── Excel export — single sheet ───────────────────────────────────────────
    st.divider()
    _buf = io.BytesIO()
    try:
        with pd.ExcelWriter(_buf, engine="openpyxl") as xw:
            ws_name = "SPOT Data"
            # Price table
            disp_df.to_excel(xw, sheet_name=ws_name, index=False, startrow=0)
            # Gap + metrics below
            gap_row = len(disp_df) + 2
            met_df.to_excel(xw, sheet_name=ws_name, index=False, startrow=gap_row)

        _buf.seek(0)
        _view  = "QH" if show_qh else "H"
        _fname = f"SPOT_{fixing}_{sel_date.strftime('%Y%m%d')}_{_view}.xlsx"
        st.download_button(
            label=f"Download {_fname}",
            data=_buf.getvalue(),
            file_name=_fname,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="sd_dl",
        )
    except ImportError:
        st.warning("openpyxl not installed — export unavailable.")

    _product_legend()

    st.divider()
    st.markdown(
        "<div style='font-size:0.85rem;color:#666;line-height:1.8'>"
        "<b>Source:</b> TGE — F1 (Day-Ahead Fixing 1) and SDAC (Single Day-Ahead Coupling)<br>"
        "<b>Auto-update:</b> daily at ~06:00 CET via cron (<code>morning</code> job &rarr; <code>tge_fixing.py</code>)<br>"
        "<b>Manual update:</b> SPOT &rsaquo; Update page"
        "</div>",
        unsafe_allow_html=True,
    )


# ── Page 2: SPOTS History ─────────────────────────────────────────────────────

def render_spots_history():
    prices_h = load_prices()

    st.title("SPOTS History")

    # Controls
    hc1, hc2, hc3, _ = st.columns([0.45, 0.65, 0.75, 4.15])
    fixing  = hc1.selectbox("Fixing",  ["F1", "F2"], key="sh_fixing")
    period  = hc2.selectbox("Period",  ["Month", "Quarter", "Year"], key="sh_period")
    product = hc3.selectbox("Product", _SELECTABLE_PRODUCTS, key="sh_product")

    price_col = "f1_price_PLN" if fixing == "F1" else "sdac_price_PLN"

    df = prices_h[prices_h[price_col].notna()].copy()
    if df.empty:
        st.warning(f"No {fixing} data available.")
        _product_legend()
        st.stop()

    df["delivery_date"] = pd.to_datetime(df["delivery_date"])
    df["year"]  = df["delivery_date"].dt.year
    df["month"] = df["delivery_date"].dt.month
    df["is_workday"] = df["delivery_date"].apply(is_workday)

    years = sorted(df["year"].unique().tolist())

    # ── Period grouping ───────────────────────────────────────────────────────
    if period == "Month":
        df["period_key"] = df["month"]
        period_index  = list(range(1, 13))
        period_labels = {m: _cal.month_abbr[m] for m in period_index}
    elif period == "Quarter":
        df["period_key"] = ((df["month"] - 1) // 3) + 1
        period_index  = [1, 2, 3, 4]
        period_labels = {q: f"Q{q}" for q in period_index}
    else:
        df["period_key"] = df["year"]
        period_index  = years
        period_labels = {y: str(y) for y in years}

    # ── Build pivot per product ───────────────────────────────────────────────
    def _pivot(prod):
        work_h    = set(_hours_for_product(prod, True))
        nonwork_h = set(_hours_for_product(prod, False))
        mask = (
            (df["is_workday"]  & df["H"].isin(work_h)) |
            (~df["is_workday"] & df["H"].isin(nonwork_h))
        )
        sub = df[mask]
        if period == "Year":
            grp    = sub.groupby("year")[price_col].mean().round(2)
            result = grp.to_frame(name="Avg [PLN/MWh]")
            result.index.name = "Year"
            return result
        grp = sub.groupby(["year", "period_key"])[price_col].mean().reset_index()
        piv = grp.pivot(index="period_key", columns="year", values=price_col).round(2)
        piv = piv.reindex(period_index)
        piv.columns    = [str(y) for y in piv.columns]
        piv.index      = [period_labels.get(k, str(k)) for k in piv.index]
        piv.index.name = period
        return piv

    t1_base = _pivot("BASE")
    t2_prod = _pivot(product)

    if period == "Year":
        t3 = (t2_prod["Avg [PLN/MWh]"] / t1_base["Avg [PLN/MWh]"]).round(4).to_frame(name="Ratio")
        t3.index.name = "Year"
    else:
        t3 = t2_prod.div(t1_base).round(4)
        t3.columns.name = None

    # ── Centre-align numeric values via Styler ────────────────────────────────
    def _styled(piv_df, decimals=2):
        num_cols = [c for c in piv_df.columns]
        fmt = {c: f"{{:.{decimals}f}}" for c in num_cols}
        return (piv_df.style
                .format(fmt, na_rep="—")
                .set_properties(**{"text-align": "center"})
                .set_table_styles([{"selector": "th", "props": [("text-align", "center")]}]))

    n_rows = len(t1_base)

    # ── Display three tables ──────────────────────────────────────────────────
    st.subheader(f"{fixing}  ·  Period: {period}  ·  Product: {product}")

    if product.startswith("Holidays") and period == "Month":
        st.caption(
            "⚠️ Holidays* products only cover ~13 public-holiday days/year plus "
            "weekends — monthly averages can be noisy with few observations. "
            "Consider Quarter/Year for a more stable view."
        )

    def _col_cfg(piv_df):
        cfg = {}
        if piv_df.index.name:
            cfg[piv_df.index.name] = st.column_config.TextColumn(width=58)
        for col in piv_df.columns:
            lbl = str(col)
            w = 90 if len(lbl) > 6 else 68
            cfg[lbl] = st.column_config.Column(width=w)
        return cfg

    col_b, col_p, col_r = st.columns([1, 1, 1])
    with col_b:
        st.markdown("**Table 1 — BASE**")
        st.dataframe(_styled(t1_base), use_container_width=True,
                     height=_df_height(n_rows), column_config=_col_cfg(t1_base))
    with col_p:
        st.markdown(f"**Table 2 — {product}**")
        st.dataframe(_styled(t2_prod), use_container_width=True,
                     height=_df_height(n_rows), column_config=_col_cfg(t2_prod))
    with col_r:
        st.markdown(f"**Table 3 — Ratio ({product} / BASE)**")
        st.dataframe(_styled(t3, decimals=2), use_container_width=True,
                     height=_df_height(n_rows), column_config=_col_cfg(t3))

    _product_legend()
