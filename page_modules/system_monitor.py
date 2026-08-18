"""
system_monitor.py — TSO / SystemMonitor.

Two operational risk tools for RB/RDN trading decisions, based on PK5 plan data:

  render_tightness_heatmap()    — Tool 1: "System Tightness Monitor"
                                    Heat map of gen_surplus_avail_tso_above (PK5 col. 6)
                                    by date x hour, colour-coded into 4 risk states.

  render_elasticity_tracker()   — Tool 2: "Price-Reserve Elasticity Tracker"
                                    Scatter of D-1 forecast surplus vs actual CEN/COR/CEB
                                    price, with a fitted exponential trend and an
                                    auto-detected inflection point.
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import date, timedelta

from shared import (
    CHART_THEME,
    load_pk5, load_pk5for, load_rb_h_cached,
    is_workday as _is_workday,
)


# ── Risk-state buckets (PK5 col. 6 — surplus above required reserve) ────────
_STATE_LABELS  = ["ALARM", "WARNING", "CAUTION", "SAFE"]
_STATE_COLORS  = ["#8B0000", "#FFA500", "#FFD700", "#008000"]
_STATE_RANGES  = ["< 0 MW", "0 - 500 MW", "500 - 1500 MW", "> 1500 MW"]

def _bucket_grid(arr: np.ndarray) -> np.ndarray:
    out = np.full(arr.shape, np.nan)
    out[arr < 0] = 0
    out[(arr >= 0) & (arr < 500)] = 1
    out[(arr >= 500) & (arr < 1500)] = 2
    out[arr >= 1500] = 3
    return out

def _discrete_colorscale():
    # midpoints between consecutive integers (0,1,2,3) normalized by range=3
    b = [0.0, 0.5/3, 0.5/3, 1.5/3, 1.5/3, 2.5/3, 2.5/3, 1.0]
    cs = []
    for i, c in enumerate(_STATE_COLORS):
        cs.append([b[2*i], c])
        cs.append([b[2*i+1], c])
    return cs


# ══════════════════════════════════════════════════════════════════════════════
#  TOOL 1 — SYSTEM TIGHTNESS MONITOR (Heat Map)
# ══════════════════════════════════════════════════════════════════════════════

def render_tightness_heatmap():
    st.title("Power Reserve")
    st.markdown(
        "<a href='/docs/Wymagana_Rezerwa_Mocy.pdf' target='_blank'>"
        "&#x1F4C4; Wymagana Rezerwa Mocy — dokumentacja PSE (PDF)</a>",
        unsafe_allow_html=True,
    )
    st.caption(
        "Visualizes historical and forecasted power balance tightness from PK5 "
        "('surplus capacity available to TSO above required power reserve'). "
        "Colour reflects the risk of COR (Operating Reserve Price) activation."
    )

    df = load_pk5()
    if df.empty or "gen_surplus_avail_tso_above" not in df.columns:
        st.warning("No PK5 data available.")
        return

    df = df.copy()
    df["hour"] = df["period"].str[:2].astype(int) + 1
    df["gen_surplus_avail_tso_above"] = pd.to_numeric(
        df["gen_surplus_avail_tso_above"], errors="coerce")

    # ── Filters ───────────────────────────────────────────────────────────────
    today = date.today()
    c1, c2, c3, c4 = st.columns([1.5, 1, 1, 1])
    min_d, max_d = df["business_date"].min(), df["business_date"].max()
    default_start = max(min_d, today - timedelta(days=10))
    default_end   = min(max_d, today + timedelta(days=7))
    date_range = c1.date_input(
        "Date range", value=(default_start, default_end),
        min_value=min_d, max_value=max_d,
    )
    daytype     = c2.selectbox("Day type", ["All", "Workday", "Weekend/Holiday"])
    show_legend = c3.checkbox("Show state legend", value=True)
    show_values = c4.checkbox("Show values", value=False)

    if isinstance(date_range, tuple) and len(date_range) == 2:
        start_d, end_d = date_range
    else:
        start_d, end_d = default_start, default_end

    dff = df[(df["business_date"] >= start_d) & (df["business_date"] <= end_d)].copy()
    if daytype != "All":
        dff["is_workday"] = dff["business_date"].apply(_is_workday)
        dff = dff[dff["is_workday"] == (daytype == "Workday")]

    if dff.empty:
        st.info("No data for the selected filters.")
        return

    # ── Heat map ──────────────────────────────────────────────────────────────
    pivot = dff.pivot_table(index="hour", columns="business_date",
                            values="gen_surplus_avail_tso_above", aggfunc="mean")
    pivot = pivot.sort_index()
    bucket_arr = _bucket_grid(pivot.values.astype(float))
    x_labels = [str(d) for d in pivot.columns]
    x_dates  = list(pivot.columns)

    hm_extra = {}
    if show_values:
        _vals = pivot.values.astype(float)
        _text = np.full(_vals.shape, "", dtype=object)
        _valid = np.isfinite(_vals)
        _text[_valid] = _vals[_valid].round(0).astype(int).astype(str)
        hm_extra["text"]         = _text
        hm_extra["texttemplate"] = "%{text}"
        hm_extra["textfont"]     = dict(size=8, color="white")

    fig = go.Figure(go.Heatmap(
        z=bucket_arr,
        x=x_labels,
        y=pivot.index,
        customdata=pivot.values,
        colorscale=_discrete_colorscale(),
        zmin=0, zmax=3,
        hovertemplate="Date: %{x}<br>Hour: %{y}<br>Surplus: %{customdata:.0f} MW<extra></extra>",
        colorbar=dict(
            tickmode="array", tickvals=[0, 1, 2, 3], ticktext=_STATE_LABELS,
            len=0.6,
        ),
        xgap=1, ygap=1,
        **hm_extra,
    ))

    # ── TODAY line — black vertical between last historical and first future ──
    _today_line_x = None
    for _i, _d in enumerate(x_dates):
        if _d > today:
            _today_line_x = _i - 0.5
            break
    if _today_line_x is not None:
        fig.add_shape(
            type="line",
            x0=_today_line_x, x1=_today_line_x, y0=0, y1=1,
            xref="x", yref="paper",
            line=dict(color="black", width=2.5),
        )
        fig.add_annotation(
            x=_today_line_x, y=1.03, text="TODAY",
            showarrow=False, xref="x", yref="paper",
            font=dict(size=10, color="black"), xanchor="center",
        )

    # ── Week separator lines (ISO week boundary) ─────────────────────────────
    for _i in range(len(x_dates) - 1):
        if x_dates[_i].isocalendar()[1] != x_dates[_i + 1].isocalendar()[1]:
            fig.add_shape(
                type="line",
                x0=_i + 0.5, x1=_i + 0.5, y0=0, y1=1,
                xref="x", yref="paper",
                line=dict(color="#555", width=1.5, dash="dot"),
            )

    fig.update_layout(
        **CHART_THEME,
        xaxis=dict(title="Date", type="category"),
        yaxis=dict(title="Hour (1-24)", tickmode="linear", dtick=1),
        height=520,
        margin=dict(l=50, r=20, t=40, b=60),
    )
    st.plotly_chart(fig, use_container_width=True)

    if show_legend:
        leg_cols = st.columns(4)
        for col, label, color, rng in zip(leg_cols, _STATE_LABELS, _STATE_COLORS, _STATE_RANGES):
            col.markdown(
                f'<div style="background:{color};color:white;padding:6px 10px;'
                f'border-radius:6px;text-align:center;font-size:0.85rem;">'
                f'<b>{label}</b><br>{rng}</div>',
                unsafe_allow_html=True,
            )

    # ── Average surplus by hour of day ───────────────────────────────────────
    st.subheader("Average Surplus by Hour")
    by_hour = dff.groupby("hour")["gen_surplus_avail_tso_above"].mean().reset_index()
    fig2 = go.Figure(go.Bar(
        x=by_hour["hour"], y=by_hour["gen_surplus_avail_tso_above"],
        marker=dict(
            color=by_hour["gen_surplus_avail_tso_above"],
            colorscale=[[0, "#8B0000"], [0.15, "#FFA500"], [0.4, "#FFD700"], [1, "#008000"]],
            cmin=-500, cmax=2500,
        ),
    ))
    fig2.add_hline(y=0, line_color="#888", line_width=1)
    fig2.update_layout(
        **CHART_THEME,
        xaxis=dict(title="Hour (1-24)", tickmode="linear", dtick=1),
        yaxis_title="Avg. Surplus [MW]",
        height=300, margin=dict(l=50, r=20, t=10, b=40),
    )
    st.plotly_chart(fig2, use_container_width=True)

    pct_alarm = (dff["gen_surplus_avail_tso_above"] < 0).mean() * 100
    pct_warn  = ((dff["gen_surplus_avail_tso_above"] >= 0) &
                 (dff["gen_surplus_avail_tso_above"] < 500)).mean() * 100
    st.caption(
        f"In the selected window: **{pct_alarm:.1f}%** of hours in ALARM, "
        f"**{pct_warn:.1f}%** in WARNING."
    )

    with st.expander("Description"):
        st.markdown("""
