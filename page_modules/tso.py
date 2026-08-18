import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import os, importlib.util
from datetime import date, timedelta
from shared import (
    CHART_THEME, APP_DIR,
    load_pse, load_pk5, load_pk5for, load_pse_demand, load_rb_h_cached,
    PK5FOR_PATH, RB_H_PATH,
    is_workday as _is_workday,
)

RB_Q_PATH = os.path.join(APP_DIR, "data", "rb", "RB_prices_Q.parquet")

def render_pse():
    st.title("CEN Price")

    # ── Load data (H=hourly, Q=15-min) ────────────────────────────────────────
    pse_h = load_rb_h_cached()   # delivery_date, H, cen_cost, cor_cost, ceb_pp_cost, ...
    pse_q = pd.read_parquet(RB_Q_PATH) if os.path.exists(RB_Q_PATH) else pd.DataFrame()
    if not pse_q.empty:
        pse_q["dtime"]         = pd.to_datetime(pse_q["dtime"])
        pse_q["business_date"] = pd.to_datetime(pse_q["business_date"]).dt.date

    if pse_h.empty:
        st.warning("No PSE data available. Press **Update** below.")
        st.stop()

    # ── Controls ──────────────────────────────────────────────────────────────
    available_pse_dates = sorted(pse_h["delivery_date"].unique())

    # Default: today, or yesterday, or last available — always pick the freshest
    _pse_today = date.today()
    _pse_yesterday = _pse_today - timedelta(days=1)
    _pse_default = (
        _pse_today     if _pse_today     in available_pse_dates else
        _pse_yesterday if _pse_yesterday in available_pse_dates else
        available_pse_dates[-1]
    )
    if "pse_date" not in st.session_state:
        st.session_state.pse_date = _pse_default
    if st.session_state.pse_date not in available_pse_dates:
        st.session_state.pse_date = _pse_default
    # If cached date is far behind latest available, reset to freshest
    if st.session_state.pse_date < available_pse_dates[-1] - timedelta(days=3):
        st.session_state.pse_date = _pse_default

    def pse_prev():
        idx = available_pse_dates.index(st.session_state.pse_date)
        if idx > 0:
            st.session_state.pse_date = available_pse_dates[idx - 1]

    def pse_next():
        idx = available_pse_dates.index(st.session_state.pse_date)
        if idx < len(available_pse_dates) - 1:
            st.session_state.pse_date = available_pse_dates[idx + 1]

    nav = st.columns([0.07, 0.22, 0.07, 0.50, 0.25, 0.25])
    with nav[0]:
        st.button("◀", on_click=pse_prev, use_container_width=True, key="pse_prev")
    with nav[1]:
        picked_pse = st.date_input(
            "Date", value=st.session_state.pse_date,
            min_value=available_pse_dates[0], max_value=available_pse_dates[-1],
            label_visibility="collapsed",
        )
        if picked_pse != st.session_state.pse_date:
            st.session_state.pse_date = picked_pse
    with nav[2]:
        st.button("▶", on_click=pse_next, use_container_width=True, key="pse_next")
    with nav[3]:
        granularity = st.radio("Granularity", ["15 min", "Hourly"], horizontal=True, index=1)
    with nav[4]:
        show_balance = st.checkbox("Balance", value=False)
    with nav[5]:
        use_bars = st.checkbox("Bars", value=False)

    sel_pse_date = st.session_state.pse_date

    # ── Prepare series based on granularity ───────────────────────────────────
    if granularity == "Hourly":
        day = pse_h[pse_h["delivery_date"] == sel_pse_date].sort_values("H")
        if day.empty:
            st.warning("No data for selected date.")
            st.stop()
        x_vals  = day["H"].tolist()
        x_axis  = dict(title="Hour", tickmode="linear", dtick=1,
                       range=[0.5, 24.5], gridcolor="#eee", linecolor="#ccc")
        hover_x = [f"H{h:02d}" for h in x_vals]
        tbl_time = hover_x
        src_label = day["source"].iloc[0] if "source" in day.columns else "H"
    else:
        if pse_q.empty:
            st.warning("No 15-min Q data available.")
            st.stop()
        day = pse_q[pse_q["business_date"] == sel_pse_date].sort_values("dtime")
        if day.empty:
            st.warning("No 15-min data for selected date.")
            st.stop()
        x_vals  = day["dtime"].tolist()
        x_axis  = dict(title="Time (Warsaw)", gridcolor="#eee", linecolor="#ccc",
                       tickformat="%H:%M")
        hover_x = day["dtime"].dt.strftime("%H:%M").tolist()
        tbl_time = [t.strftime("%H:%M") for t in day["dtime"]]
        src_label = day["source"].iloc[0] if "source" in day.columns else "H"

    def _get(col):
        return day[col].tolist() if col in day.columns else [None] * len(x_vals)

    cen = _get("cen_cost")
    ceb = _get("ceb_pp_cost")
    cor = _get("cor_cost")
    sk  = _get("sk_cost")
    bal = _get("balance")

    # Source label
    _src_color = "#e65100" if src_label == "F" else "#1565c0"
    _src_text  = "Forecast" if src_label == "F" else "Confirmed"
    st.markdown(
        f"<div style='color:{_src_color};font-weight:600;font-size:13px;"
        f"margin-bottom:8px'>{_src_text}</div>",
        unsafe_allow_html=True,
    )

    # ── Chart ─────────────────────────────────────────────────────────────────
    fig = go.Figure()

    if show_balance:
        bal_colors = [
            "rgba(30,100,200,0.35)" if (b is not None and not pd.isna(b) and b >= 0)
            else "rgba(200,50,50,0.35)" for b in bal
        ]
        fig.add_trace(go.Bar(
            x=x_vals, y=bal, name="Balance (MWh)",
            marker_color=bal_colors, yaxis="y2",
            hovertemplate="%{customdata}  Balance: %{y:.1f} MWh<extra></extra>",
            customdata=hover_x,
        ))

    def _trace(x, y, name, color):
        kw = dict(x=x, y=y, name=name, customdata=hover_x,
                  hovertemplate=f"%{{customdata}}  {name}: %{{y:.2f}} PLN/MWh<extra></extra>")
        if use_bars:
            return go.Bar(**kw, marker_color=color)
        return go.Scatter(**kw, mode="lines+markers",
                          line=dict(color=color, width=2), marker=dict(size=4, color=color))

    fig.add_trace(_trace(x_vals, cen, "CEN", "#1565c0"))
    t_ceb = _trace(x_vals, ceb, "CKOEB", "#2dc653")
    t_ceb.visible = "legendonly"
    fig.add_trace(t_ceb)
    t_cor = _trace(x_vals, cor, "COR", "#29b6f6")
    t_cor.visible = "legendonly"
    fig.add_trace(t_cor)
    t_sk = _trace(x_vals, sk, "SK", "#ff9800")
    t_sk.visible = "legendonly"
    fig.add_trace(t_sk)

    layout = dict(
        **CHART_THEME,
        title=f"PSE Market Data — {sel_pse_date}  [{_src_text}]",
        xaxis=x_axis,
        yaxis=dict(title="Price (PLN/MWh)", gridcolor="#eee", linecolor="#ccc"),
        legend=dict(orientation="v", x=1.02, y=1, xanchor="left",
                    bgcolor="white", bordercolor="#ddd", borderwidth=1, font=dict(size=12)),
        height=500, margin=dict(t=60, b=60, r=160),
        hovermode="x unified", barmode="group",
    )
    if show_balance:
        layout["yaxis2"] = dict(title="Balance (MWh)", overlaying="y", side="right",
                                showgrid=False, zeroline=True, zerolinecolor="#aaa")
    fig.update_layout(**layout)
    st.plotly_chart(fig, use_container_width=True)

    # ── Metrics ───────────────────────────────────────────────────────────────
    def _avg(lst):
        c = [v for v in lst if v is not None and not pd.isna(v)]
        return f"{sum(c)/len(c):.2f}" if c else "—"
    def _max(lst):
        c = [v for v in lst if v is not None and not pd.isna(v)]
        return f"{max(c):.2f}" if c else "—"
    def _avg1(lst):
        c = [v for v in lst if v is not None and not pd.isna(v)]
        return f"{sum(c)/len(c):.1f}" if c else "—"

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("CEN avg",   _avg(cen))
    m2.metric("CEN max",   _max(cen))
    m3.metric("CKOEB avg", _avg(ceb))
    m4.metric("CKOEB max", _max(ceb))
    m5.metric("Bal avg",   _avg1(bal))
    m6.metric("Records",   str(len(day)))

    # ── Price table ───────────────────────────────────────────────────────────
    st.divider()
    st.subheader("Price Table")

    df_tbl = pd.DataFrame({
        "Time":  tbl_time,
        "CEN":   [round(v, 2) if v is not None and not pd.isna(v) else None for v in cen],
        "CKOEB": [round(v, 2) if v is not None and not pd.isna(v) else None for v in ceb],
        "COR":   [round(v, 2) if v is not None and not pd.isna(v) else None for v in cor],
        "SK":    [round(v, 2) if v is not None and not pd.isna(v) else None for v in sk],
        "Bal":   [round(v, 2) if v is not None and not pd.isna(v) else None for v in bal],
    })
    tbl_col, _ = st.columns([0.55, 0.45])
    with tbl_col:
        st.dataframe(df_tbl, use_container_width=True, hide_index=True, height=400)

    # ── Update button ─────────────────────────────────────────────────────────
    st.divider()
    _pse_date_str = sel_pse_date.strftime("%Y-%m-%d")
    _pse_url = (
        f"https://raporty.pse.pl/report/bpci-energy-and-prices"
        f"?chart=true&bpciDataType=FCST&dateFrom={_pse_date_str}&dateTo={_pse_date_str}"
    )
    btn_col, link_col = st.columns([1, 3])
    with btn_col:
        _update_clicked = st.button("Update PSE Prices", use_container_width=True)
    with link_col:
        st.markdown(
            f'<br><a href="{_pse_url}" target="_blank">'
            f'Open PSE portal for {_pse_date_str} ↗</a>',
            unsafe_allow_html=True,
        )
    if _update_clicked:
        _rb_spec = importlib.util.spec_from_file_location(
            "rb_prices", os.path.join(APP_DIR, "procedures", "rb_prices.py")
        )
        _rb_mod = importlib.util.module_from_spec(_rb_spec)
        _rb_spec.loader.exec_module(_rb_mod)
        _lines = []
        with st.spinner("Downloading PSE prices..."):
            _today     = date.today()
            _yesterday = _today - timedelta(days=1)
            # 1. Fetch forecast (F) for yesterday + today — price-fcst fills in
            #    each quarter near real time, so yesterday is usually still
            #    incomplete right after midnight and needs a backfill too.
            _rb_mod.fast_load(dates=[_yesterday, _today], log=lambda m: _lines.append(m))
            # 2. Try confirmed data (H) for today and yesterday directly
            #    Only save quarters where cen_cost is actually available (not NaN)
            import time as _time_rb
            for _d in [_yesterday, _today]:
                _df = _rb_mod._fetch_day_confirm(_d, lambda m: _lines.append(m))
                if _df is not None and not _df.empty:
                    import pandas as _pd_rb
                    _df["cen_cost"] = _pd_rb.to_numeric(_df.get("cen_cost", _pd_rb.Series()), errors="coerce")
                    _df_valid = _df[_df["cen_cost"].notna()]
                    if not _df_valid.empty:
                        _rb_mod._save_to_Q(_df_valid, "H", [_d], lambda m: _lines.append(m))
                        if len(_df_valid) < len(_df):
                            _lines.append(f"  [PARTIAL] {_d}: {len(_df_valid)}/{len(_df)} quarters confirmed")
                    else:
                        _lines.append(f"  [INFO] {_d}: cen_cost not yet confirmed, keeping F")
                _time_rb.sleep(0.2)
            _rb_mod.rebuild_H_from_Q()
            # 3. Confirm any other pending F→H dates
            result = _rb_mod.confirm_prices(log=lambda m: _lines.append(m))
        load_rb_h_cached.clear()
        if result.get("status") == "ok":
            st.success(result.get("message", "Done."))
        else:
            st.error(result.get("message", "Error."))
        with st.expander("Pipeline log"):
            st.text("\n".join(_lines))
        st.rerun()

    # ── Data sources description ───────────────────────────────────────────────
    st.divider()
    st.caption(
        "**Data sources** &nbsp;|&nbsp; "
        "`prices/RB_prices_Q.parquet` — 15-min balancing market data: CEN, COR, CKOEB, SK, Balance "
        "(source **F** = forecast, source **H** = confirmed). "
        "`prices/RB_prices_H.parquet` — hourly averages derived from Q. &nbsp;|&nbsp; "
        "**Update schedule:** 06:00 forecast (F) + confirm previous day (F→H) · 15:30 updated forecast."
    )


