import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import os, calendar, re as _re
from datetime import date, timedelta
from shared import (
    CHART_THEME, APP_DIR,
    load_prices, load_de_prices, load_eurpln, load_rb_h_cached,
)

def render_prices():
    prices = load_prices()
    available_dates = sorted(prices[prices["H"] >= 1]["fixing_date"].unique())
    st.title("Polish SPOT")

    # Navigate by DELIVERY date (what the user cares about)
    available_delivery = sorted(prices[prices["H"] >= 1]["delivery_date"].unique())
    last_delivery = available_delivery[-1]

    if "price_date" not in st.session_state:
        st.session_state.price_date = last_delivery

    # Keep session state valid after parquet updates
    if st.session_state.price_date not in available_delivery:
        st.session_state.price_date = last_delivery

    def go_prev():
        idx = available_delivery.index(st.session_state.price_date)
        if idx > 0:
            st.session_state.price_date = available_delivery[idx - 1]

    def go_next():
        idx = available_delivery.index(st.session_state.price_date)
        if idx < len(available_delivery) - 1:
            st.session_state.price_date = available_delivery[idx + 1]

    nav = st.columns([0.07, 0.22, 0.07, 0.46, 0.09, 0.09])
    with nav[0]:
        st.button("◀", on_click=go_prev, use_container_width=True)
    with nav[1]:
        picked = st.date_input("Delivery date", value=st.session_state.price_date,
                               min_value=available_delivery[0], max_value=available_delivery[-1],
                               label_visibility="collapsed")
        if picked != st.session_state.price_date:
            st.session_state.price_date = picked
    with nav[2]:
        st.button("▶", on_click=go_next, use_container_width=True)
    with nav[4]:
        show_cen = st.checkbox("CEN", value=False, help="Show hourly CEN price from PSE")
    with nav[5]:
        show_de = st.checkbox("DE", value=False, help="Show German SPOT price in PLN")

    sel_delivery = st.session_state.price_date
    day = prices[(prices["delivery_date"] == sel_delivery) & (prices["H"] >= 1)].sort_values("H")

    if day.empty:
        st.warning("No data for this date.")
        st.stop()

    # Derive fixing date from the data
    sel_fixing = day.iloc[0]["fixing_date"]

    hours  = day["H"].tolist()
    f1     = day["f1_price_PLN"].tolist()
    sdac   = day["sdac_price_PLN"].tolist()
    spread = day["spread_f1_sdac"].tolist()

    avg_f1   = day["f1_price_PLN"].mean()
    avg_sdac = day["sdac_price_PLN"].mean()

    # ── Load CEN data (RB_prices_H) for selected delivery date ────────────
    cen_by_hour = {}
    if show_cen:
        rb_h_p = load_rb_h_cached()
        if not rb_h_p.empty:
            cen_day = rb_h_p[rb_h_p["delivery_date"] == sel_delivery]
            if not cen_day.empty:
                cen_by_hour = {int(h): round(float(v), 2)
                               for h, v in zip(cen_day["H"], cen_day["cen_cost"])
                               if not pd.isna(v)}

    # ── Load DE data for selected delivery date ───────────────────────────
    de_prices_df = load_de_prices()
    eurpln_df    = load_eurpln()

    de_pln_by_hour = {}
    eur_pln_rate   = None

    if show_de and not de_prices_df.empty:
        de_day = de_prices_df[
            de_prices_df["business_date"] == sel_delivery
        ].sort_values("hour")

        # EUR/PLN rate: use last known rate on or before the delivery date
        if not eurpln_df.empty:
            rate_rows = eurpln_df[eurpln_df["date"] <= sel_delivery].sort_values("date")
            eur_pln_rate = float(rate_rows.iloc[-1]["rate"]) if not rate_rows.empty else 4.28
        else:
            eur_pln_rate = 4.28

        if not de_day.empty:
            for _, row in de_day.iterrows():
                de_pln_by_hour[int(row["hour"])] = round(
                    float(row["price_eur"]) * eur_pln_rate, 2
                )

    # ── Chart 1: Polish SPOT (+ optional DE line) ─────────────────────────
    fig = go.Figure()

    bar_colors = [
        "rgba(30,100,200,0.4)" if (s is not None and not pd.isna(s) and s >= 0)
        else "rgba(200,50,50,0.4)"
        for s in spread
    ]
    fig.add_trace(go.Bar(
        x=hours, y=spread, name="Spread (F1−SDAC)",
        marker_color=bar_colors, yaxis="y2",
        hovertemplate="H%{x:02d}  Spread: %{y:.2f} PLN<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=hours, y=f1, mode="lines", name=f"F1 avg: {avg_f1:.0f}",
        line=dict(color="#1565c0", width=2.5),
        hovertemplate="H%{x:02d}  F1: %{y:.2f} PLN<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=hours, y=sdac, mode="lines", name=f"SDAC avg: {avg_sdac:.0f}",
        line=dict(color="#e65100", width=2.5, dash="dash"),
        hovertemplate="H%{x:02d}  SDAC: %{y:.2f} PLN<extra></extra>",
    ))

    if show_cen and cen_by_hour:
        cen_h = sorted(cen_by_hour.keys())
        cen_v = [cen_by_hour[h] for h in cen_h]
        avg_cen = sum(cen_v) / len(cen_v)
        fig.add_trace(go.Scatter(
            x=cen_h, y=cen_v, mode="lines",
            name=f"CEN avg: {avg_cen:.0f}",
            line=dict(color="#2e7d32", width=2.5, dash="dot"),
            hovertemplate="H%{x:02d}  CEN: %{y:.2f} PLN<extra></extra>",
        ))

    if show_de and de_pln_by_hour:
        de_h = sorted(de_pln_by_hour.keys())
        de_v = [de_pln_by_hour[h] for h in de_h]
        avg_de = sum(de_v) / len(de_v)
        fig.add_trace(go.Scatter(
            x=de_h, y=de_v, mode="lines",
            name=f"DE SPOT avg: {avg_de:.0f}",
            line=dict(color="#795548", width=2, dash="dot"),
            hovertemplate="H%{x:02d}  DE SPOT: %{y:.2f} PLN<extra></extra>",
        ))

    rate_label = f"  |  EUR/PLN: {eur_pln_rate:.4f}" if eur_pln_rate else ""
    fig.update_layout(
        **CHART_THEME,
        title=f"Polish SPOT — Delivery: {sel_delivery}   (Fixing: {sel_fixing}){rate_label}",
        xaxis=dict(title="Hour", tickmode="linear", dtick=1, range=[0.5, 24.5],
                   gridcolor="#eee", linecolor="#ccc"),
        yaxis=dict(title="Price (PLN/MWh)", gridcolor="#eee", linecolor="#ccc"),
        yaxis2=dict(title="Spread (PLN/MWh)", overlaying="y", side="right",
                    showgrid=False, zeroline=True, zerolinecolor="#aaa"),
        legend=dict(orientation="h", y=1.1, x=0, bgcolor="white"),
        height=480, margin=dict(t=80, b=50),
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── Chart 2: German vs Polish SPOT (only when DE checked) ────────────
    if show_de and de_pln_by_hour:
        st.subheader("German vs Polish SPOT")

        # Polish SPOT per hour = average of F1 and SDAC
        pl_spot = {
            h: (float(f) + float(s)) / 2
            for h, f, s in zip(hours, f1, sdac)
            if f is not None and s is not None
            and not pd.isna(f) and not pd.isna(s)
        }

        common_hours = sorted(set(pl_spot.keys()) & set(de_pln_by_hour.keys()))

        if common_hours:
            pl_vals   = [pl_spot[h]          for h in common_hours]
            de_vals   = [de_pln_by_hour[h]   for h in common_hours]
            diff_vals = [pl - de for pl, de in zip(pl_vals, de_vals)]

            diff_colors = [
                "rgba(30,100,200,0.4)" if d >= 0 else "rgba(200,50,50,0.4)"
                for d in diff_vals
            ]

            fig2 = go.Figure()
            fig2.add_trace(go.Bar(
                x=common_hours, y=diff_vals, name="PL − DE",
                marker_color=diff_colors, yaxis="y2",
                hovertemplate="H%{x:02d}  PL−DE: %{y:.2f} PLN<extra></extra>",
            ))
            fig2.add_trace(go.Scatter(
                x=common_hours, y=pl_vals, mode="lines", name="Polish SPOT",
                line=dict(color="#2dc653", width=2.5),
                hovertemplate="H%{x:02d}  PL SPOT: %{y:.2f} PLN<extra></extra>",
            ))
            fig2.add_trace(go.Scatter(
                x=common_hours, y=de_vals, mode="lines", name="German SPOT",
                line=dict(color="#795548", width=2, dash="dot"),
                hovertemplate="H%{x:02d}  DE SPOT: %{y:.2f} PLN<extra></extra>",
            ))
            fig2.update_layout(
                **CHART_THEME,
                title=f"German vs Polish SPOT — Delivery: {sel_delivery}",
                xaxis=dict(title="Hour", tickmode="linear", dtick=1, range=[0.5, 24.5],
                           gridcolor="#eee", linecolor="#ccc"),
                yaxis=dict(title="Price (PLN/MWh)", gridcolor="#eee", linecolor="#ccc"),
                yaxis2=dict(title="Difference (PLN/MWh)", overlaying="y", side="right",
                            showgrid=False, zeroline=True, zerolinecolor="#aaa"),
                legend=dict(orientation="h", y=1.1, x=0, bgcolor="white"),
                height=420, margin=dict(t=80, b=50),
                hovermode="x unified",
            )
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("No German SPOT data available for this delivery date.")

    # ── Metrics ───────────────────────────────────────────────────────────
    spread_clean = [s for s in spread if s is not None and not pd.isna(s)]
    _show_cen_metric = show_cen and bool(cen_by_hour)
    _metrics = st.columns(5 if _show_cen_metric else 4)
    _metrics[0].metric("F1 avg", f"{avg_f1:.1f} PLN/MWh")
    _metrics[1].metric("SDAC avg", f"{avg_sdac:.1f} PLN/MWh")
    _metrics[2].metric("Max spread", f"{max(spread_clean):.1f} PLN/MWh" if spread_clean else "—")
    _metrics[3].metric("Min spread", f"{min(spread_clean):.1f} PLN/MWh" if spread_clean else "—")
    if _show_cen_metric:
        _cen_avg = sum(cen_by_hour.values()) / len(cen_by_hour)
        _metrics[4].metric("CEN avg", f"{_cen_avg:.1f} PLN/MWh")

    # ── Footer ────────────────────────────────────────────────────────────
    st.divider()
    st.markdown(
        "<div style='font-size:0.85rem;color:#666;line-height:1.8'>"
        "<b>Source:</b> TGE — F1 (Day-Ahead Fixing 1) and SDAC (Single Day-Ahead Coupling)<br>"
        "<b>Auto-update:</b> daily at ~06:00 CET via cron (<code>morning</code> job → <code>tge_fixing.py</code>)<br>"
        "<b>DE overlay:</b> EPEX Day-Ahead, updated daily at ~04:00 CET (<code>night</code> job → <code>de_prices.py</code>)<br>"
        "<b>Manual update:</b> SPOT &rsaquo; Update page"
        "</div>",
        unsafe_allow_html=True,
    )





def render_german_spot():

    st.title("German SPOT — EPEX Day-Ahead")

    _de    = load_de_prices()
    _fx_de = load_eurpln()

    if _de.empty:
        st.warning("No DE Spot data. Run the DE Prices pipeline from the Admin page.")
        st.stop()

    _eurpln_de = float(_fx_de["rate"].iloc[-1]) if not _fx_de.empty else 4.28
    _fx_dt_de  = _fx_de["date"].iloc[-1]        if not _fx_de.empty else "—"

    # ── Controls ──────────────────────────────────────────────────────────────
    # Always use datetime.date objects so arrows and date_input stay in sync
    _avail_de = sorted(set(pd.to_datetime(_de["business_date"]).dt.date.tolist()))

    if "de_date" not in st.session_state or st.session_state.de_date not in _avail_de:
        st.session_state.de_date = _avail_de[-1]

    def _de_prev():
        _i = _avail_de.index(st.session_state.de_date)
        if _i > 0:
            st.session_state.de_date = _avail_de[_i - 1]

    def _de_next():
        _i = _avail_de.index(st.session_state.de_date)
        if _i < len(_avail_de) - 1:
            st.session_state.de_date = _avail_de[_i + 1]

    _nav = st.columns([0.07, 0.22, 0.07, 0.46, 0.18])
    with _nav[0]:
        st.button("◀", on_click=_de_prev, use_container_width=True, key="de_prev")
    with _nav[1]:
        _picked_de = st.date_input(
            "Date", value=st.session_state.de_date,
            min_value=_avail_de[0], max_value=_avail_de[-1],
            label_visibility="collapsed",
        )
        if _picked_de != st.session_state.de_date:
            st.session_state.de_date = _picked_de
            st.rerun()
    with _nav[2]:
        st.button("▶", on_click=_de_next, use_container_width=True, key="de_next")
    with _nav[3]:
        st.markdown(
            f"<div style='padding-top:8px;font-size:0.85rem;color:#555;'>"
            f"EUR/PLN: <b>{_eurpln_de:.4f}</b> &nbsp;·&nbsp; "
            f"<span style='color:#aaa'>PLN checkbox applies to chart + tables</span></div>",
            unsafe_allow_html=True,
        )
    with _nav[4]:
        _use_pln = st.checkbox("PLN", value=False, key="de_pln")

    _currency    = "PLN/MWh" if _use_pln else "EUR/MWh"
    _mult        = _eurpln_de if _use_pln else 1.0
    _sel_de_date = st.session_state.de_date

    # Filter using date comparison (business_date stored as strings in parquet)
    _day_de = _de[pd.to_datetime(_de["business_date"]).dt.date == _sel_de_date].copy().sort_values("hour")

    if _day_de.empty:
        st.warning("No data for selected date.")
        st.stop()

    _x_vals  = _day_de["hour"].tolist()
    _prices  = (_day_de["price_eur"] * _mult).round(2).tolist()
    _hover_x = [f"H{h:02d} CET" for h in _x_vals]
    _x_axis  = dict(title="Hour (CET)", tickmode="linear", dtick=1,
                    range=[0.5, 24.5], gridcolor="#eee", linecolor="#ccc")

    # ── Chart ─────────────────────────────────────────────────────────────────
    _fig_de = go.Figure()
    _fig_de.add_hline(y=0, line_color="#aaa", line_width=1)
    _fig_de.add_trace(go.Scatter(
        x=_x_vals, y=_prices,
        mode="lines+markers",
        line=dict(color="#1565c0", width=2.5),
        marker=dict(size=6, color=["#2dc653" if p >= 0 else "#e63946" for p in _prices]),
        customdata=_hover_x,
        hovertemplate="%{customdata}  %{y:.2f} " + _currency + "<extra></extra>",
    ))
    _fig_de.update_layout(
        **CHART_THEME,
        title=f"EPEX Day-Ahead — {_sel_de_date} (CET)",
        xaxis=_x_axis,
        yaxis=dict(title=f"Price ({_currency})", gridcolor="#eee", linecolor="#ccc",
                   zeroline=True, zerolinecolor="#aaa"),
        height=420, margin=dict(t=60, b=60),
        hovermode="x unified",
    )
    st.plotly_chart(_fig_de, use_container_width=True)

    # ── Metrics ───────────────────────────────────────────────────────────────
    _ps = pd.Series(_prices)
    _dm1, _dm2, _dm3, _dm4 = st.columns(4)
    _dm1.metric("Avg",            f"{_ps.mean():.2f} {_currency}")
    _dm2.metric("Min",            f"{_ps.min():.2f} {_currency}")
    _dm3.metric("Max",            f"{_ps.max():.2f} {_currency}")
    _dm4.metric("Negative hours", str((_ps < 0).sum()))

    st.divider()

    # ── Monthly table  +  12-month averages ───────────────────────────────────
    _col_tbl, _col_month = st.columns(2)

    _sel_yr = _sel_de_date.year
    _sel_mo = _sel_de_date.month
    _de["_ym"] = pd.to_datetime(_de["business_date"]).dt.to_period("M")

    _month_mask = (
        (pd.to_datetime(_de["business_date"]).dt.year  == _sel_yr) &
        (pd.to_datetime(_de["business_date"]).dt.month == _sel_mo)
    )
    _month_data = _de[_month_mask]

    with _col_tbl:
        _mo_label = date(_sel_yr, _sel_mo, 1).strftime("%B %Y")
        st.subheader(f"Daily prices — {_mo_label}")
        _daily = (
            _month_data.groupby("business_date")
            .agg(avg=("price_eur", "mean"),
                 min=("price_eur", "min"),
                 max=("price_eur", "max"))
            .reset_index()
            .sort_values("business_date")
        )
        _daily["avg"] = (_daily["avg"] * _mult).round(2)
        _daily["min"] = (_daily["min"] * _mult).round(2)
        _daily["max"] = (_daily["max"] * _mult).round(2)
        _daily.columns = ["Date", f"Avg ({_currency})", f"Min ({_currency})", f"Max ({_currency})"]
        st.dataframe(_daily.sort_values("Date", ascending=False), use_container_width=True, hide_index=True, height=450)

    with _col_month:
        st.subheader("Monthly averages — last 12 months")
        _monthly = (
            _de.groupby("_ym")
            .agg(avg=("price_eur", "mean"),
                 min=("price_eur", "min"),
                 max=("price_eur", "max"))
            .reset_index()
            .sort_values("_ym", ascending=False)
            .head(12)
        )
        _monthly["avg"] = (_monthly["avg"] * _mult).round(2)
        _monthly["min"] = (_monthly["min"] * _mult).round(2)
        _monthly["max"] = (_monthly["max"] * _mult).round(2)
        _monthly["_ym"] = _monthly["_ym"].astype(str)
        _monthly.columns = ["Month", f"Avg ({_currency})", f"Min ({_currency})", f"Max ({_currency})"]
        st.dataframe(_monthly, use_container_width=True, hide_index=True, height=450)

    # ── Footer ────────────────────────────────────────────────────────────────
    st.divider()
    _de_last = _de["business_date"].max()
    st.markdown(
        f"<div style='font-size:0.85rem;color:#666;line-height:1.8'>"
        f"<b>Source:</b> <a href='https://www.electricitymaps.com' target='_blank'>Electricity Maps</a> "
        f"— EPEX SPOT Day-Ahead prices, Germany (DE) bidding zone<br>"
        f"<b>Unit:</b> EUR/MWh &nbsp;·&nbsp; <b>Times:</b> CET (hours 1–24) &nbsp;·&nbsp; "
        f"<b>Granularity:</b> hourly<br>"
        f"<b>Auto-update:</b> daily at ~04:00 CET via cron (<code>night</code> job &rarr; <code>de_prices.py</code>)<br>"
        f"<b>Manual update:</b> SPOT &rsaquo; Update page &nbsp;&nbsp;"
        f"<b>Last data point:</b> {_de_last}"
        f"</div>",
        unsafe_allow_html=True,
    )




