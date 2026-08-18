"""
ancillary.py — Ancillary Market (Rynek Mocy Bilansujących) pages.

Pages:
  render_history()  — aggregate tables: avg prices by period + WRM
  render_daily()    — 24-hour breakdown for a single auction day
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import os, importlib.util
from io import BytesIO
from datetime import date, timedelta

from shared import (
    load_ancillary, load_pk5,
    CHART_THEME, APP_DIR,
)

# ── Constants ─────────────────────────────────────────────────────────────────
_SERVICES   = ["FCR", "aFRR", "mFRR", "RR"]
_COL_UP     = {"FCR": "fcr_g",   "aFRR": "afrr_g",  "mFRR": "mfrrd_g", "RR": "rr_g"}
_COL_DOWN   = {"FCR": "fcr_d",   "aFRR": "afrr_d",  "mFRR": "mfrrd_d", "RR": "rr_d"}

# Product/hour-bucket definitions — same convention as SPOT Daily (spot_analysis.py)
_PROD_HOURS = {
    "BASE":     list(range(1, 25)),
    "PEAK":     list(range(8, 23)),
    "OFFPEAK":  list(range(1, 8)) + [23, 24],
    "LowOFF":   list(range(1, 8)),
    "LowPEAK":  list(range(8, 18)),
    "HighPEAK": list(range(18, 23)),
    "HighOFF":  [23, 24],
}
_PROD_LABEL = {
    "BASE":     "H01–H24",
    "PEAK":     "H08–H22",
    "OFFPEAK":  "H23–H07",
    "LowOFF":   "H01–H07",
    "LowPEAK":  "H08–H17",
    "HighPEAK": "H18–H22",
    "HighOFF":  "H23–H24",
}
_PEAK_HOURS = set(_PROD_HOURS["PEAK"])   # hours 8-22 (15h)

_SERVICE_COLORS = {
    "FCR":  "#2979ff",
    "aFRR": "#00c853",
    "mFRR": "#ff6d00",
    "RR":   "#aa00ff",
}

_WRM_DESCRIPTION = """
**WRM (Wymagana Rezerwa Mocy / Required Power Reserve)** is a key KSE safety parameter:
PSE's estimated upward power reserve needed to cover demand if a balancing-uncertainty
source (ZNZ) occurs. It is calculated every 15 minutes (OREB) per §7.7 of the *Warunki
Dotyczące Bilansowania* (WDB — Balancing Conditions).

**Formula inputs:**
- KSE power demand forecast for the period
- Forecasted total wind and PV generation
- Frequency containment reserve up (FCR — constant, ~200 MW)
- Frequency restoration reserve up (aFRR + mFRR — ~1000 MW, from the reference incident)
- Upper limit = 110% × the 99th percentile of the last year's balancing errors
- Forecast-error correlation coefficients (demand / wind / solar) and a constant term —
  re-estimated quarterly by PSE to minimize the reserve while keeping LOLP < 1% of periods/year

**What pushes WRM up (ZNZ — balancing-uncertainty sources):** demand and RES forecast
errors, cross-border exchange deviations, unplanned generation-unit outages, POB imbalance.

**Where to find it in PK5:**
- Column (4) = WRM (*"Wymagana rezerwa mocy OSP [MW]"*) = `req_pow_res`
- Column (5) = Surplus capacity available to TSO, gross (before netting the reserve) =
  `surplus_cap_avail_tso`
- Column (6) = Surplus **above** WRM = column(5) − column(4) = `gen_surplus_avail_tso_above`

**Price signal:** when column (6) drops below 0 → high risk of COR price activation
(up to 5,000 PLN/MWh).

**Reserve structure:** WRM = FCR + (aFRR + mFRR) + RR. Knowing WRM and the constant
FCR/FRR demand, RR demand follows as the residual.