def render_pk5():
    st.title("Daily KSE Situation")

    # ── Update button (top) ────────────────────────────────────────────────────
    _pk5_top_c1, _pk5_top_c2 = st.columns([1, 4])
    with _pk5_top_c1:
        if st.button("Update PK5", key="pk5_update_top"):
            import importlib.util as _ilu_pk5t
            _spec_t = _ilu_pk5t.spec_from_file_location(
                "pk5_pipeline",
                os.path.join(APP_DIR, "procedures", "pk5_pipeline.py")
            )
            _mod_t = _ilu_pk5t.module_from_spec(_spec_t)
            _spec_t.loader.exec_module(_mod_t)
            _lines_t = []
            with st.spinner("Downloading PK5 data..."):
                _result_t = _mod_t.run_pipeline(
                    app_dir=APP_DIR,
                    log=lambda m: _lines_t.append(m),
                )
            load_pk5.clear()
            if _result_t.get("status") == "ok":
                st.success(_result_t.get("message", "Done."))
            else:
                st.error(_result_t.get("message", "Something went wrong."))
            with st.expander("Pipeline log"):
                st.text("\n".join(_lines_t))
            st.rerun()

    pk5_df = load_pk5()

    if pk5_df.empty:
        st.warning("No PK5 data yet. Press **Update PK5** above to download.")
    else:
        available_pk5 = sorted(pk5_df["business_date"].unique())

        # Default: today if available, else last available
        _today_pk5 = date.today()
        _pk5_default = (
            _today_pk5 if _today_pk5 in available_pk5 else available_pk5[-1]
        )
        if "pk5_date" not in st.session_state:
            st.session_state.pk5_date = _pk5_default
        if st.session_state.pk5_date not in available_pk5:
            st.session_state.pk5_date = _pk5_default
        # Reset to today if session is stale
        if st.session_state.pk5_date < available_pk5[-1] - timedelta(days=7):
            st.session_state.pk5_date = _pk5_default

        def pk5_prev():
            idx = available_pk5.index(st.session_state.pk5_date)
            if idx > 0:
                st.session_state.pk5_date = available_pk5[idx - 1]

        def pk5_next():
            idx = available_pk5.index(st.session_state.pk5_date)
            if idx < len(available_pk5) - 1:
                st.session_state.pk5_date = available_pk5[idx + 1]

        nav = st.columns([0.07, 0.22, 0.07, 0.30, 0.34])
        with nav[0]:
            st.button("◀", on_click=pk5_prev, use_container_width=True, key="pk5_prev")
        with nav[1]:
            picked_pk5 = st.date_input(
                "Date", value=st.session_state.pk5_date,
                min_value=available_pk5[0], max_value=available_pk5[-1],
                label_visibility="collapsed",
            )
            if picked_pk5 != st.session_state.pk5_date:
                st.session_state.pk5_date = picked_pk5
        with nav[2]:
            st.button("▶", on_click=pk5_next, use_container_width=True, key="pk5_next")
        with nav[3]:
            _use_pd = st.checkbox("Use PowerDemand", value=False, key="pk5_use_pd")
        with nav[4]:
            pass  # spacer

        sel_pk5 = st.session_state.pk5_date
        day_pk5 = pk5_df[pk5_df["business_date"] == sel_pk5].sort_values("plan_dtime")

        # data_type label
        _dtype = day_pk5["data_type"].iloc[0] if "data_type" in day_pk5.columns else "?"
        _dtype_label = "Forecast" if _dtype == "F" else "Historical"
        st.markdown(
            f"<div style='color:{'#e65100' if _dtype=='F' else '#1565c0'};"
            f"font-weight:600;font-size:13px;margin-bottom:6px'>{_dtype_label}</div>",
            unsafe_allow_html=True,
        )

        if day_pk5.empty:
            st.warning("No data for selected date.")
        else:
            hours       = list(range(1, len(day_pk5) + 1))
            total_load  = day_pk5["grid_demand_fcst"].tolist()
            wind        = day_pk5["fcst_wi_tot_gen"].tolist()
            pv          = day_pk5["fcst_pv_tot_gen"].tolist()
            residual_gd = day_pk5["pred_gen_res_not_cov"].tolist() \
                          if "pred_gen_res_not_cov" in day_pk5.columns else []
            hour_labels = [f"H{h:02d}" for h in hours]

            # ── PowerDemand series ─────────────────────────────────────────────
            pd_load = []
            residual_pd = []
            if _use_pd:
                _psd = load_pse_demand()
                if not _psd.empty:
                    _psd_day = _psd[_psd["business_date"] == sel_pk5].copy()
                    if not _psd_day.empty:
                        _psd_day["hour"] = _psd_day["dtime"].dt.hour + 1
                        # Use load_actual if available, else load_fcst
                        _psd_day["load_val"] = _psd_day["load_actual"].fillna(_psd_day["load_fcst"])
                        _psd_h = (
                            _psd_day.groupby("hour")["load_val"].mean()
                            .reindex(range(1, 25))
                        )
                        for h in hours:
                            v = _psd_h.get(h, float("nan"))
                            pd_load.append(None if pd.isna(v) else v)
                        # Residual PD = PowerDemand - wind - pv
                        residual_pd = [
                            (p - w - pv_v)
                            if (p is not None and w is not None and pv_v is not None
                                and not any(pd.isna(x) for x in [p, w, pv_v]))
                            else None
                            for p, w, pv_v in zip(pd_load, wind, pv)
                        ]

            # ── Metrics ───────────────────────────────────────────────────────
            _wind_clean = [v for v in wind if v is not None and not pd.isna(v)]
            _pv_clean   = [v for v in pv   if v is not None and not pd.isna(v)]
            _load_clean = [v for v in total_load if v is not None and not pd.isna(v)]
            _res_clean  = [v for v in residual_gd if v is not None and not pd.isna(v)]
            _load_sum   = sum(_load_clean) if _load_clean else 0
            _wind_share = sum(_wind_clean) / _load_sum * 100 if _load_sum else 0
            _pv_share   = sum(_pv_clean)   / _load_sum * 100 if _load_sum else 0

            mc1, mc2, mc3, mc4, mc5 = st.columns(5)
            mc1.metric("Grid Demand",  f"{max(_load_clean):,.0f} MW" if _load_clean else "—")
            mc2.metric("Min Residual", f"{min(_res_clean):,.0f} MW"  if _res_clean  else "—")
            mc3.metric("Peak Wind",    f"{max(_wind_clean):,.0f} MW" if _wind_clean else "—")
            mc4.metric("Peak PV",      f"{max(_pv_clean):,.0f} MW"   if _pv_clean   else "—")
            mc5.metric("RES / Grid",   f"{_wind_share + _pv_share:.1f}%")

            # ── Chart ─────────────────────────────────────────────────────────
            fig = go.Figure()

            # Bars: Wind + PV
            fig.add_trace(go.Bar(
                x=hours, y=wind, name="Wind", marker_color="#1565c0",
                hovertemplate="%{customdata}  Wind: %{y:,.0f} MW<extra></extra>",
                customdata=hour_labels,
            ))
            fig.add_trace(go.Bar(
                x=hours, y=pv, name="PV (incl. prosumers)", marker_color="#fdd835",
                hovertemplate="%{customdata}  PV: %{y:,.0f} MW<extra></extra>",
                customdata=hour_labels,
            ))

            # Black lines: Grid Demand (solid) + Residual GD (dashed)
            fig.add_trace(go.Scatter(
                x=hours, y=total_load, name="Grid Demand",
                mode="lines", line=dict(color="#212121", width=2.5),
                hovertemplate="%{customdata}  Grid Demand: %{y:,.0f} MW<extra></extra>",
                customdata=hour_labels,
            ))
            if residual_gd:
                fig.add_trace(go.Scatter(
                    x=hours, y=residual_gd, name="Residual Load (GD)",
                    mode="lines", line=dict(color="#212121", width=1.8, dash="dash"),
                    hovertemplate="%{customdata}  Residual GD: %{y:,.0f} MW<extra></extra>",
                    customdata=hour_labels,
                ))

            # Red lines: Power Demand (solid) + Residual PD (dashed) — when checkbox on
            if _use_pd and pd_load:
                fig.add_trace(go.Scatter(
                    x=hours, y=pd_load, name="Power Demand (KSE)",
                    mode="lines", line=dict(color="#e63946", width=2.5),
                    hovertemplate="%{customdata}  Power Demand: %{y:,.0f} MW<extra></extra>",
                    customdata=hour_labels,
                ))
                if residual_pd:
                    fig.add_trace(go.Scatter(
                        x=hours, y=residual_pd, name="Residual Load (PD)",
                        mode="lines", line=dict(color="#e63946", width=1.8, dash="dash"),
                        hovertemplate="%{customdata}  Residual PD: %{y:,.0f} MW<extra></extra>",
                        customdata=hour_labels,
                    ))

            fig.update_layout(
                **CHART_THEME,
                title=f"KSE — {sel_pk5}  [{_dtype_label}]",
                barmode="stack",
                xaxis=dict(title="Hour", tickmode="linear", dtick=1,
                           range=[0.5, len(hours) + 0.5],
                           gridcolor="#eee", linecolor="#ccc"),
                yaxis=dict(title="MW", gridcolor="#eee", linecolor="#ccc"),
                legend=dict(orientation="h", y=1.08, x=0, bgcolor="white"),
                height=520, margin=dict(t=80, b=50),
                hovermode="x unified",
            )
            st.plotly_chart(fig, use_container_width=True)
            st.caption(
                "**Grid Demand** = PK5 grid demand (zapotrzebowanie sieci, net of prosumer PV). "
                "**Residual Load (GD)** = PSE's own estimate (pred_gen_res_not_cov). "
                "**Power Demand** = KSE load (actual if available, else forecast). "
                "**Residual Load (PD)** = Power Demand − Wind − PV."
            )

    # ── Last updated info ──────────────────────────────────────────────────────
    if not pk5_df.empty and "snapshot_date" in pk5_df.columns:
        _pk5_last_snap = pd.to_datetime(pk5_df["snapshot_date"]).max()
        st.divider()
        st.caption(f"Last update: **{_pk5_last_snap.strftime('%Y-%m-%d %H:%M')}**")