**System Tightness Monitor** maps PK5 column (6) — *surplus generation capacity
available to the TSO above the required power reserve* — onto a 4-state risk scale:

| State | Range | Meaning |
|-------|-------|---------|
| **ALARM** | < 0 MW | Technical reserve deficit — near-certain extreme CEN/CEB price via scarcity pricing |
| **WARNING** | 0–500 MW | High LOLP probability, non-linear COR increase |
| **CAUTION** | 500–1500 MW | Stable but sensitive to a 500 MW+ unit outage |
| **SAFE** | > 1500 MW | Low risk of high imbalance prices |

Source: `data/pse/pk5.parquet` (`gen_surplus_avail_tso_above` = `surplus_cap_avail_tso − req_pow_res`).
Past dates show the latest available (most accurate) PK5 value; future dates show the
5-day-ahead forecast horizon.
        """)


# ══════════════════════════════════════════════════════════════════════════════
#  TOOL 2 — PRICE-RESERVE ELASTICITY TRACKER (Scatter Plot)
# ══════════════════════════════════════════════════════════════════════════════

_PRICE_OPTIONS = {
    "CEN":       "cen_cost",
    "COR":       "cor_cost",
    "CEB (PP)":  "ceb_pp_cost",
    "CEB (SR)":  "ceb_sr_cost",
}

def render_elasticity_tracker():
    st.title("Price-Reserve Elasticity Tracker")
    st.caption(
        "Correlates the D-1 forecast surplus (PK5 col. 6, as known the day before "
        "delivery) with the actual settled price, to find the threshold where short-"
        "position risk becomes unacceptable."
    )

    df_for = load_pk5for()
    rb_h   = load_rb_h_cached()
    if df_for.empty or rb_h.empty:
        st.warning("PK5 snapshot history or RB prices not available.")
        return

    df_for = df_for.copy()
    df_for["diff_days"] = (
        pd.to_datetime(df_for["business_date"]) - pd.to_datetime(df_for["snapshot_date"])
    ).dt.days
    d1 = df_for[df_for["diff_days"] == 1].copy()
    if d1.empty:
        st.warning("No D-1 PK5 snapshots found yet — the snapshot archive needs to "
                   "accumulate at least one day-ahead vintage per delivery date.")
        return
    d1["gen_surplus_avail_tso_above"] = pd.to_numeric(
        d1["gen_surplus_avail_tso_above"], errors="coerce")

    merged = d1.merge(
        rb_h, left_on=["business_date", "H"], right_on=["delivery_date", "H"], how="inner"
    )
    if merged.empty:
        st.warning("No overlapping dates between PK5 D-1 snapshots and RB prices.")
        return

    # ── Filters ───────────────────────────────────────────────────────────────
    c1, c2, c3 = st.columns([1, 1, 1.4])
    price_label = c1.selectbox("Price metric", list(_PRICE_OPTIONS.keys()))
    daytype     = c2.selectbox("Day type", ["All", "Workday", "Weekend/Holiday"], key="ept_daytype")
    threshold   = c3.number_input("Inflection threshold [PLN/MWh]", value=100.0, step=10.0)

    price_col = _PRICE_OPTIONS[price_label]
    if price_col not in merged.columns:
        st.warning(f"Column `{price_col}` not found in RB prices.")
        return

    mm = merged.copy()
    if daytype != "All":
        mm["is_workday"] = mm["business_date"].apply(_is_workday)
        mm = mm[mm["is_workday"] == (daytype == "Workday")]

    mm[price_col] = pd.to_numeric(mm[price_col], errors="coerce")
    mm = mm.dropna(subset=["gen_surplus_avail_tso_above", price_col])
    if mm.empty:
        st.info("No data for the selected filters.")
        return

    x = mm["gen_surplus_avail_tso_above"].to_numpy(dtype=float)
    y = mm[price_col].to_numpy(dtype=float)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x, y=y, mode="markers", name="Hourly observations",
        marker=dict(color="#2979ff", size=5, opacity=0.5),
    ))

    # ── Binned average (robust trend) ────────────────────────────────────────
    bin_w = 200
    bins  = np.arange(np.floor(x.min() / bin_w) * bin_w, np.ceil(x.max() / bin_w) * bin_w + bin_w, bin_w)
    bin_idx = np.digitize(x, bins)
    bin_centers, bin_means = [], []
    for i in range(1, len(bins)):
        mask = bin_idx == i
        if mask.sum() >= 3:
            bin_centers.append((bins[i-1] + bins[i]) / 2)
            bin_means.append(y[mask].mean())
    if bin_centers:
        fig.add_trace(go.Scatter(
            x=bin_centers, y=bin_means, mode="lines+markers",
            name=f"Binned avg ({bin_w} MW)", line=dict(color="#ff6d00", width=2),
        ))

    # ── Exponential trend fit ────────────────────────────────────────────────
    inflection_x = None
    try:
        from scipy.optimize import curve_fit

        def _expf(xv, a, b, c):
            return a * np.exp(-b * xv) + c

        p0 = [max(y.max() - y.min(), 1.0), 0.002, y.min()]
        popt, _ = curve_fit(_expf, x, y, p0=p0, maxfev=10000)
        x_smooth = np.linspace(x.min(), x.max(), 300)
        y_smooth = _expf(x_smooth, *popt)
        fig.add_trace(go.Scatter(
            x=x_smooth, y=y_smooth, mode="lines", name="Exponential trend",
            line=dict(color="#d50000", width=2, dash="dash"),
        ))
        crossings = np.where(np.diff(np.sign(y_smooth - threshold)))[0]
        if len(crossings):
            inflection_x = x_smooth[crossings[0]]
            fig.add_vline(
                x=inflection_x, line_dash="dot", line_color="#666",
                annotation_text=f"Inflection ≈ {inflection_x:.0f} MW",
                annotation_position="top",
            )
    except Exception as e:
        st.caption(f"Exponential fit unavailable ({e}) — showing binned average only.")

    fig.add_hline(y=5000, line_dash="dot", line_color="#999",
                  annotation_text="5,000 PLN/MWh cap", annotation_position="bottom right")

    fig.update_layout(
        **CHART_THEME,
        xaxis_title="PK5 Surplus above Required Reserve (D-1 forecast) [MW]",
        yaxis_title=f"{price_label} [PLN/MWh]",
        height=520,
        legend=dict(orientation="h", y=-0.15),
        margin=dict(l=50, r=20, t=20, b=70),
    )
    st.plotly_chart(fig, use_container_width=True)

    if inflection_x is not None:
        st.success(
            f"Estimated inflection point: surplus below **{inflection_x:.0f} MW** is "
            f"where {price_label} historically starts exceeding {threshold:.0f} PLN/MWh."
        )

    st.caption(f"{len(mm)} hourly observations · D-1 PK5 snapshot vs settled {price_label} price.")

    with st.expander("Description"):
        st.markdown("""
**Price-Reserve Elasticity Tracker** joins the PK5 surplus forecast as it was known
**one day before delivery** (the vintage a trader actually had when deciding a position)
with the **actual settled price** for that hour, to quantify how reserve tightness
translates into financial risk.

- **X axis**: `gen_surplus_avail_tso_above` from the D-1 snapshot in `pk5for.parquet`
  (not the latest/revised value — using a later revision would leak information the
  trader didn't have at decision time).
- **Y axis**: settled CEN / COR / CEB price from `RB_prices_H.parquet`.
- **Trend**: binned average (robust) + exponential curve fit `a·e^(-b·x) + c`.
- **Inflection point**: surplus level where the fitted curve crosses your chosen
  price threshold — i.e. where short-position risk starts increasing sharply.

*Note: the D-1 snapshot archive (`pk5for.parquet`) currently covers a shorter history
than the main PK5 file, so this chart's date range is narrower than the Tightness Monitor's.*
        """)