*Source: PSE — Warunki Dotyczące Bilansowania §7.7 (`examples/26_06_WRM_opis.pdf`).*
"""


def _get_col(service: str, direction: str) -> str:
    return _COL_UP[service] if direction == "UP" else _COL_DOWN[service]


def _prod_avg(prices_by_h: dict, hours: list) -> float:
    vals = [v for h in hours if pd.notna(v := prices_by_h.get(h, float("nan")))]
    return sum(vals) / len(vals) if vals else float("nan")


def _df_height(n_rows: int, row_px: int = 35, header_px: int = 38) -> int:
    return n_rows * row_px + header_px


def _period_label(d: date, granularity: str) -> str:
    if granularity == "Week":
        iso = d.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    if granularity == "Month":
        return d.strftime("%Y-%m")
    if granularity == "Quarter":
        q = (d.month - 1) // 3 + 1
        return f"{d.year}-Q{q}"
    return str(d.year)


def _wrm_from_pk5(df_pk5: pd.DataFrame, product: str) -> pd.DataFrame:
    """Returns df with cols [business_date, wrm] averaged over product hours."""
    if df_pk5.empty or "req_pow_res" not in df_pk5.columns:
        return pd.DataFrame(columns=["business_date", "wrm"])
    df = df_pk5.copy()
    df["hour"] = df["period"].str[:2].astype(int) + 1
    if product == "Peak":
        df = df[df["hour"].isin(_PEAK_HOURS)]
    df["req_pow_res"] = pd.to_numeric(df["req_pow_res"], errors="coerce")
    grp = df.groupby("business_date")["req_pow_res"].mean().reset_index()
    grp.columns = ["business_date", "wrm"]
    return grp


def _to_excel(frames: dict) -> bytes:
    """dict of {sheet_name: DataFrame} → Excel bytes."""
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        for sheet, df in frames.items():
            df.to_excel(w, sheet_name=sheet[:31], index=False)
    return buf.getvalue()


# ══════════════════════════════════════════════════════════════════════════════
#  HISTORY
# ══════════════════════════════════════════════════════════════════════════════

def render_history():
    st.title("Ancillary Market — History")

    df_all = load_ancillary()
    if df_all.empty:
        st.warning("No ancillary data found. Run Admin > RMB pipeline first.")
        return

    df_pk5 = load_pk5()

    # ── Filters ───────────────────────────────────────────────────────────────
    fc1, fc2, fc3, fc4 = st.columns([1, 1, 1, 1])
    granularity = fc1.selectbox("Period",    ["Month", "Week", "Quarter", "Year"], index=0)
    product     = fc2.selectbox("Product",   ["Base", "Peak"], index=0)
    direction   = fc3.selectbox("Direction", ["UP", "DOWN"], index=0)
    service_sel = fc4.selectbox("Service",   ["All"] + _SERVICES, index=0)

    # ── Prepare data ──────────────────────────────────────────────────────────
    df = df_all.copy()
    if product == "Peak":
        df = df[df["hour"].isin(_PEAK_HOURS)]

    # WRM per day
    wrm_daily = _wrm_from_pk5(df_pk5, product)
    wrm_map   = dict(zip(wrm_daily["business_date"], wrm_daily["wrm"]))
    df["wrm"] = df["business_date"].map(wrm_map)

    # Period label
    df["period_lbl"] = df["business_date"].apply(lambda d: _period_label(d, granularity))

    # Service columns to show
    if service_sel == "All":
        svc_cols = _SERVICES
    else:
        svc_cols = [service_sel]

    col_map = {s: _get_col(s, direction) for s in svc_cols}

    # ── Table 1: Avg price per period ─────────────────────────────────────────
    st.subheader(f"Average Price by {granularity} — {direction} [{product}]")

    grp_cols = {c: "mean" for c in col_map.values() if c in df.columns}
    grp_cols["wrm"] = "mean"
    agg = df.groupby("period_lbl").agg(grp_cols).reset_index()
    agg = agg.sort_values("period_lbl", ascending=False)

    rename = {"period_lbl": granularity}
    rename.update({v: k for k, v in col_map.items()})
    rename["wrm"] = "WRM [MW]"
    agg = agg.rename(columns=rename)

    fmt_cols = {c: "{:.2f}" for c in svc_cols if c in agg.columns}
    if "WRM [MW]" in agg.columns:
        fmt_cols["WRM [MW]"] = "{:.0f}"

    st.dataframe(
        agg.style.format(fmt_cols, na_rep="—"),
        use_container_width=True,
        hide_index=True,
    )

    # ── Table 2: Peak vs Base ─────────────────────────────────────────────────
    if product == "Base" and service_sel != "All":
        st.subheader(f"Peak vs Base — {service_sel} {direction}")
        svc_col = col_map[service_sel]

        if svc_col in df_all.columns:
            df2 = df_all.copy()
            df2["period_lbl"] = df2["business_date"].apply(lambda d: _period_label(d, granularity))
            df2["is_peak"]    = df2["hour"].isin(_PEAK_HOURS)

            base_agg = (df2.groupby("period_lbl")[svc_col]
                        .mean()
                        .reset_index()
                        .rename(columns={svc_col: "Base"}))
            peak_agg = (df2[df2["is_peak"]].groupby("period_lbl")[svc_col]
                        .mean()
                        .reset_index()
                        .rename(columns={svc_col: "Peak"}))
            df_pb = base_agg.merge(peak_agg, on="period_lbl", how="left")
            df_pb["Peak/Base"] = (df_pb["Peak"] / df_pb["Base"]).round(3)
            df_pb = df_pb.sort_values("period_lbl", ascending=False).rename(
                columns={"period_lbl": granularity})

            st.dataframe(
                df_pb.style.format({"Base": "{:.2f}", "Peak": "{:.2f}", "Peak/Base": "{:.3f}"},
                                   na_rep="—"),
                use_container_width=True,
                hide_index=True,
            )

    # ── Chart: avg price trend ────────────────────────────────────────────────
    st.subheader("Price Trend")
    fig = go.Figure()
    for s in svc_cols:
        c = col_map[s]
        if c not in df.columns:
            continue
        trend = df.groupby("period_lbl")[c].mean().reset_index().sort_values("period_lbl")
        fig.add_trace(go.Scatter(
            x=trend["period_lbl"], y=trend[c],
            mode="lines+markers", name=s,
            line=dict(color=_SERVICE_COLORS.get(s, "#888")),
        ))
    fig.update_layout(
        **CHART_THEME,
        xaxis_title=granularity, yaxis_title="PLN/MW/h",
        height=380, legend=dict(orientation="h", y=-0.15),
        margin=dict(l=40, r=20, t=20, b=60),
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── Export ────────────────────────────────────────────────────────────────
    xl_bytes = _to_excel({"Summary": agg, "Raw": df_all})
    st.download_button(
        "Download Excel",
        data=xl_bytes,
        file_name=f"ancillary_{granularity}_{product}_{direction}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    # ── Description ───────────────────────────────────────────────────────────
    with st.expander("Description"):
        st.markdown("""