def render_pk5_snapshots():
    st.title("PK5 Snapshot Comparison")
    st.caption("Compare daily PSE 5-day plan revisions for any future delivery date.")

    _pfor = load_pk5for()

    if _pfor.empty:
        st.warning("No snapshot history yet. Run PK5 pipeline at least once.")
        st.stop()

    # ── Controls ──────────────────────────────────────────────────────────────
    _pfor_dates     = sorted(_pfor["business_date"].unique())
    _pfor_snaps_all = sorted(_pfor["snapshot_date"].unique())

    # Default business_date: next available future date (or last date in file)
    _today_pfor = date.today()
    _future     = [d for d in _pfor_dates if d > _today_pfor]
    _pfor_def   = _future[0] if _future else _pfor_dates[-1]

    _pc1, _pc2 = st.columns([1, 2])
    with _pc1:
        _pfor_sel_date = st.date_input(
            "Delivery date",
            value=_pfor_def,
            min_value=_pfor_dates[0],
            max_value=_pfor_dates[-1],
            key="pfor_date",
        )

    # Snapshots available for this delivery date
    _snaps_for_date = sorted(
        _pfor[_pfor["business_date"] == _pfor_sel_date]["snapshot_date"].unique()
    )

    with _pc2:
        if not _snaps_for_date:
            st.warning("No snapshots for this delivery date.")
            st.stop()
        # Default: last 5 snapshots (or all if fewer)
        _snap_default = _snaps_for_date[-5:] if len(_snaps_for_date) >= 5 else _snaps_for_date
        _pfor_sel_snaps = st.multiselect(
            "Snapshots to compare",
            options=_snaps_for_date,
            default=_snap_default,
            key="pfor_snaps",
            format_func=lambda d: str(d),
        )

    if not _pfor_sel_snaps:
        st.info("Select at least one snapshot.")
        st.stop()

    # ── Metric selector ───────────────────────────────────────────────────────
    _pfor_metric_map = {
        "Demand [MW]":        "grid_demand_fcst",
        "Wind [MW]":          "fcst_wi_tot_gen",
        "PV [MW]":            "fcst_pv_tot_gen",
        "Net Load [MW]":      "_net_load",
        "Exchange [MW]":      "planned_exchange",
        "Unavailability [MW]":"fcst_unav_energy",
    }
    _pfor_metric_label = st.selectbox(
        "Signal", list(_pfor_metric_map.keys()), key="pfor_metric"
    )
    _pfor_col = _pfor_metric_map[_pfor_metric_label]

    # ── Slice & pivot ─────────────────────────────────────────────────────────
    _pfor_sub = (
        _pfor[
            (_pfor["business_date"] == _pfor_sel_date) &
            (_pfor["snapshot_date"].isin(_pfor_sel_snaps))
        ]
        .sort_values(["snapshot_date", "H"])
        .copy()
    )

    if _pfor_col == "_net_load":
        _pfor_sub["_net_load"] = (
            _pfor_sub["grid_demand_fcst"]
            - _pfor_sub["fcst_wi_tot_gen"]
            - _pfor_sub["fcst_pv_tot_gen"]
        )

    # ── Chart ─────────────────────────────────────────────────────────────────
    _n_snaps = len(_pfor_sel_snaps)
    _sorted_snaps = sorted(_pfor_sel_snaps)

    # Color gradient: light blue → dark blue
    def _snap_color(i, n):
        t = i / max(n - 1, 1)
        r = int(180 - t * 150)
        g = int(210 - t * 110)
        b = int(240 - t * 60)
        return f"rgb({r},{g},{b})"

    _fig_snap = go.Figure()
    for _i, _snap in enumerate(_sorted_snaps):
        _sub_s = _pfor_sub[_pfor_sub["snapshot_date"] == _snap].sort_values("H")
        if _sub_s.empty:
            continue
        _is_latest = (_snap == _sorted_snaps[-1])
        _fig_snap.add_trace(go.Scatter(
            x=_sub_s["H"].tolist(),
            y=_sub_s[_pfor_col].tolist(),
            mode="lines+markers" if _is_latest else "lines",
            name=str(_snap),
            line=dict(
                color=_snap_color(_i, _n_snaps),
                width=3 if _is_latest else 1.5,
            ),
            marker=dict(size=5) if _is_latest else dict(size=0),
            hovertemplate=f"{_snap}  H%{{x:02d}}: %{{y:,.0f}} MW<extra></extra>",
        ))

    _fig_snap.update_layout(
        **CHART_THEME,
        title=f"{_pfor_metric_label}  —  {_pfor_sel_date}",
        xaxis=dict(title="Hour", tickmode="linear", dtick=1,
                   range=[0.5, 24.5], gridcolor="#eee", linecolor="#ccc"),
        yaxis=dict(title="MW", gridcolor="#eee", linecolor="#ccc"),
        legend=dict(title="Snapshot date", orientation="v",
                    bgcolor="rgba(255,255,255,0.9)", bordercolor="#ddd", borderwidth=1),
        height=460, margin=dict(t=60, b=50),
        hovermode="x unified",
    )
    st.plotly_chart(_fig_snap, use_container_width=True)

    # ── Delta vs latest snapshot ───────────────────────────────────────────────
    if len(_pfor_sel_snaps) >= 2:
        st.subheader("Delta vs latest snapshot")
        _latest_snap  = max(_pfor_sel_snaps)
        _earlier_snap = sorted(s for s in _pfor_sel_snaps if s != _latest_snap)[-1]

        _ldf = (_pfor_sub[_pfor_sub["snapshot_date"] == _latest_snap]
                .set_index("H")[_pfor_col].rename(str(_latest_snap)))
        _edf = (_pfor_sub[_pfor_sub["snapshot_date"] == _earlier_snap]
                .set_index("H")[_pfor_col].rename(str(_earlier_snap)))

        _delta_df = pd.concat([_edf, _ldf], axis=1)
        _delta_df["Δ"] = _delta_df[str(_latest_snap)] - _delta_df[str(_earlier_snap)]
        _delta_df.index.name = "H"
        _delta_df = _delta_df.reset_index()

        def _color_delta(val):
            if pd.isna(val) or val == 0:
                return ""
            return "color: #c62828" if val > 0 else "color: #1565c0"

        st.dataframe(
            _delta_df.style
                .format({str(_earlier_snap): "{:,.0f}", str(_latest_snap): "{:,.0f}", "Δ": "{:+,.0f}"}, na_rep="—")
                .applymap(_color_delta, subset=["Δ"]),
            use_container_width=True,
            hide_index=True,
            height=430,
        )
        _sum_delta = _delta_df["Δ"].sum()
        _abs_delta = _delta_df["Δ"].abs().sum()
        st.caption(
            f"Snapshot {_earlier_snap} → {_latest_snap}  ·  "
            f"Sum Δ: **{_sum_delta:+,.0f} MWh**  ·  "
            f"Total abs change: **{_abs_delta:,.0f} MWh**"
        )

    # ── Hourly pivot table (all selected snapshots) ───────────────────────────
    with st.expander("Full hourly table — all snapshots"):
        _pivot = (
            _pfor_sub[["H", "snapshot_date", _pfor_col]]
            .pivot(index="H", columns="snapshot_date", values=_pfor_col)
        )
        _pivot.columns = [str(c) for c in _pivot.columns]
        _pivot.index.name = "H"
        st.dataframe(
            _pivot.reset_index().style.format(
                {c: "{:,.0f}" for c in _pivot.columns}, na_rep="—"
            ),
            use_container_width=True,
            hide_index=True,
            height=430,
        )





def render_power_demand():
    st.title("KSE Power Demand")
    st.caption("Actual vs forecast KSE demand — 15-min resolution, aggregated to hourly.")

    _pd_root = APP_DIR
    _pd_cursor = os.path.join(_pd_root, "prices", "pse_demand_cursor.txt")

    # ── Update button (top) ────────────────────────────────────────────────────
    _pd_col1, _pd_col2 = st.columns([1, 5])
    with _pd_col1:
        if st.button("Update", key="pd_update"):
            import importlib.util as _ilu_pd
            _pd_spec = _ilu_pd.spec_from_file_location(
                "pse_demand", os.path.join(_pd_root, "procedures", "pse_demand.py")
            )
            _pd_mod = _ilu_pd.module_from_spec(_pd_spec)
            _pd_spec.loader.exec_module(_pd_mod)
            _pd_lines = []
            with st.spinner("Downloading KSE demand..."):
                _pd_res = _pd_mod.run_pipeline(
                    app_dir=_pd_root, log=lambda m: _pd_lines.append(m)
                )
            load_pse_demand.clear()
            if _pd_res.get("status") == "ok":
                st.success(_pd_res.get("message", "Done."))
            else:
                st.error(_pd_res.get("message", "Error."))
            with st.expander("Pipeline log"):
                st.text("\n".join(_pd_lines))
            st.rerun()

    _pd_df = load_pse_demand()

    if _pd_df.empty:
        st.warning("No KSE demand data yet. Press **Update** above.")
        st.stop()

    # ── Last updated ───────────────────────────────────────────────────────────
    _pd_last_date = _pd_df["business_date"].max()
    st.caption(f"The page was updated on: **{_pd_last_date}**")

    # ── Date navigation ────────────────────────────────────────────────────────
    _pd_dates = sorted(_pd_df["business_date"].unique())

    if "pd_date" not in st.session_state:
        st.session_state.pd_date = date.today() if date.today() in _pd_dates else _pd_dates[-1]
    if st.session_state.pd_date not in _pd_dates:
        st.session_state.pd_date = _pd_dates[-1]

    def _pd_prev():
        idx = _pd_dates.index(st.session_state.pd_date)
        if idx > 0: st.session_state.pd_date = _pd_dates[idx - 1]

    def _pd_next():
        idx = _pd_dates.index(st.session_state.pd_date)
        if idx < len(_pd_dates) - 1: st.session_state.pd_date = _pd_dates[idx + 1]

    _pd_nav = st.columns([0.07, 0.22, 0.07, 0.64])
    with _pd_nav[0]:
        st.button("◀", on_click=_pd_prev, use_container_width=True, key="pd_prev")
    with _pd_nav[1]:
        _pd_picked = st.date_input(
            "Date", value=st.session_state.pd_date,
            min_value=_pd_dates[0], max_value=_pd_dates[-1],
            label_visibility="collapsed", key="pd_date_input",
        )
        if _pd_picked != st.session_state.pd_date:
            st.session_state.pd_date = _pd_picked
    with _pd_nav[2]:
        st.button("▶", on_click=_pd_next, use_container_width=True, key="pd_next")

    _pd_sel = st.session_state.pd_date
    _pd_day = _pd_df[_pd_df["business_date"] == _pd_sel].copy()

    if _pd_day.empty:
        st.warning("No data for selected date.")
        st.stop()

    # ── Aggregate 15-min → hourly ──────────────────────────────────────────────
    _pd_day["hour"] = _pd_day["dtime"].dt.hour + 1   # 1-24
    _pd_hourly = (
        _pd_day.groupby("hour", as_index=False)
        .agg(load_actual=("load_actual", "mean"), load_fcst=("load_fcst", "mean"))
        .sort_values("hour")
    )
    _pd_hours   = _pd_hourly["hour"].tolist()
    _pd_actual  = _pd_hourly["load_actual"].tolist()
    _pd_fcst    = _pd_hourly["load_fcst"].tolist()
    _pd_dev     = [
        (a - f) if (a is not None and f is not None
                    and not pd.isna(a) and not pd.isna(f)) else None
        for a, f in zip(_pd_actual, _pd_fcst)
    ]
    _pd_hlabels = [f"H{h:02d}" for h in _pd_hours]

    # ── Metrics ────────────────────────────────────────────────────────────────
    _pd_act_c  = [v for v in _pd_actual if v is not None and not pd.isna(v)]
    _pd_fcs_c  = [v for v in _pd_fcst   if v is not None and not pd.isna(v)]
    _pd_dev_c  = [v for v in _pd_dev    if v is not None and not pd.isna(v)]
    _pdm1, _pdm2, _pdm3, _pdm4 = st.columns(4)
    _pdm1.metric("Peak Actual",   f"{max(_pd_act_c):,.0f} MW" if _pd_act_c else "—")
    _pdm2.metric("Peak Forecast", f"{max(_pd_fcs_c):,.0f} MW" if _pd_fcs_c else "—")
    _pdm3.metric("Max +Deviation", f"{max(_pd_dev_c):+,.0f} MW" if _pd_dev_c else "—")
    _pdm4.metric("Max -Deviation", f"{min(_pd_dev_c):+,.0f} MW" if _pd_dev_c else "—")

    # ── Chart 1: Actual vs Forecast + deviation bars ───────────────────────────
    _pd_show_bars = st.checkbox("Show deviation bars", value=True, key="pd_bars")

    _fig_pd = go.Figure()

    if _pd_show_bars:
        _pd_bar_colors = [
            "#e63946" if (v is not None and not pd.isna(v) and v < 0) else "#2dc653"
            for v in _pd_dev
        ]
        _fig_pd.add_trace(go.Bar(
            x=_pd_hours, y=_pd_dev,
            name="Deviation (Actual − Forecast)",
            marker_color=_pd_bar_colors,
            opacity=0.5,
            yaxis="y2",
            hovertemplate="%{customdata}  Dev: %{y:+,.0f} MW<extra></extra>",
            customdata=_pd_hlabels,
        ))

    _fig_pd.add_trace(go.Scatter(
        x=_pd_hours, y=_pd_fcst,
        name="Forecast",
        mode="lines", line=dict(color="#1565c0", width=2),
        hovertemplate="%{customdata}  Forecast: %{y:,.0f} MW<extra></extra>",
        customdata=_pd_hlabels,
    ))
    _fig_pd.add_trace(go.Scatter(
        x=_pd_hours, y=_pd_actual,
        name="Actual",
        mode="lines+markers", line=dict(color="#e63946", width=2.5),
        marker=dict(size=4),
        hovertemplate="%{customdata}  Actual: %{y:,.0f} MW<extra></extra>",
        customdata=_pd_hlabels,
    ))

    _fig_pd.update_layout(
        **CHART_THEME,
        title=f"KSE Load — {_pd_sel}",
        barmode="overlay",
        xaxis=dict(title="Hour", tickmode="linear", dtick=1,
                   range=[0.5, 24.5], gridcolor="#eee", linecolor="#ccc"),
        yaxis=dict(title="MW", gridcolor="#eee", linecolor="#ccc"),
        yaxis2=dict(title="Deviation [MW]", overlaying="y", side="right",
                    showgrid=False, zeroline=True, zerolinecolor="#ccc"),
        legend=dict(orientation="h", y=1.08, x=0, bgcolor="white"),
        height=480, margin=dict(t=80, b=50),
        hovermode="x unified",
    )
    st.plotly_chart(_fig_pd, use_container_width=True)

    # ── Chart 2: PK5 Demand vs KSE Forecast comparison ────────────────────────
    st.subheader("PK5 Plan vs KSE Forecast")
    _pk5_cmp = load_pk5()
    _pk5_cmp_day = pd.DataFrame()
    if not _pk5_cmp.empty:
        _pk5_cmp_day = _pk5_cmp[_pk5_cmp["business_date"] == _pd_sel].copy()
        if not _pk5_cmp_day.empty:
            _pk5_cmp_day = _pk5_cmp_day.sort_values("plan_dtime").reset_index(drop=True)
            _pk5_cmp_day["hour"] = range(1, len(_pk5_cmp_day) + 1)

    if _pk5_cmp_day.empty:
        st.info("No PK5 data for this date.")
    else:
        _cmp_hours  = _pk5_cmp_day["hour"].tolist()
        _cmp_pk5    = _pk5_cmp_day["grid_demand_fcst"].tolist()

        # Align KSE hourly forecast to PK5 hours
        _cmp_kse    = []
        for h in _cmp_hours:
            _row = _pd_hourly[_pd_hourly["hour"] == h]
            _cmp_kse.append(float(_row["load_fcst"].iloc[0])
                            if not _row.empty and not pd.isna(_row["load_fcst"].iloc[0])
                            else None)

        _cmp_dev = [
            (k - p) if (k is not None and p is not None
                        and not pd.isna(k) and not pd.isna(p)) else None
            for k, p in zip(_cmp_kse, _cmp_pk5)
        ]

        _fig_cmp = go.Figure()
        _cmp_bar_colors = [
            "#e63946" if (v is not None and not pd.isna(v) and v < 0) else "#2dc653"
            for v in _cmp_dev
        ]
        _fig_cmp.add_trace(go.Bar(
            x=_cmp_hours, y=_cmp_dev,
            name="Deviation (KSE Fcst − PK5)",
            marker_color=_cmp_bar_colors,
            opacity=0.45,
            yaxis="y2",
            hovertemplate="H%{x:02d}  Dev: %{y:+,.0f} MW<extra></extra>",
        ))
        _fig_cmp.add_trace(go.Scatter(
            x=_cmp_hours, y=_cmp_pk5,
            name="PK5 Grid Demand",
            mode="lines", line=dict(color="#212121", width=2.5),
            hovertemplate="H%{x:02d}  PK5: %{y:,.0f} MW<extra></extra>",
        ))
        _fig_cmp.add_trace(go.Scatter(
            x=_cmp_hours, y=_cmp_kse,
            name="KSE Forecast",
            mode="lines", line=dict(color="#2e7d32", width=2),
            hovertemplate="H%{x:02d}  KSE Fcst: %{y:,.0f} MW<extra></extra>",
        ))

        _fig_cmp.update_layout(
            **CHART_THEME,
            title=f"PK5 Plan vs KSE Forecast — {_pd_sel}",
            barmode="overlay",
            xaxis=dict(title="Hour", tickmode="linear", dtick=1,
                       range=[0.5, 24.5], gridcolor="#eee", linecolor="#ccc"),
            yaxis=dict(title="MW", gridcolor="#eee", linecolor="#ccc"),
            yaxis2=dict(title="Deviation [MW]", overlaying="y", side="right",
                        showgrid=False, zeroline=True, zerolinecolor="#ccc"),
            legend=dict(orientation="h", y=1.08, x=0, bgcolor="white"),
            height=460, margin=dict(t=80, b=50),
            hovermode="x unified",
        )
        st.plotly_chart(_fig_cmp, use_container_width=True)
        st.caption(
            "**PK5 Grid Demand** = PSE 5-day plan (zapotrzebowanie sieci, net of prosumer PV). "
            "**KSE Forecast** = KSE Load API forecast (load_fcst). "
            "Deviation = KSE Forecast − PK5 Plan."
        )

    # ── Demand Statistics by Period ────────────────────────────────────────────
    st.divider()
    st.subheader("Power Demand Statistics by Period")

    _stat_df = _pd_df.copy()
    _stat_df["hour"]       = _stat_df["dtime"].dt.hour + 1
    _stat_df["is_workday"] = _stat_df["business_date"].apply(_is_workday)
    _stat_df["_dt"]        = pd.to_datetime(_stat_df["business_date"])

    _sc_sel, _ = st.columns([1, 4])
    _stat_period = _sc_sel.selectbox("Period", ["Week", "Month", "Quarter", "Year"], index=3, key="pd_stat_period")

    if _stat_period == "Week":
        _stat_df["_pkey"] = _stat_df["_dt"].dt.strftime("%G-W%V")
    elif _stat_period == "Month":
        _stat_df["_pkey"] = _stat_df["_dt"].dt.strftime("%Y-%m")
    elif _stat_period == "Quarter":
        _stat_df["_pkey"] = _stat_df["_dt"].dt.to_period("Q").astype(str)
    else:
        _stat_df["_pkey"] = _stat_df["_dt"].dt.year.astype(str)

    _STAT_PRODS = {
        "BASE":     (set(range(1, 25)), False),
        "PEAK":     (set(range(8, 23)), True),
        "LowPEAK":  (set(range(8, 18)), True),
        "HighPEAK": (set(range(18, 23)), True),
    }

    def _build_stat_tbl(src_df, val_col):
        rows = []
        for _pk, _grp in src_df.groupby("_pkey", sort=True):
            _row = {"Period": _pk}
            for _pname, (_hours, _wd_only) in _STAT_PRODS.items():
                _mask = _grp["hour"].isin(_hours)
                if _wd_only:
                    _mask = _mask & _grp["is_workday"]
                _vals = _grp.loc[_mask, val_col].dropna()
                _row[_pname] = round(float(_vals.mean()), 0) if not _vals.empty else None
            rows.append(_row)
        return (
            pd.DataFrame(rows)
            .sort_values("Period", ascending=False)
            .reset_index(drop=True)
        )

    _stat_tbl = _build_stat_tbl(_stat_df, "load_actual")

    # ── Grid Demand from PK5 ──────────────────────────────────────────────────
    _pk5_raw = load_pk5()
    _gd_tbl  = pd.DataFrame()
    if not _pk5_raw.empty and "grid_demand_fcst" in _pk5_raw.columns:
        _gd_df = _pk5_raw.copy()
        _gd_df["business_date"] = pd.to_datetime(_gd_df["business_date"]).dt.date
        _gd_df["plan_dtime"]    = pd.to_datetime(_gd_df["plan_dtime"], errors="coerce")
        _gd_df["hour"]          = _gd_df["plan_dtime"].dt.hour + 1
        _gd_df["is_workday"]    = _gd_df["business_date"].apply(_is_workday)
        _gd_df["grid_demand_fcst"] = pd.to_numeric(_gd_df["grid_demand_fcst"], errors="coerce")
        # keep latest snapshot per day/hour
        _gd_df = (
            _gd_df.sort_values("publication_ts")
            .drop_duplicates(["business_date", "hour"], keep="last")
        )
        _gd_df["_dt"] = pd.to_datetime(_gd_df["business_date"])
        if _stat_period == "Week":
            _gd_df["_pkey"] = _gd_df["_dt"].dt.strftime("%G-W%V")
        elif _stat_period == "Month":
            _gd_df["_pkey"] = _gd_df["_dt"].dt.strftime("%Y-%m")
        elif _stat_period == "Quarter":
            _gd_df["_pkey"] = _gd_df["_dt"].dt.to_period("Q").astype(str)
        else:
            _gd_df["_pkey"] = _gd_df["_dt"].dt.year.astype(str)
        _gd_tbl = _build_stat_tbl(_gd_df, "grid_demand_fcst")

    # ── Difference table ──────────────────────────────────────────────────────
    _diff_tbl = pd.DataFrame()
    if not _gd_tbl.empty:
        _merged = _stat_tbl.merge(_gd_tbl, on="Period", suffixes=("_kse", "_gd"))
        _diff_rows = []
        for _, r in _merged.iterrows():
            _row = {"Period": r["Period"]}
            for p in ["BASE", "PEAK", "LowPEAK", "HighPEAK"]:
                v_kse = r.get(f"{p}_kse")
                v_gd  = r.get(f"{p}_gd")
                if v_kse is not None and v_gd is not None:
                    _row[p] = round(float(v_kse) - float(v_gd), 0)
                else:
                    _row[p] = None
            _diff_rows.append(_row)
        _diff_tbl = pd.DataFrame(_diff_rows)

    # ── Display ───────────────────────────────────────────────────────────────
    _stat_fmt = {p: "{:,.0f}" for p in ["BASE", "PEAK", "LowPEAK", "HighPEAK"]}

    _flt_col, _ = st.columns([1, 4])
    _period_flt = _flt_col.text_input("Filter Period", value="", placeholder="np. Q2, 2025-W10…", key="pd_stat_flt", label_visibility="collapsed")

    def _apply_filter(tbl):
        if _period_flt.strip():
            mask = tbl["Period"].str.contains(_period_flt.strip(), case=False, na=False)
            return tbl[mask].reset_index(drop=True)
        return tbl

    _stat_tbl_f = _apply_filter(_stat_tbl)
    _gd_tbl_f   = _apply_filter(_gd_tbl)   if not _gd_tbl.empty   else _gd_tbl
    _diff_tbl_f = _apply_filter(_diff_tbl) if not _diff_tbl.empty else _diff_tbl

    _ncols = 3 if not _gd_tbl.empty else 1
    if _ncols == 3:
        _sc1, _sc2, _sc3 = st.columns([1, 1, 1])
        with _sc1:
            st.markdown("**KSE Load** *(load_actual)*")
            st.dataframe(_stat_tbl_f.style.format(_stat_fmt, na_rep="—"),
                         use_container_width=True, hide_index=True)
        with _sc2:
            st.markdown("**Grid Demand** *(grid_demand_fcst, PK5)*")
            st.dataframe(_gd_tbl_f.style.format(_stat_fmt, na_rep="—"),
                         use_container_width=True, hide_index=True)
        with _sc3:
            st.markdown("**Różnica** *(KSE Load − Grid Demand ≈ PV prosument)*")
            st.dataframe(_diff_tbl_f.style.format(_stat_fmt, na_rep="—"),
                         use_container_width=True, hide_index=True)
    else:
        st.markdown("**KSE Load** *(load_actual)*")
        st.dataframe(_stat_tbl_f.style.format(_stat_fmt, na_rep="—"),
                     use_container_width=False, hide_index=True)

    st.markdown(
        "<div style='"
        "border:1px solid #444;border-radius:8px;padding:14px 16px;"
        "font-size:0.83rem;line-height:1.9;margin-top:12px'>"
        "<b>Grid Demand = KSE Load &minus; generacja rozproszona (w tym PV prosumenckie)</b><br><br>"
        "<table style='border-collapse:collapse;width:100%;font-size:0.82rem;margin-bottom:10px'>"
        "<thead><tr style='border-bottom:1px solid #666'>"
        "<th style='text-align:left;padding:3px 8px'>Tabela</th>"
        "<th style='text-align:left;padding:3px 8px'>Zastosowanie</th>"
        "</tr></thead><tbody>"
        "<tr><td style='padding:3px 8px;white-space:nowrap'><b>T2 Grid Demand</b></td>"
        "<td style='padding:3px 8px'>Ile KSE musiało dostarczyć — najlepsza do tradingu i planowania</td></tr>"
        "<tr style='background:rgba(128,128,128,0.08)'><td style='padding:3px 8px;white-space:nowrap'><b>T1 KSE Load</b></td>"
        "<td style='padding:3px 8px'>Całkowity popyt systemu — benchmark makro</td></tr>"
        "<tr><td style='padding:3px 8px;white-space:nowrap'><b>T3 Różnica</b></td>"
        "<td style='padding:3px 8px'>Trend wzrostu PV prosumenckiego — do kalibracji sezonowej</td></tr>"
        "</tbody></table>"
        "<b>KSE Load</b> — <code>load_actual</code>, PSE API <code>kse-load</code>. "
        "Dane od <b>13 czerwca 2024</b>.<br>"
        "<b>Grid Demand</b> — <code>grid_demand_fcst</code>, PK5. "
        "Dane od <b>1 lutego 2025</b>.<br>"
        "<b>Różnica</b> — zawiera też błąd prognozy PK5; w długim okresie błędy się uśredniają.<br><br>"
        "<b>Jednostka:</b> MW &nbsp;·&nbsp; "
        "PEAK / LowPEAK / HighPEAK — tylko dni robocze (pon–pt, bez świąt PL). "
        "BASE — wszystkie godziny, wszystkie dni.<br>"
        "<a href='https://raporty.pse.pl/report/kse-load' target='_blank'>"
        "&#x1F517; PSE — Rzeczywiste i Prognozowane Zapotrzebowanie KSE</a>"
        "</div>",
        unsafe_allow_html=True,
    )

    with st.expander("Product definitions"):
        st.markdown(
            "| Product | Hours | Applies to |\n"
            "|---------|-------|------------|\n"
            "| **BASE** | H01–H24 | All days |\n"
            "| **PEAK** | H08–H22 | Workdays only (Mon–Fri, excl. PL holidays) |\n"
            "| **LowPEAK** | H08–H17 | Workdays only |\n"
            "| **HighPEAK** | H18–H22 | Workdays only |\n"
        )
        st.caption(
            "PEAK/LowPEAK/HighPEAK are calculated on working days only — "
            "same convention as SPOT Daily and SPOTS History."
        )