**Ancillary Market — History** shows historical auction results for Polish system services
(*Rynek Mocy Bilansujących / RMB*) sourced from the PSE API (`cmbp-tp` endpoint).

| Service | Description | Contracted capacity |
|---------|-------------|-------------------|
| **FCR** | Frequency Containment Reserve | ~170 MW (constant) |
| **aFRR** | Automatic Frequency Restoration Reserve | part of FRR pool |
| **mFRR** | Manual Frequency Restoration Reserve | part of FRR pool |
| **RR** | Replacement Reserve | Total_Reserve − FCR − (aFRR+mFRR) |

**WRM** (Wymagana Rezerwa Mocy OSP) = total reserve requirement from PK5 5-day plan.

**Directions**: UP = generation capacity (`_g`), DOWN = demand/load capacity (`_d`).
DOWN prices are not available in historical Excel data — they appear after API backfill.

**Peak** = hours 8–22 (15 hours per day, same convention as SPOT Daily). **Base** = all 24 hours.

**Data source**: Excel historical file (2024-06-14 onwards), daily PSE API (`cmbp-tp`) at 07:15.
*mFRR prices in historical (Excel) data equal aFRR — no real mFRR data existed before the
API backfill.*
        """)
        st.markdown("**What is WRM?**")
        st.markdown(_WRM_DESCRIPTION)


# ══════════════════════════════════════════════════════════════════════════════
#  DAILY
# ══════════════════════════════════════════════════════════════════════════════

def render_daily():
    st.title("Ancillary Market — Daily")

    # ── Update button (top) ──────────────────────────────────────────────────
    _upd_c1, _upd_c2 = st.columns([1, 4])
    with _upd_c1:
        if st.button("Update", key="rmb_daily_update_top"):
            _spec = importlib.util.spec_from_file_location(
                "rmb_pipeline", os.path.join(APP_DIR, "procedures", "rmb_pipeline.py")
            )
            _mod = importlib.util.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            _lines = []
            with st.spinner("Downloading RMB auction results (FCR, aFRR, mFRR, RR — UP/DOWN)..."):
                _result = _mod.run_pipeline(app_dir=APP_DIR, log=lambda m: _lines.append(m))
            load_ancillary.clear()
            if _result.get("status") == "ok":
                st.success(_result.get("message", "Done."))
            else:
                st.error(_result.get("message", "Something went wrong."))
            with st.expander("Pipeline log"):
                st.text("\n".join(_lines))
            st.rerun()
    _pse_tomorrow = date.today() + timedelta(days=1)
    _pse_url = (
        f"https://raporty.pse.pl/report/cmbp-tp"
        f"?dateFrom={_pse_tomorrow}&dateTo={_pse_tomorrow}"
    )
    with _upd_c2:
        st.markdown(
            "Main auction settles around **10:00** — press Update after that to fetch "
            "today's UP/DOWN results for all services. &nbsp;|&nbsp; "
            f'<a href="{_pse_url}" target="_blank">Open latest auction on PSE ↗</a>',
            unsafe_allow_html=True,
        )

    df_all = load_ancillary()
    if df_all.empty:
        st.warning("No ancillary data found. Run Admin > RMB pipeline first.")
        return

    df_pk5 = load_pk5()

    available = sorted(df_all["business_date"].unique(), reverse=True)
    default   = available[0] if available else date.today()

    dc1, dc2, dc3 = st.columns([1, 1, 3])
    sel_date  = dc1.date_input("Auction date", value=default,
                               min_value=available[-1], max_value=available[0])
    direction = dc2.selectbox("Direction", ["UP", "DOWN"], key="daily_dir")

    df_day = df_all[df_all["business_date"] == sel_date].copy()
    if df_day.empty:
        st.info(f"No data for {sel_date}.")
        return

    # WRM per hour for selected day
    if not df_pk5.empty and "req_pow_res" in df_pk5.columns:
        df_pk5_day = df_pk5[df_pk5["business_date"] == sel_date].copy()
        df_pk5_day["hour"] = df_pk5_day["period"].str[:2].astype(int) + 1
        df_pk5_day["req_pow_res"] = pd.to_numeric(df_pk5_day["req_pow_res"], errors="coerce")
        wrm_hour = df_pk5_day.groupby("hour")["req_pow_res"].mean()
        df_day["WRM [MW]"] = df_day["hour"].map(wrm_hour)
    else:
        df_day["WRM [MW]"] = None

    # Build display columns
    col_map  = {s: _get_col(s, direction) for s in _SERVICES}
    disp_cols = {"Hour": "hour"}
    disp_cols.update({s: col_map[s] for s in _SERVICES})
    disp_cols["WRM [MW]"] = "WRM [MW]"

    tbl = pd.DataFrame({"Hour": df_day["hour"].values})
    for s in _SERVICES:
        c = col_map[s]
        tbl[s] = df_day[c].values if c in df_day.columns else None
    tbl["WRM [MW]"] = df_day["WRM [MW]"].values

    # Averages footer
    avg_row = {"Hour": "AVG"}
    for s in _SERVICES:
        avg_row[s] = tbl[s].mean() if s in tbl.columns else None
    avg_row["WRM [MW]"] = tbl["WRM [MW]"].mean() if "WRM [MW]" in tbl.columns else None

    tbl_display = pd.concat([tbl, pd.DataFrame([avg_row])], ignore_index=True)

    fmt = {s: "{:.2f}" for s in _SERVICES}
    fmt["WRM [MW]"] = "{:.0f}"

    _col_tbl, _col_prod = st.columns(2)

    with _col_tbl:
        st.subheader(f"Hourly prices — {direction}")
        st.dataframe(
            tbl_display.style.format(fmt, na_rep="—"),
            use_container_width=True,
            hide_index=True,
            height=_df_height(len(tbl_display)),
        )

    with _col_prod:
        st.subheader(f"Price Summary by Product — {direction}")
        prod_rows = []
        for prod, hours in _PROD_HOURS.items():
            row = {"Product": prod, "Hours": _PROD_LABEL[prod]}
            for s in _SERVICES:
                prices_by_h = tbl.set_index("Hour")[s].to_dict()
                row[s] = _prod_avg(prices_by_h, hours)
            prod_rows.append(row)
        prod_df = pd.DataFrame(prod_rows)

        st.dataframe(
            prod_df.style.format({s: "{:.2f}" for s in _SERVICES}, na_rep="—"),
            use_container_width=True,
            hide_index=True,
            height=_df_height(len(prod_df)),
        )

    # ── Chart ─────────────────────────────────────────────────────────────────
    fig = go.Figure()
    for s in _SERVICES:
        c = col_map[s]
        if c not in df_day.columns:
            continue
        fig.add_trace(go.Scatter(
            x=tbl["Hour"], y=tbl[s],
            mode="lines+markers", name=s,
            line=dict(color=_SERVICE_COLORS.get(s, "#888")),
        ))

    # WRM on secondary axis
    if tbl["WRM [MW]"].notna().any():
        fig.add_trace(go.Scatter(
            x=tbl["Hour"], y=tbl["WRM [MW]"],
            mode="lines", name="WRM [MW]",
            line=dict(color="#aaa", dash="dot"),
            yaxis="y2",
        ))
        fig.update_layout(
            yaxis2=dict(
                title="WRM [MW]", overlaying="y", side="right",
                showgrid=False, rangemode="tozero",
            )
        )

    fig.update_layout(
        **CHART_THEME,
        xaxis=dict(title="Hour", tickmode="linear", tick0=1, dtick=1),
        yaxis_title="PLN/MW/h",
        height=400,
        legend=dict(orientation="h", y=-0.18),
        margin=dict(l=40, r=60, t=20, b=70),
        title=dict(text=f"Ancillary Prices — {sel_date} [{direction}]", x=0.5),
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── Download ──────────────────────────────────────────────────────────────
    xl = _to_excel({f"Daily_{sel_date}": tbl, "Product_Summary": prod_df})
    st.download_button(
        "Download Excel",
        data=xl,
        file_name=f"ancillary_daily_{sel_date}_{direction}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    # ── Description ───────────────────────────────────────────────────────────
    with st.expander("Description"):
        st.markdown(f"""
**Ancillary Market — Daily** shows the full 24-hour auction result for a single day.

- **Auction date** = trading day (T); delivery is on T+1 for most services.
- **Peak** = hours 8–22 (15 hours, same convention as SPOT Daily). See the Price Summary
  by Product table for BASE/PEAK/OFFPEAK/LowOFF/LowPEAK/HighPEAK/HighOFF breakdowns.
- **WRM** = *Wymagana Rezerwa Mocy OSP* [MW] from PK5 5-day plan — see "What is WRM?" below.
- **UP** prices come from the historical Excel file from **2024-06-14** onwards; **DOWN**
  prices (FCR/aFRR/mFRR) are only available from the PSE API (`cmbp-tp`) going forward.
  `rr_d` is structurally absent from the PSE report (not a bug).
- The main auction for delivery day D+1 settles around **10:00** on day D — use the
  "Open latest auction on PSE" link above to cross-check against the official report.
- Source: `data/rb/ancillary_prices.parquet`, updated daily via Admin > RMB pipeline.
        """)
        st.markdown("**What is WRM?**")
        st.markdown(_WRM_DESCRIPTION)