def render_pse_viewer():
        import importlib.util as _ilu_rb, sys as _sys_rb

        _rb_root = APP_DIR
        _sys_rb.path.insert(0, os.path.join(_rb_root, "procedures"))
        _rb_spec = _ilu_rb.spec_from_file_location(
            "rb_prices", os.path.join(_rb_root, "procedures", "rb_prices.py"))
        _rb_mod = _ilu_rb.module_from_spec(_rb_spec)
        _rb_spec.loader.exec_module(_rb_mod)

        rb_h = _rb_mod.load_rb_h()
        rb_q = _rb_mod.load_rb_q()

        st.title("PSE Viewer — RB Prices")

        # ── Summary ───────────────────────────────────────────────────────────────
        if rb_h.empty:
            st.warning("RB_prices_H.parquet not found. Run migration first.")
            st.stop()

        _h_days   = rb_h["delivery_date"].nunique()
        _h_min    = rb_h["delivery_date"].min()
        _h_max    = rb_h["delivery_date"].max()
        _src_cnt  = rb_h["source"].value_counts().to_dict()
        _c_cnt    = _src_cnt.get("C", 0)
        _i_cnt    = _src_cnt.get("I", 0)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Days in H", _h_days)
        c2.metric("Date from", str(_h_min))
        c3.metric("Date to",   str(_h_max))
        c4.metric("Confirmed / Initial", f"{_c_cnt} / {_i_cnt}")

        st.divider()

        # ── Controls ──────────────────────────────────────────────────────────────
        tab_h, tab_q, tab_mig = st.tabs(["RB_prices_H  (hourly)", "RB_prices_Q  (quarterly)", "Tools"])

        with tab_h:
            _all_dates_h = sorted(rb_h["delivery_date"].unique(), reverse=True)
            fc1, fc2 = st.columns([1, 3])
            with fc1:
                _src_filter = st.multiselect("Source", ["H", "F"], default=["H", "F"], key="pv_src")
            with fc2:
                _date_range = st.select_slider(
                    "Delivery date range",
                    options=_all_dates_h[::-1],
                    value=(_all_dates_h[-1], _all_dates_h[0]),
                    key="pv_date_h",
                )

            _h_view = rb_h[
                (rb_h["delivery_date"] >= _date_range[0]) &
                (rb_h["delivery_date"] <= _date_range[1]) &
                (rb_h["source"].isin(_src_filter))
            ].sort_values(["delivery_date", "H"], ascending=[False, False])

            st.caption(f"{len(_h_view):,} rows · {_h_view['delivery_date'].nunique()} days")

            def _color_cen(val):
                if pd.isna(val): return ""
                return "background-color:#c8f7c5;color:#155724" if val > 0 \
                       else "background-color:#fcd5d5;color:#7b0000"

            def _color_src(val):
                return "background-color:#fff3cd" if val == "F" else ""

            _h_cols = {"delivery_date": "Date", "H": "H", "source": "Src",
                       "cen_cost": "CEN", "cor_cost": "COR", "ceb_pp_cost": "CKOEB",
                       "sk_cost": "SK", "balance": "Balance"}
            _h_disp = _h_view[[c for c in _h_cols if c in _h_view.columns]].rename(columns=_h_cols)
            st.dataframe(
                _h_disp.style
                    .applymap(_color_cen, subset=["CEN"] if "CEN" in _h_disp.columns else [])
                    .applymap(_color_src, subset=["Src"] if "Src" in _h_disp.columns else []),
                use_container_width=True, hide_index=True, height=500,
            )

            st.divider()
            st.subheader("Daily averages")
            _daily = (
                _h_view.groupby("delivery_date")
                .agg(
                    CEN_avg=("cen_cost", "mean"),
                    CEN_max=("cen_cost", "max"),
                    CEN_min=("cen_cost", "min"),
                    Hours=("H", "count"),
                    Source=("source", lambda x: "F" if "F" in x.values else "H"),
                )
                .reset_index()
                .sort_values("delivery_date", ascending=False)
            )
            for col in ["CEN_avg", "CEN_max", "CEN_min"]:
                _daily[col] = _daily[col].round(2)
            st.dataframe(_daily, use_container_width=True, hide_index=True)

        with tab_q:
            if rb_q.empty:
                st.info("RB_prices_Q.parquet not found.")
            else:
                _all_dates_q = sorted(rb_q["business_date"].unique(), reverse=True)
                _sel_day_q = st.selectbox("Select day", _all_dates_q, key="pv_day_q")
                _q_view = rb_q[rb_q["business_date"] == _sel_day_q].sort_values("dtime")
                st.caption(f"{len(_q_view)} quarters · source = {_q_view['source'].unique().tolist()}")
                st.dataframe(_q_view.rename(columns={
                    "dtime": "Datetime",
                    "business_date": "Business date",
                    "cen_cost": "CEN (PLN/MWh)",
                    "source": "Source",
                }), use_container_width=True, hide_index=True, height=450)

        with tab_mig:
            # ── Fast Load (price-fcst → source=F) ─────────────────────────────
            st.subheader("Fast Load — CEN Forecast")
            st.caption(
                "Fetches today's CEN forecast from **price-fcst** endpoint (available ~15 min delay). "
                "Saves as source=**I** (initial). Use this during the day to get fresh prices."
            )
            _fl_col1, _fl_col2 = st.columns([1, 2])
            with _fl_col1:
                _fl_date = st.date_input("Date", value=date.today(), key="pv_fl_date")
            with _fl_col2:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("⚡ Fast Load", type="primary", key="pv_fast_load"):
                    _fl_lines = []
                    with st.spinner("Fetching from price-fcst..."):
                        _fl_res = _rb_mod.fast_load(
                            dates=[_fl_date],
                            log=lambda m: _fl_lines.append(m)
                        )
                    if _fl_res["status"] == "ok":
                        st.success(_fl_res["message"])
                    else:
                        st.error(_fl_res["message"])
                    st.text("\n".join(_fl_lines))

            st.divider()

            # ── Confirm (energy-prices → F→H) ─────────────────────────────────
            st.subheader("Confirm Prices — I → C")
            st.caption(
                "Fetches confirmed CEN from **energy-prices** endpoint and replaces all source=**I** "
                "records with source=**C**. Run by the daily robot or manually."
            )
            if st.button("✅ Confirm F → H", key="pv_confirm"):
                _conf_lines = []
                with st.spinner("Fetching confirmed prices..."):
                    _conf_res = _rb_mod.confirm_prices(log=lambda m: _conf_lines.append(m))
                if _conf_res["status"] == "ok":
                    st.success(_conf_res["message"])
                else:
                    st.error(_conf_res["message"])
                st.text("\n".join(_conf_lines))

            st.divider()

            # ── Migration ──────────────────────────────────────────────────────
            st.subheader("Migration / Full Rebuild")
            st.caption("One-time: rebuilds RB_prices_Q from pse_prices.parquet (source=H) and regenerates RB_prices_H.")
            if st.button("🔄 Run Migration", key="pv_migrate"):
                _mig_lines = []
                with st.spinner("Running..."):
                    _mig_res = _rb_mod.migrate_from_pse(log=lambda m: _mig_lines.append(m))
                if _mig_res["status"] == "ok":
                    st.success(_mig_res["message"])
                else:
                    st.error(_mig_res["message"])
                st.text("\n".join(_mig_lines))

            st.divider()

            # ── How it works ───────────────────────────────────────────────────
            st.subheader("How it works")
            st.markdown("""
    **RB_prices_Q** — master file, quarterly (15-min) CEN data. Never edited directly.

    **RB_prices_H** — derived file, hourly averages built from Q. Rebuilt automatically after every Q update.

    **source = H (History)**
    Data fetched from `energy-prices` endpoint. Published by PSE with ~1 day delay. This is the final, settled CEN price.

    **source = F (Forecast)**
    Data fetched from `price-fcst` endpoint. Available same day with ~15 min delay. This is a forecast — close to final but may differ slightly once confirmed.

    **Typical daily workflow:**
    1. During the day → **⚡ Fast Load** — pulls today's CEN forecast (source=F)
    2. Next morning → **✅ Confirm F→H** — replaces forecast with confirmed prices (source=H)

    **Daily robot** runs `Confirm F→H` automatically once per day, so manual confirmation is optional.

    **Data flow:**
    ```
    price-fcst API  →  RB_prices_Q (source=F)  →  RB_prices_H (F)
                              ↓  next day
    energy-prices API  →  RB_prices_Q (source=H)  →  RB_prices_H (H)
    ```
    """)





