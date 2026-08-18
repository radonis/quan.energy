import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import os
from datetime import date, timedelta, datetime
from shared import (
    CHART_THEME, APP_DIR,
    FORECAST_DB_PATH, DE_FORE_PATH,
    load_prices, load_pk5, load_eurpln, load_de_prices,
    PARQUET_PATH, FORECAST_DB_PATH, DE_FORE_PATH, PK5_PATH,
    RB_H_PATH, DE_EFDE_PATH, DE_PRICES_PATH, DE_FORE_HIST_PATH,
)

def render_forecast():
    import importlib.util as _ilu_fc

    st.title("Price Forecast")
    st.caption("SARIMAX + ML models (DT / RF / XGB) for TGE Fixing prices")

    _fc_root = APP_DIR

    def _load_fc_mod():
        _spec = _ilu_fc.spec_from_file_location(
            "forecast", os.path.join(_fc_root, "procedures", "forecast.py")
        )
        _mod = _ilu_fc.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        return _mod

    # ── Run buttons ───────────────────────────────────────────────────────────
    _fc1, _fc2, _fc3 = st.columns([1, 1, 2])
    with _fc1:
        _btn_f1 = st.button("▶ Run F1", key="fc_run_f1", use_container_width=True, type="primary")
    with _fc2:
        _btn_f2 = st.button("▶ Run F2", key="fc_run_f2", use_container_width=True, type="primary")

    if _btn_f1 or _btn_f2:
        _fc_type = "F1" if _btn_f1 else "F2"
        st.divider()
        st.subheader(f"Running forecast: {_fc_type}")
        _fc_log_box = st.empty()
        _fc_lines   = []

        def _fc_log(msg):
            _fc_lines.append(str(msg))
            _fc_log_box.code("\n".join(_fc_lines), language="bash")

        _fc_mod    = _load_fc_mod()
        _fc_result = _fc_mod.run_pipeline(
            fixing_type=_fc_type,
            db_path=FORECAST_DB_PATH,
            app_dir=_fc_root,
            log=_fc_log,
        )

        if _fc_result.get("status") == "ok":
            st.success(_fc_result["message"])
        else:
            st.error(_fc_result.get("message", "Pipeline error."))

    # ── Last runs history ─────────────────────────────────────────────────────
    st.divider()
    st.subheader("Last runs")

    try:
        import duckdb as _ddb_fc
        if os.path.exists(FORECAST_DB_PATH):
            _fc_con = _ddb_fc.connect(FORECAST_DB_PATH, read_only=True)
            _fc_runs = _fc_con.execute("""
                SELECT
                    run_id,
                    fixing_type,
                    CAST(snapshot_ts AS VARCHAR) AS run_time,
                    CAST(forecast_start AS VARCHAR) AS fc_start,
                    CAST(forecast_end   AS VARCHAR) AS fc_end,
                    CAST(sdac_last_date AS VARCHAR) AS "Last Fixing Date"
                FROM runs
                ORDER BY snapshot_ts DESC
                LIMIT 20
            """).df()
            _fc_con.close()
            if _fc_runs.empty:
                st.info("No forecast runs yet.")
            else:
                st.dataframe(_fc_runs, use_container_width=True, hide_index=True)
        else:
            st.info(f"Forecast DB not found at `{FORECAST_DB_PATH}`.")
    except Exception as _fc_e:
        st.warning(f"Could not load run history: {_fc_e}")

    # ── Data readiness ────────────────────────────────────────────────────────
    st.divider()
    st.subheader("Data readiness")

    def _fc_last_date(path, date_col):
        try:
            if not os.path.exists(path):
                return None, "file missing"
            _df = pd.read_parquet(path, columns=[date_col])
            _d  = pd.to_datetime(_df[date_col]).max()
            return _d.date(), str(_d.date())
        except Exception as _ex:
            return None, f"error: {_ex}"

    def _fc_ger_last():
        try:
            if not os.path.exists(DE_FORE_PATH):
                return None, "file missing"
            _df = pd.read_parquet(DE_FORE_PATH, columns=["run_timestamp"])
            _d  = pd.to_datetime(_df["run_timestamp"]).max()
            return _d.date(), _d.strftime("%Y-%m-%d %H:%M")
        except Exception as _ex:
            return None, f"error: {_ex}"

    def _fc_pk5_last():
        try:
            if not os.path.exists(PK5_PATH):
                return None, "file missing"
            _df = pd.read_parquet(PK5_PATH, columns=["publication_ts"])
            _d  = pd.to_datetime(_df["publication_ts"]).max()
            return _d.date(), _d.strftime("%Y-%m-%d %H:%M")
        except Exception as _ex:
            return None, f"error: {_ex}"

    _today_fc = date.today()

    _ready_sources = [
        ("Last Fixing Date", PARQUET_PATH, "fixing_date", "Trains price model"),
    ]

    _rh1, _rh2, _rh3, _rh4 = st.columns([2, 1.6, 1, 2.5])
    _rh1.markdown("**Source**")
    _rh2.markdown("**Last date**")
    _rh3.markdown("**Status**")
    _rh4.markdown("**Role**")
    st.divider()

    for _src_name, _src_path, _src_col, _src_role in _ready_sources:
        _last_d, _last_str = _fc_last_date(_src_path, _src_col)
        _is_ok  = (_last_d is not None) and (_last_d >= _today_fc - timedelta(days=1))
        _icon   = "✅" if _is_ok else ("⚠️" if _last_d else "❌")
        _rc1, _rc2, _rc3, _rc4 = st.columns([2, 1.6, 1, 2.5])
        _rc1.markdown(_src_name)
        _rc2.markdown(f"`{_last_str}`")
        _rc3.markdown(_icon)
        _rc4.markdown(f"<small style='color:#888'>{_src_role}</small>", unsafe_allow_html=True)

    # PK5 last update (separate — uses publication_ts, not business_date,
    # since business_date max is just the 5-day forecast horizon end and
    # doesn't tell you whether the pipeline actually refreshed today)
    _pk5_d, _pk5_str = _fc_pk5_last()
    _pk5_ok   = (_pk5_d is not None) and (_pk5_d >= _today_fc - timedelta(days=1))
    _pk5_icon = "✅" if _pk5_ok else ("⚠️" if _pk5_d else "❌")
    _pkc1, _pkc2, _pkc3, _pkc4 = st.columns([2, 1.6, 1, 2.5])
    _pkc1.markdown("PK5 last update")
    _pkc2.markdown(f"`{_pk5_str}`")
    _pkc3.markdown(_pk5_icon)
    _pkc4.markdown("<small style='color:#888'>Drives forecast features</small>", unsafe_allow_html=True)

    # GER forecast (separate — uses run_timestamp, not a simple date column)
    _ger_d, _ger_str = _fc_ger_last()
    _ger_ok   = (_ger_d is not None) and (_ger_d >= _today_fc - timedelta(days=1))
    _ger_icon = "✅" if _ger_ok else ("⚠️" if _ger_d else "❌")
    _gc1, _gc2, _gc3, _gc4 = st.columns([2, 1.6, 1, 2.5])
    _gc1.markdown("GER forecast")
    _gc2.markdown(f"`{_ger_str}`")
    _gc3.markdown(_ger_icon)
    _gc4.markdown("<small style='color:#888'>GER comparison plot</small>", unsafe_allow_html=True)





def render_weekly():
    import duckdb as _ddb_wf
    import plotly.graph_objects as _go_wf

    st.title("Weekly Forecast")

    # ── Connect DB ────────────────────────────────────────────────────────────
    if not os.path.exists(FORECAST_DB_PATH):
        st.error(f"Forecast DB not found: `{FORECAST_DB_PATH}`")
        st.stop()

    try:
        _wf_con = _ddb_wf.connect(FORECAST_DB_PATH, read_only=True)
    except Exception as _e:
        st.error(f"Cannot connect to forecast DB: {_e}")
        st.stop()

    # ── Load available F1 runs ────────────────────────────────────────────────
    _wf_runs = _wf_con.execute("""
        SELECT run_id,
               CAST(snapshot_ts AS TIMESTAMP)  AS snapshot_ts,
               CAST(forecast_start AS DATE)    AS forecast_start,
               CAST(forecast_end   AS DATE)    AS forecast_end
        FROM runs
        WHERE fixing_type = 'F1'
        ORDER BY snapshot_ts DESC
        LIMIT 10
    """).df()

    if _wf_runs.empty:
        st.info("No F1 forecast runs found. Run F1 from the Forecast page first.")
        _wf_con.close()
        st.stop()

    # ── Controls row ─────────────────────────────────────────────────────────
    _wf_c1, _wf_c2, _wf_c3 = st.columns([2, 1.5, 2])

    with _wf_c1:
        _wf_run_labels = [
            f"{r['snapshot_ts'].strftime('%Y-%m-%d %H:%M')}  ({r['forecast_start']} – {r['forecast_end']})"
            for _, r in _wf_runs.iterrows()
        ]
        _wf_run_sel = st.selectbox("F1 Run", _wf_run_labels, index=0, key="wf_run_sel")
        _wf_run_idx = _wf_run_labels.index(_wf_run_sel)
        _wf_run_id  = _wf_runs.iloc[_wf_run_idx]["run_id"]
        _wf_fc_start = pd.Timestamp(_wf_runs.iloc[_wf_run_idx]["forecast_start"]).date()
        _wf_fc_end   = pd.Timestamp(_wf_runs.iloc[_wf_run_idx]["forecast_end"]).date()

    with _wf_c2:
        _wf_model = st.selectbox("Model", ["DT", "RF", "XGB", "SARIMAX", "Average"], index=4, key="wf_model")

    with _wf_c3:
        st.write("")
        _wf_cb1, _wf_cb2, _wf_cb3, _wf_cb4 = st.columns(4)
        with _wf_cb1: _wf_show_pv   = st.checkbox("PV",   value=False, key="wf_pv")
        with _wf_cb2: _wf_show_wind = st.checkbox("Wind", value=False, key="wf_wind")
        with _wf_cb3: _wf_show_res  = st.checkbox("RES",  value=True,  key="wf_res")
        with _wf_cb4: _wf_show_rl   = st.checkbox("RL",   value=False, key="wf_rl")

    # ── Week navigation ───────────────────────────────────────────────────────
    # Anchor = Monday of THIS week; offset navigates forward/backward from there
    def _wf_week_monday(d):
        if not isinstance(d, date):
            d = pd.Timestamp(d).date()
        return d - timedelta(days=d.weekday())

    if "wf_offset" not in st.session_state:
        st.session_state["wf_offset"] = 0

    _wf_anchor     = _wf_week_monday(date.today())
    _wf_week_start = _wf_anchor + timedelta(weeks=st.session_state["wf_offset"])
    _wf_week_end   = _wf_week_start + timedelta(days=6)

    _wn1, _wn2, _wn3 = st.columns([0.08, 0.35, 0.08])
    with _wn1:
        if st.button("◀", key="wf_prev", use_container_width=True):
            st.session_state["wf_offset"] -= 1
            st.rerun()
    with _wn2:
        _wf_week_num = _wf_week_start.isocalendar()[1]
        st.markdown(
            f"<div style='text-align:center;font-size:1.1rem;padding-top:6px'>"
            f"<b>Week {_wf_week_num}</b> &nbsp; {_wf_week_start.strftime('%d %b')} – {_wf_week_end.strftime('%d %b %Y')}"
            f"</div>",
            unsafe_allow_html=True,
        )
    with _wn3:
        if st.button("▶", key="wf_next", use_container_width=True):
            st.session_state["wf_offset"] += 1
            st.rerun()

    # ── Load historical F1 prices (daily avg from FixingPricesH) ─────────────
    _wf_hist = load_prices()  # delivery_date, f1_price_PLN, H
    _wf_hist_daily = (
        _wf_hist.groupby("delivery_date")["f1_price_PLN"]
        .mean()
        .reset_index()
        .rename(columns={"f1_price_PLN": "price"})
    )
    _wf_hist_daily["delivery_date"] = pd.to_datetime(_wf_hist_daily["delivery_date"]).dt.date

    # ── Load forecast prices from DuckDB ──────────────────────────────────────
    _wf_fc_raw = _wf_con.execute(f"""
        SELECT CAST(ts AS DATE) AS d,
               model,
               AVG(price_pln_mwh) AS price
        FROM forecast_prices
        WHERE run_id = '{_wf_run_id}'
        GROUP BY d, model
        ORDER BY d, model
    """).df()
    _wf_fc_raw["d"] = pd.to_datetime(_wf_fc_raw["d"]).dt.date

    def _wf_fc_for_day(d):
        sub = _wf_fc_raw[_wf_fc_raw["d"] == d]
        if sub.empty:
            return None
        if _wf_model == "Average":
            return sub["price"].mean()
        row = sub[sub["model"] == _wf_model]
        return row["price"].iloc[0] if not row.empty else None

    # ── Load PK5 generation data (daily avg) ──────────────────────────────────
    _wf_pk5 = load_pk5()
    _wf_pk5_daily = pd.DataFrame()
    if not _wf_pk5.empty:
        _wf_pk5_daily = (
            _wf_pk5.groupby("business_date")[["fcst_pv_tot_gen", "fcst_wi_tot_gen", "grid_demand_fcst"]]
            .mean()
            .reset_index()
        )
        _wf_pk5_daily["business_date"] = pd.to_datetime(_wf_pk5_daily["business_date"]).dt.date
        _wf_pk5_daily["res"] = _wf_pk5_daily["fcst_pv_tot_gen"] + _wf_pk5_daily["fcst_wi_tot_gen"]
        _wf_pk5_daily["rl"]  = (
            _wf_pk5_daily["grid_demand_fcst"]
            - _wf_pk5_daily["fcst_wi_tot_gen"]
            - _wf_pk5_daily["fcst_pv_tot_gen"]
        )

    def _wf_pk5_val(d, col):
        if _wf_pk5_daily.empty:
            return None
        row = _wf_pk5_daily[_wf_pk5_daily["business_date"] == d]
        return row[col].iloc[0] if not row.empty else None

    # ── Build 7-day arrays ────────────────────────────────────────────────────
    _today_wf = date.today()
    _wf_days  = [_wf_week_start + timedelta(days=i) for i in range(7)]
    _wf_labels     = [d.strftime("%a\n%d %b") for d in _wf_days]
    _wf_prices     = []
    _wf_colors     = []
    _wf_is_fc      = []

    for d in _wf_days:
        is_weekend = d.weekday() >= 5
        # try historical first (FixingPricesH); fall back to forecast
        hist_row = _wf_hist_daily[_wf_hist_daily["delivery_date"] == d]
        if not hist_row.empty:
            price = float(hist_row["price"].iloc[0])
            color = "rgba(176,196,222,0.5)" if is_weekend else "rgba(176,196,222,0.85)"
            _wf_is_fc.append(False)
        elif _wf_fc_start <= d <= _wf_fc_end:
            price = _wf_fc_for_day(d)
            color = "rgba(30,100,180,0.45)" if is_weekend else "#1565C0"
            _wf_is_fc.append(True)
        else:
            price = None
            color = "rgba(200,200,200,0.3)"
            _wf_is_fc.append(False)
        _wf_prices.append(price)
        _wf_colors.append(color)

    # ── Build figure ──────────────────────────────────────────────────────────
    _wf_fig = _go_wf.Figure()

    # weekend background shading
    for _i, _d in enumerate(_wf_days):
        if _d.weekday() >= 5:
            _wf_fig.add_shape(
                type="rect",
                x0=_i - 0.5, x1=_i + 0.5,
                y0=0, y1=1,
                xref="x", yref="paper",
                fillcolor="rgba(255,248,200,0.45)",
                line_width=0,
                layer="below",
            )

    # price bars
    _wf_valid_prices = [p for p in _wf_prices if p is not None]
    _wf_text_vals = [f"{p:.0f}" if p is not None else "" for p in _wf_prices]

    _wf_fig.add_trace(_go_wf.Bar(
        x=list(range(7)),
        y=_wf_prices,
        marker_color=_wf_colors,
        text=_wf_text_vals,
        textposition="outside",
        textfont=dict(size=11, color="#333"),
        name="Price (PLN/MWh)",
        yaxis="y1",
    ))

    # secondary axis traces
    _wf_pk5_cols = []
    if _wf_show_pv:   _wf_pk5_cols.append(("fcst_pv_tot_gen", "PV",   "#FFA726", "dot"))
    if _wf_show_wind: _wf_pk5_cols.append(("fcst_wi_tot_gen", "Wind", "#42A5F5", "solid"))
    if _wf_show_res:  _wf_pk5_cols.append(("res",             "RES",  "#66BB6A", "solid"))
    if _wf_show_rl:   _wf_pk5_cols.append(("rl",              "RL",   "#EF5350", "dash"))

    for _col, _name, _clr, _dash in _wf_pk5_cols:
        _vals = [_wf_pk5_val(d, _col) for d in _wf_days]
        _wf_fig.add_trace(_go_wf.Scatter(
            x=list(range(7)),
            y=_vals,
            mode="lines+markers",
            name=_name,
            line=dict(color=_clr, width=2, dash=_dash),
            marker=dict(size=6),
            yaxis="y2",
        ))

    # layout
    _wf_price_min = min(_wf_valid_prices) * 0.85 if _wf_valid_prices else 0
    _wf_price_max = max(_wf_valid_prices) * 1.12 if _wf_valid_prices else 500

    _wf_fig.update_layout(
        height=480,
        margin=dict(t=30, b=10, l=10, r=60),
        plot_bgcolor="#FAFAFA",
        paper_bgcolor="#FFFFFF",
        xaxis=dict(
            tickvals=list(range(7)),
            ticktext=_wf_labels,
            tickfont=dict(size=11),
            showgrid=False,
        ),
        yaxis=dict(
            title="PLN/MWh",
            range=[_wf_price_min, _wf_price_max],
            showgrid=True,
            gridcolor="#EEEEEE",
        ),
        yaxis2=dict(
            title="MW",
            overlaying="y",
            side="right",
            showgrid=False,
        ),
        legend=dict(orientation="h", y=-0.15, x=0),
        bargap=0.25,
        showlegend=True,
    )

    st.plotly_chart(_wf_fig, use_container_width=True)

    # ── Summary row ───────────────────────────────────────────────────────────
    st.markdown("---")
    _sm1, _sm2, _sm3, _sm4, _sm5, _sm6, _sm7 = st.columns(7)

    _wf_valid  = [(d, p) for d, p in zip(_wf_days, _wf_prices) if p is not None]
    _wf_hist_p = [(d, p) for d, p, fc in zip(_wf_days, _wf_prices, _wf_is_fc) if not fc and p is not None]
    _wf_fc_p   = [(d, p) for d, p, fc in zip(_wf_days, _wf_prices, _wf_is_fc) if fc and p is not None]

    _sm1.metric("Week", f"W{_wf_week_num}")

    if _wf_hist_p:
        _hist_avg = sum(p for _, p in _wf_hist_p) / len(_wf_hist_p)
        _sm2.metric("F1 Hist avg", f"{_hist_avg:.1f} PLN")
    else:
        _sm2.metric("F1 Hist avg", "—")

    if _wf_fc_p:
        _fc_avg = sum(p for _, p in _wf_fc_p) / len(_wf_fc_p)
        _fc_max_day = max(_wf_fc_p, key=lambda x: x[1])
        _fc_min_day = min(_wf_fc_p, key=lambda x: x[1])
        _sm3.metric("Forecast avg", f"{_fc_avg:.1f} PLN")
        _sm5.metric(f"Max ({_fc_max_day[0].strftime('%a')})", f"{_fc_max_day[1]:.1f}")
        _sm6.metric(f"Min ({_fc_min_day[0].strftime('%a')})", f"{_fc_min_day[1]:.1f}")
    else:
        _sm3.metric("Forecast avg", "—")
        _sm5.metric("Max day", "—")
        _sm6.metric("Min day", "—")

    # Blended week estimate: hist for realized days + forecast for remaining days
    if _wf_valid:
        _blended_avg = sum(p for _, p in _wf_valid) / len(_wf_valid)
        _n_hist = len(_wf_hist_p)
        _n_fc   = len(_wf_fc_p)
        if _n_hist and _n_fc:
            _blend_label = f"{_n_hist}d hist · {_n_fc}d fcst"
        elif _n_hist:
            _blend_label = "historical"
        else:
            _blend_label = "forecast"
        _sm4.metric("Week Est.", f"{_blended_avg:.1f} PLN", _blend_label, delta_color="off")
    else:
        _sm4.metric("Week Est.", "—")

    _wf_res_vals = [_wf_pk5_val(d, "res") for d in _wf_days]
    _wf_res_valid = [v for v in _wf_res_vals if v is not None]
    if _wf_res_valid:
        _sm7.metric("Avg RES", f"{sum(_wf_res_valid)/len(_wf_res_valid):.0f} MW")
    else:
        _sm7.metric("Avg RES", "—")

    _wf_con.close()





def render_plotting():
    import matplotlib.pyplot as plt
    import numpy as _np
    import duckdb as _ddb_plt

    st.title("Forecast — Plotting")

    # ── Connect DB ────────────────────────────────────────────────────────────
    if not os.path.exists(FORECAST_DB_PATH):
        st.error(f"Forecast DB not found: `{FORECAST_DB_PATH}`")
        st.stop()

    try:
        _pcon = _ddb_plt.connect(FORECAST_DB_PATH, read_only=True)
    except Exception as _e:
        st.error(f"Cannot connect to forecast DB: {_e}")
        st.stop()

    # ── Load latest run per fixing type ───────────────────────────────────────
    _plt_runs = _pcon.execute("""
        SELECT run_id, fixing_type,
               CAST(snapshot_ts AS TIMESTAMP) AS snapshot_ts,
               CAST(forecast_start AS DATE)   AS forecast_start,
               CAST(forecast_end   AS DATE)   AS forecast_end
        FROM runs
        ORDER BY snapshot_ts DESC
    """).df()

    if _plt_runs.empty:
        st.info("No forecast runs yet. Run F1 and F2 from the Forecast page first.")
        _pcon.close()
        st.stop()

    _plt_latest = _plt_runs.drop_duplicates("fixing_type", keep="first").set_index("fixing_type")

    # ── Available delivery dates — always normalize to datetime.date ─────────
    _plt_dates = sorted(
        pd.Timestamp(d).date()
        for d in _pcon.execute("""
            SELECT DISTINCT CAST(ts AS DATE) AS d
            FROM forecast_prices ORDER BY d
        """).df()["d"].tolist()
    )

    if not _plt_dates:
        st.info("No forecast data yet.")
        _pcon.close()
        st.stop()

    # ── Date navigator (shared across tabs) ───────────────────────────────────
    _plt_tomorrow = date.today() + timedelta(days=1)
    if "plt_date" not in st.session_state or st.session_state.plt_date not in _plt_dates:
        st.session_state.plt_date = (
            _plt_tomorrow if _plt_tomorrow in _plt_dates else _plt_dates[0]
        )

    _dnav = st.columns([0.07, 0.20, 0.07, 0.66])
    with _dnav[0]:
        _plt_go_prev = st.button("◀", use_container_width=True, key="plt_prev")
    with _dnav[1]:
        _picked_plt = st.date_input(
            "date", value=st.session_state.plt_date,
            min_value=_plt_dates[0], max_value=_plt_dates[-1],
            label_visibility="collapsed", key="plt_date_inp",
        )
    with _dnav[2]:
        _plt_go_next = st.button("▶", use_container_width=True, key="plt_next")

    # Normalize picked date to datetime.date
    _picked_plt = _picked_plt if isinstance(_picked_plt, type(_plt_dates[0])) else pd.Timestamp(_picked_plt).date()

    _cur_i = _plt_dates.index(st.session_state.plt_date)
    if _plt_go_prev and _cur_i > 0:
        st.session_state.plt_date = _plt_dates[_cur_i - 1]
        st.rerun()
    elif _plt_go_next and _cur_i < len(_plt_dates) - 1:
        st.session_state.plt_date = _plt_dates[_cur_i + 1]
        st.rerun()
    elif _picked_plt != st.session_state.plt_date:
        st.session_state.plt_date = _picked_plt
        st.rerun()

    _sel_date = st.session_state.plt_date

    # ── Shared helpers ────────────────────────────────────────────────────────
    _MODEL_COLORS = {
        "DT":      "#2196F3",
        "RF":      "#4CAF50",
        "XGB":     "#FF9800",
        "SARIMAX": "#9C27B0",
    }

    def _load_fc_day(run_id, sel_date):
        return _pcon.execute(f"""
            SELECT CAST(EXTRACT(HOUR FROM ts) + 1 AS INTEGER) AS H,
                   model, price_pln_mwh
            FROM forecast_prices
            WHERE run_id = '{run_id}'
              AND CAST(ts AS DATE) = '{sel_date}'
            ORDER BY H, model
        """).df()

    def _hourly(df, model):
        if model == "Average":
            return df.groupby("H")["price_pln_mwh"].mean().reset_index()
        return df[df["model"] == model][["H", "price_pln_mwh"]].sort_values("H").reset_index(drop=True)

    def _new_fig(title):
        fig, ax = plt.subplots(figsize=(13, 5))
        fig.patch.set_facecolor("white")
        ax.set_facecolor("white")
        ax.set_title(title, fontsize=11, pad=10)
        ax.set_xlabel("Hour")
        ax.set_ylabel("PLN/MWh")
        ax.set_xticks(range(1, 25))
        ax.grid(True, alpha=0.2)
        return fig, ax

    # ── Tabs ──────────────────────────────────────────────────────────────────
    _tab1, _tab2, _tab3 = st.tabs(["Forecast models", "Arbitrage", "GER comparison"])

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # TAB 1 — Forecast models
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    with _tab1:
        _ft_sel = st.radio("Fixing type", ["F1", "F2"], horizontal=True, key="plt_ft")

        if _ft_sel not in _plt_latest.index:
            st.warning(f"No {_ft_sel} run available. Run the forecast first.")
        else:
            _t1_rid  = _plt_latest.loc[_ft_sel, "run_id"]
            _t1_snap = _plt_latest.loc[_ft_sel, "snapshot_ts"]
            _t1_df   = _load_fc_day(_t1_rid, _sel_date)

            if _t1_df.empty:
                st.info(f"No forecast data for {_sel_date}.")
            else:
                _t1_models = sorted(_t1_df["model"].unique())

                # Model checkboxes
                _cb_cols = st.columns(len(_t1_models) + 1)
                _t1_show = {_m: _cb_cols[_i].checkbox(_m, value=True, key=f"plt1_cb_{_m}")
                            for _i, _m in enumerate(_t1_models)}
                _show_avg = _cb_cols[-1].checkbox("Average", value=True, key="plt1_cb_avg")

                _sel_models = [_m for _m in _t1_models if _t1_show[_m]]
                _snap_str   = str(_t1_snap)[:16]

                fig1, ax1 = _new_fig(f"{_ft_sel} forecast — {_sel_date}  |  run: {_snap_str}")
                _all_vals  = []

                for _m in _sel_models:
                    _sub = _hourly(_t1_df, _m)
                    ax1.plot(_sub["H"], _sub["price_pln_mwh"],
                             color=_MODEL_COLORS.get(_m, "#666"),
                             linewidth=2, label=f"{_m}  avg: {_sub['price_pln_mwh'].mean():.0f}")
                    _all_vals.append(_sub["price_pln_mwh"].values)

                if _show_avg and _all_vals:
                    _mean_v = _np.mean(_np.vstack(_all_vals), axis=0)
                    _h_axis = _hourly(_t1_df, _sel_models[0])["H"]
                    ax1.plot(_h_axis, _mean_v, color="black", linewidth=2.5,
                             linestyle="--", label=f"Average  avg: {_mean_v.mean():.0f}")

                ax1.legend(loc="upper left", fontsize=9)
                fig1.tight_layout()
                st.pyplot(fig1)
                plt.close(fig1)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # TAB 2 — Arbitrage F1 − F2
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    with _tab2:
        if not ("F1" in _plt_latest.index and "F2" in _plt_latest.index):
            st.warning("Both F1 and F2 runs are required. Run both from the Forecast page.")
        else:
            _t2_f1 = _load_fc_day(_plt_latest.loc["F1", "run_id"], _sel_date)
            _t2_f2 = _load_fc_day(_plt_latest.loc["F2", "run_id"], _sel_date)

            if _t2_f1.empty or _t2_f2.empty:
                st.info(f"No data for {_sel_date} in one or both runs.")
            else:
                _t2_models = sorted(set(_t2_f1["model"].unique()) & set(_t2_f2["model"].unique()))
                _t2_sel    = st.selectbox("Model", _t2_models + ["Average"], key="plt2_model")

                _f1h = _hourly(_t2_f1, _t2_sel)
                _f2h = _hourly(_t2_f2, _t2_sel)
                _mrg = _f1h.merge(_f2h, on="H", suffixes=("_f1", "_f2"))
                _mrg["delta"] = _mrg["price_pln_mwh_f1"] - _mrg["price_pln_mwh_f2"]

                _d_avg  = _mrg["delta"].mean()
                _f1_avg = _mrg["price_pln_mwh_f1"].mean()
                _f2_avg = _mrg["price_pln_mwh_f2"].mean()

                fig2, ax2a = plt.subplots(figsize=(13, 6))
                fig2.patch.set_facecolor("white")
                ax2a.set_facecolor("white")
                ax2b = ax2a.twinx()

                ax2a.plot(_mrg["H"], _mrg["price_pln_mwh_f1"],
                          color="#1565C0", linewidth=2.5, label=f"F1  avg: {_f1_avg:.0f}")
                ax2a.plot(_mrg["H"], _mrg["price_pln_mwh_f2"],
                          color="#C62828", linewidth=2.5, linestyle="--",
                          label=f"F2  avg: {_f2_avg:.0f}")

                _bcolors = ["#4CAF50" if v >= 0 else "#F44336" for v in _mrg["delta"]]
                ax2b.bar(_mrg["H"], _mrg["delta"], color=_bcolors, alpha=0.35, width=0.6)
                for _, _r in _mrg.iterrows():
                    _v = _r["delta"]
                    ax2b.text(_r["H"], _v + (0.8 if _v >= 0 else -0.8),
                              f"{int(round(_v))}", ha="center",
                              va="bottom" if _v >= 0 else "top", fontsize=7.5, color="#333")

                ax2a.set_title(f"Arbitrage F1−F2  |  {_t2_sel}  |  {_sel_date}  |  Δ avg: {_d_avg:.0f} PLN/MWh",
                               fontsize=11, pad=10)
                ax2a.set_xlabel("Hour")
                ax2a.set_ylabel("PLN/MWh")
                ax2b.set_ylabel("Δ F1−F2 (PLN/MWh)", color="#555")
                ax2a.set_xticks(range(1, 25))
                ax2a.grid(True, alpha=0.2)
                ax2a.legend(loc="upper left", fontsize=9)
                fig2.tight_layout()
                st.pyplot(fig2)
                plt.close(fig2)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # TAB 3 — GER comparison
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    with _tab3:
        if not os.path.exists(DE_FORE_PATH):
            st.warning(f"German forecast file not found at `{DE_FORE_PATH}`. "
                       "It is generated daily at 07:10 by DE_forecast.py on OVH.")
        elif "F1" not in _plt_latest.index:
            st.warning("No F1 run available. Run F1 from the Forecast page first.")
        else:
            try:
                _ger = pd.read_parquet(DE_FORE_PATH)
                _ger["datetime"] = pd.to_datetime(_ger["datetime"], utc=True).dt.tz_convert("Europe/Warsaw")
                _ger["date"]     = _ger["datetime"].dt.date
                _ger["H"]        = _ger["datetime"].dt.hour + 1

                # Use live EUR/PLN from app data
                _fx_live = load_eurpln()
                if not _fx_live.empty:
                    _live_rate  = float(_fx_live["rate"].iloc[-1])
                    _rate_label = f"EUR/PLN {_live_rate:.4f} (live)"
                else:
                    _live_rate  = float(_ger["kurs"].iloc[0]) if "kurs" in _ger.columns else 4.28
                    _rate_label = f"EUR/PLN {_live_rate:.4f} (file)"

                _ger["PricePL"] = _ger["PriceEU"] * _live_rate
                _ger_run_ts     = str(pd.to_datetime(_ger["run_timestamp"].max()))[:16]

            except Exception as _ge:
                st.error(f"Cannot load German forecast: {_ge}")
                st.stop()

            _ger_day = _ger[_ger["date"] == _sel_date]

            if _ger_day.empty:
                st.info(f"No German forecast for {_sel_date}. "
                        f"GER file covers 72 h from last run ({_ger_run_ts}).")
            else:
                _t3_f1 = _load_fc_day(_plt_latest.loc["F1", "run_id"], _sel_date)

                if _t3_f1.empty:
                    st.info(f"No F1 forecast data for {_sel_date}.")
                else:
                    _t3_models = sorted(_t3_f1["model"].unique())
                    _t3_sel    = st.selectbox("Model (F1)", _t3_models + ["Average"], key="plt3_model")

                    _f1h3  = _hourly(_t3_f1, _t3_sel)
                    _gerh  = _ger_day.groupby("H")["PricePL"].mean().reset_index()
                    _mrg3  = _gerh.merge(_f1h3, on="H")
                    _mrg3["delta"] = _mrg3["PricePL"] - _mrg3["price_pln_mwh"]

                    # Color: top 3 → green, bottom 3 → red, rest → gray
                    _top3    = set(_mrg3["delta"].nlargest(3).index)
                    _bot3    = set(_mrg3["delta"].nsmallest(3).index)
                    _bcol3   = ["#4CAF50" if i in _top3 else "#F44336" if i in _bot3 else "#9E9E9E"
                                for i in _mrg3.index]

                    _ger_avg = _mrg3["PricePL"].mean()
                    _pol_avg = _mrg3["price_pln_mwh"].mean()
                    _d3_avg  = _mrg3["delta"].mean()

                    fig3, ax3a = plt.subplots(figsize=(13, 6))
                    fig3.patch.set_facecolor("white")
                    ax3a.set_facecolor("white")
                    ax3b = ax3a.twinx()

                    ax3a.plot(_mrg3["H"], _mrg3["PricePL"],
                              color="#2E7D32", linewidth=2.5, linestyle=":",
                              label=f"GER ({_rate_label})  avg: {_ger_avg:.0f}")
                    ax3a.plot(_mrg3["H"], _mrg3["price_pln_mwh"],
                              color="#1565C0", linewidth=2.5,
                              label=f"F1 {_t3_sel}  avg: {_pol_avg:.0f}")

                    ax3b.bar(_mrg3["H"], _mrg3["delta"], color=_bcol3, alpha=0.4, width=0.7)
                    ax3b.axhline(0, color="#999", linewidth=0.8, linestyle="--")
                    for _, _r in _mrg3.iterrows():
                        _v = _r["delta"]
                        ax3b.text(_r["H"], _v + (0.8 if _v >= 0 else -0.8),
                                  f"{int(round(_v))}", ha="center",
                                  va="bottom" if _v >= 0 else "top", fontsize=7.5, color="#333")

                    ax3a.set_title(
                        f"GER vs F1 ({_t3_sel})  |  {_sel_date}  |  Δ avg: {_d3_avg:.0f}  |  GER run: {_ger_run_ts}",
                        fontsize=11, pad=10,
                    )
                    ax3a.set_xlabel("Hour")
                    ax3a.set_ylabel("PLN/MWh")
                    ax3b.set_ylabel("Δ GER−F1 (PLN/MWh)", color="#555")
                    ax3a.set_xticks(range(1, 25))
                    ax3a.grid(True, alpha=0.2)
                    ax3a.legend(loc="upper left", fontsize=9)
                    fig3.tight_layout()
                    st.pyplot(fig3)
                    plt.close(fig3)

                    st.caption("Green = GER most above Polish model (hours to watch for import) | Red = opposite")




def render_performance():
        import duckdb as _duckdb_mp

        st.title("Model Performance")
        st.caption("Directional accuracy of forecast models for Fixing1 vs Fixing2 arbitrage")

        if not os.path.exists(FORECAST_DB_PATH):
            st.warning(f"DuckDB not found: `{FORECAST_DB_PATH}`")
            st.stop()

        # ── Controls ──────────────────────────────────────────────────────────────
        _mp_c1, _mp_c2 = st.columns([1, 3])
        with _mp_c1:
            _mp_lookback = st.selectbox(
                "Lookback (delivery days)", [3, 5, 7, 14], index=0, key="mp_lookback"
            )

        # ── Load forecasts from DuckDB ────────────────────────────────────────────
        try:
            _mp_con = _duckdb_mp.connect(FORECAST_DB_PATH, read_only=True)
            _mp_fc_raw = _mp_con.execute("""
                SELECT
                    CAST(fp.ts AS DATE)                          AS delivery_date,
                    CAST(EXTRACT(HOUR FROM fp.ts) + 1 AS INTEGER) AS H,
                    fp.model,
                    fp.price_pln_mwh                             AS forecast_F2,
                    r.snapshot_ts
                FROM forecast_prices fp
                JOIN runs r ON fp.run_id = r.run_id
                WHERE r.fixing_type = 'F2'
            """).df()
            _mp_con.close()
        except Exception as _mp_err:
            st.error(f"DuckDB error: {_mp_err}")
            st.stop()

        if _mp_fc_raw.empty:
            st.info("No forecast data in database yet.")
            st.stop()

        # Keep latest run per delivery_date × H × model
        _mp_fc_raw["delivery_date"] = pd.to_datetime(_mp_fc_raw["delivery_date"]).dt.date
        _mp_fc = (
            _mp_fc_raw
            .sort_values("snapshot_ts", ascending=False)
            .drop_duplicates(subset=["delivery_date", "H", "model"])
            [["delivery_date", "H", "model", "forecast_F2"]]
        )

        # ── Load actual F1/F2 from FixingPricesH.parquet ──────────────────────────
        _mp_fix = load_prices()[["delivery_date", "H", "f1_price_PLN", "sdac_price_PLN"]].copy()
        _mp_fix["delivery_date"] = pd.to_datetime(_mp_fix["delivery_date"]).dt.date

        # ── Apply lookback filter ─────────────────────────────────────────────────
        _mp_cutoff = date.today() - timedelta(days=_mp_lookback)
        _mp_fix = _mp_fix[
            (_mp_fix["delivery_date"] >= _mp_cutoff) &
            (_mp_fix["delivery_date"] < date.today())
        ]

        # ── Join ──────────────────────────────────────────────────────────────────
        _mp_perf = _mp_fc.merge(_mp_fix, on=["delivery_date", "H"], how="inner")

        if _mp_perf.empty:
            st.info("No overlapping data between forecasts and actual fixings for this period.")
            st.stop()

        # ── Build df_perf ─────────────────────────────────────────────────────────
        _mp_perf = _mp_perf.rename(columns={
            "f1_price_PLN":   "actual_F1",
            "sdac_price_PLN": "actual_F2",
        })
        _mp_perf["forecast_spread"] = _mp_perf["forecast_F2"] - _mp_perf["actual_F1"]
        _mp_perf["actual_spread"]   = _mp_perf["actual_F2"]   - _mp_perf["actual_F1"]
        _mp_perf["abs_spread"]      = _mp_perf["actual_spread"].abs()

        def _mp_dir(v):
            if v > 0:  return "LONG"
            if v < 0:  return "SHORT"
            return "FLAT"

        _mp_perf["signal"]           = _mp_perf["forecast_spread"].apply(_mp_dir)
        _mp_perf["actual_direction"] = _mp_perf["actual_spread"].apply(_mp_dir)
        _mp_perf["hit"]              = (_mp_perf["signal"] == _mp_perf["actual_direction"]).astype(int)
        _mp_perf["position"]         = _mp_perf["signal"].map({"LONG": 1, "SHORT": -1, "FLAT": 0})
        _mp_perf["pnl"]              = _mp_perf["position"] * _mp_perf["actual_spread"]

        # ── Info bar ──────────────────────────────────────────────────────────────
        _mp_d_min = _mp_perf["delivery_date"].min()
        _mp_d_max = _mp_perf["delivery_date"].max()
        _mp_days  = _mp_perf["delivery_date"].nunique()
        st.info(
            f"Period: **{_mp_d_min}** → **{_mp_d_max}**  ·  "
            f"**{_mp_days}** delivery days  ·  "
            f"**{len(_mp_perf)}** observations"
        )

        # ── Model ranking ─────────────────────────────────────────────────────────
        st.subheader("Model ranking")

        _mp_rank = (
            _mp_perf.groupby("model")
            .agg(
                Observations=("hit", "count"),
                Hit_ratio=("hit", "mean"),
                Total_PnL=("pnl", "sum"),
                Avg_PnL=("pnl", "mean"),
                Avg_abs_spread=("abs_spread", "mean"),
            )
            .reset_index()
            .sort_values(["Total_PnL", "Hit_ratio"], ascending=False)
            .reset_index(drop=True)
        )
        _mp_rank.insert(0, "Rank", range(1, len(_mp_rank) + 1))
        _mp_rank["Hit_ratio"]      = (_mp_rank["Hit_ratio"] * 100).round(2)
        _mp_rank["Total_PnL"]      = _mp_rank["Total_PnL"].round(2)
        _mp_rank["Avg_PnL"]        = _mp_rank["Avg_PnL"].round(2)
        _mp_rank["Avg_abs_spread"] = _mp_rank["Avg_abs_spread"].round(2)
        _mp_rank.columns           = ["#", "Model", "Obs", "Hit ratio %", "Total PnL", "Avg PnL", "Avg |spread|"]

        def _mp_color_rank(df):
            styles = pd.DataFrame("", index=df.index, columns=df.columns)
            _center = "text-align: center"
            for col in df.columns:
                styles[col] = _center
            for i, row in df.iterrows():
                clr = "#2dc653" if row["Total PnL"] > 0 else "#e63946"
                styles.loc[i, "Total PnL"] = f"{_center}; color:{clr}; font-weight:700"
                hr = row["Hit ratio %"]
                if hr >= 60:
                    styles.loc[i, "Hit ratio %"] = f"{_center}; color:#2dc653; font-weight:700"
                elif hr >= 50:
                    styles.loc[i, "Hit ratio %"] = f"{_center}; color:#f39c12; font-weight:600"
                else:
                    styles.loc[i, "Hit ratio %"] = f"{_center}; color:#e63946"
            return styles

        st.dataframe(
            _mp_rank.style.apply(_mp_color_rank, axis=None).format({
                "Hit ratio %": "{:.2f}",
                "Total PnL":   "{:.2f}",
                "Avg PnL":     "{:.2f}",
                "Avg |spread|": "{:.2f}",
            }),
            use_container_width=False,
            width=620,
            hide_index=True,
        )

        # ── Hourly ranking ────────────────────────────────────────────────────────
        st.subheader("Hourly ranking — best model per hour")

        _mp_hourly_all = (
            _mp_perf.groupby(["H", "model"])
            .agg(
                obs=("hit", "count"),
                hit_ratio=("hit", "mean"),
                total_pnl=("pnl", "sum"),
            )
            .reset_index()
        )

        _mp_best_h = (
            _mp_hourly_all
            .sort_values(["H", "hit_ratio", "total_pnl"], ascending=[True, False, False])
            .drop_duplicates(subset=["H"])
            .reset_index(drop=True)
        )
        _mp_best_h["hit_ratio"] = (_mp_best_h["hit_ratio"] * 100).round(2)
        _mp_best_h["total_pnl"] = _mp_best_h["total_pnl"].round(2)
        _mp_best_h.columns      = ["Hour", "Best model", "Obs", "Hit ratio %", "Total PnL"]

        def _mp_color_h(df):
            styles = pd.DataFrame("", index=df.index, columns=df.columns)
            _center = "text-align: center"
            for col in df.columns:
                styles[col] = _center
            for i, row in df.iterrows():
                clr = "#2dc653" if row["Total PnL"] > 0 else "#e63946"
                styles.loc[i, "Total PnL"] = f"{_center}; color:{clr}; font-weight:700"
                if row["Hit ratio %"] >= 60:
                    styles.loc[i, "Hit ratio %"] = f"{_center}; color:#2dc653; font-weight:700"
                elif row["Hit ratio %"] >= 50:
                    styles.loc[i, "Hit ratio %"] = f"{_center}; color:#f39c12; font-weight:600"
                else:
                    styles.loc[i, "Hit ratio %"] = f"{_center}; color:#e63946"
                model_colors = {"SGB": "#8e44ad", "RF": "#2980b9", "DT": "#e67e22", "SAR": "#7f8c8d"}
                clr_m = model_colors.get(row["Best model"], "#333")
                styles.loc[i, "Best model"] = f"{_center}; color:{clr_m}; font-weight:700"
            return styles

        st.dataframe(
            _mp_best_h.style.apply(_mp_color_h, axis=None).format({
                "Hit ratio %": "{:.2f}",
                "Total PnL":   "{:.2f}",
            }),
            use_container_width=False,
            width=480,
            hide_index=True,
            height=650,
        )

        # ── Full hourly detail (collapsed) ────────────────────────────────────────
        with st.expander("All models × hour detail"):
            _mp_hourly_all["hit_ratio"] = (_mp_hourly_all["hit_ratio"] * 100).round(2)
            _mp_hourly_all["total_pnl"] = _mp_hourly_all["total_pnl"].round(2)
            _mp_hourly_all.columns      = ["Hour", "Model", "Obs", "Hit ratio %", "Total PnL"]
            st.dataframe(
                _mp_hourly_all.sort_values(["Hour", "Total PnL"], ascending=[True, False])
                .style.format({"Hit ratio %": "{:.2f}", "Total PnL": "{:.2f}"}),
                use_container_width=False,
                width=480,
                hide_index=True,
            )

        # ── Field descriptions ────────────────────────────────────────────────────
        st.divider()
        st.markdown("""
    **Field descriptions**

    | Field | Description |
    |---|---|
    | **Hit ratio %** | % of hours where the model correctly predicted the direction of spread F2−F1 (LONG or SHORT). 50% = random guess. |
    | **Obs** | Number of hourly observations included in the analysis (delivery days × 24 hours). |
    | **Total PnL** | Simulated cumulative profit/loss for 1 MW position over the lookback period (PLN). LONG = +1 MW, SHORT = −1 MW, FLAT = 0. |
    | **Avg PnL** | Average PnL per hour observation (Total PnL / Obs). |
    | **Avg |spread|** | Average absolute value of actual spread F2−F1 (PLN/MWh). Indicates how large the market moves were — higher = more opportunity. |
    """)

        # ── Tomorrow's signal ──────────────────────────────────────────────────────
        st.divider()
        st.subheader("Tomorrow's signal")
        _mp_tomorrow = date.today() + timedelta(days=1)
        st.caption(
            f"Delivery date: **{_mp_tomorrow}** — position per hour using best model from above ranking"
        )

        try:
            _mp_con2 = _duckdb_mp.connect(FORECAST_DB_PATH, read_only=True)

            _mp_f1_run = _mp_con2.execute("""
                SELECT run_id, CAST(snapshot_ts AS VARCHAR) AS snap
                FROM runs
                WHERE fixing_type = 'F1'
                  AND CAST(forecast_start AS DATE) <= ?
                  AND CAST(forecast_end   AS DATE) >= ?
                ORDER BY snapshot_ts DESC
                LIMIT 1
            """, [_mp_tomorrow, _mp_tomorrow]).df()

            _mp_f2_run = _mp_con2.execute("""
                SELECT run_id, CAST(snapshot_ts AS VARCHAR) AS snap
                FROM runs
                WHERE fixing_type = 'F2'
                  AND CAST(forecast_start AS DATE) <= ?
                  AND CAST(forecast_end   AS DATE) >= ?
                ORDER BY snapshot_ts DESC
                LIMIT 1
            """, [_mp_tomorrow, _mp_tomorrow]).df()

            if _mp_f1_run.empty or _mp_f2_run.empty:
                _mp_missing = []
                if _mp_f1_run.empty: _mp_missing.append("F1")
                if _mp_f2_run.empty: _mp_missing.append("F2")
                st.info(
                    f"No {' and '.join(_mp_missing)} forecast available for {_mp_tomorrow}. "
                    f"Run the missing forecast(s) on the Forecast page first."
                )
            else:
                _mp_f1_rid  = _mp_f1_run.iloc[0]["run_id"]
                _mp_f1_snap = _mp_f1_run.iloc[0]["snap"]
                _mp_f2_rid  = _mp_f2_run.iloc[0]["run_id"]
                _mp_f2_snap = _mp_f2_run.iloc[0]["snap"]

                _mp_f1_prices = _mp_con2.execute("""
                    SELECT
                        CAST(EXTRACT(HOUR FROM ts) + 1 AS INTEGER) AS H,
                        model,
                        price_pln_mwh AS fc_f1
                    FROM forecast_prices
                    WHERE run_id = ?
                """, [_mp_f1_rid]).df()

                _mp_f2_prices = _mp_con2.execute("""
                    SELECT
                        CAST(EXTRACT(HOUR FROM ts) + 1 AS INTEGER) AS H,
                        model,
                        price_pln_mwh AS fc_f2
                    FROM forecast_prices
                    WHERE run_id = ?
                """, [_mp_f2_rid]).df()

                # best model lookup: H → {model, hit_ratio}
                _mp_bm_map = (
                    _mp_best_h[["Hour", "Best model", "Hit ratio %"]]
                    .set_index("Hour")
                    .to_dict("index")
                )

                _mp_sig_rows = []
                for _h in range(1, 25):
                    _bm_info = _mp_bm_map.get(_h, {})
                    _bm      = _bm_info.get("Best model", "N/A")
                    _bm_hr   = _bm_info.get("Hit ratio %", None)

                    _f1r = _mp_f1_prices[(_mp_f1_prices["H"] == _h) & (_mp_f1_prices["model"] == _bm)]
                    _f2r = _mp_f2_prices[(_mp_f2_prices["H"] == _h) & (_mp_f2_prices["model"] == _bm)]

                    _f1 = float(_f1r.iloc[0]["fc_f1"]) if not _f1r.empty else None
                    _f2 = float(_f2r.iloc[0]["fc_f2"]) if not _f2r.empty else None

                    if _f1 is not None and _f2 is not None:
                        _sp  = _f2 - _f1
                        _pos = "LONG" if _sp > 0 else ("SHORT" if _sp < 0 else "FLAT")
                    else:
                        _sp  = None
                        _pos = "N/A"

                    _mp_sig_rows.append({
                        "H":           _h,
                        "Best model":  _bm,
                        "Hit ratio %": _bm_hr,
                        "F1 Forecast": round(_f1, 2) if _f1 is not None else None,
                        "F2 Forecast": round(_f2, 2) if _f2 is not None else None,
                        "Exp. Spread": round(_sp, 2) if _sp is not None else None,
                        "Position":    _pos,
                        "Run ID F1":   _mp_f1_rid,
                        "Run ID F2":   _mp_f2_rid,
                    })

                _mp_sig_df = pd.DataFrame(_mp_sig_rows)

                st.caption(f"F1 · run `{_mp_f1_rid}` · snapshot {_mp_f1_snap}")
                st.caption(f"F2 · run `{_mp_f2_rid}` · snapshot {_mp_f2_snap}")

                _mp_mc = {"SGB": "#8e44ad", "RF": "#2980b9", "DT": "#e67e22", "SAR": "#7f8c8d"}

                def _mp_color_sig(df):
                    styles = pd.DataFrame("", index=df.index, columns=df.columns)
                    _c = "text-align: center"
                    for col in df.columns:
                        styles[col] = _c
                    for i, row in df.iterrows():
                        styles.loc[i, "Best model"] = (
                            f"{_c}; color:{_mp_mc.get(row['Best model'], '#333')}; font-weight:700"
                        )
                        if row["Position"] == "LONG":
                            styles.loc[i, "Position"] = f"{_c}; color:#2dc653; font-weight:700"
                        elif row["Position"] == "SHORT":
                            styles.loc[i, "Position"] = f"{_c}; color:#e63946; font-weight:700"
                        if pd.notna(row["Exp. Spread"]):
                            _sc = "#2dc653" if row["Exp. Spread"] > 0 else "#e63946"
                            styles.loc[i, "Exp. Spread"] = f"{_c}; color:{_sc}"
                    return styles

                st.dataframe(
                    _mp_sig_df.style.apply(_mp_color_sig, axis=None).format({
                        "Hit ratio %": "{:.2f}",
                        "F1 Forecast": "{:.2f}",
                        "F2 Forecast": "{:.2f}",
                        "Exp. Spread": "{:.2f}",
                    }, na_rep="—"),
                    use_container_width=True,
                    hide_index=True,
                    height=700,
                )

            _mp_con2.close()

        except Exception as _mp_sig_err:
            st.error(f"Could not load tomorrow's signal: {_mp_sig_err}")


# ══════════════════════════════════════════════════════════════════════════════
#  SPREAD FORECAST — dedicated model for F1 - F2 (instead of subtracting two
#  independently-trained price models)
# ══════════════════════════════════════════════════════════════════════════════

def render_spread_forecast():
    import importlib.util as _ilu_sp

    st.title("Spread Forecast (F1 − F2)")
    st.caption(
        "Dedicated model — predicts the F1/SDAC spread directly as a single target, "
        "instead of subtracting two independently-forecast price models (which compounds "
        "their individual errors)."
    )

    _sp_root = APP_DIR

    def _load_sp_mod():
        _spec = _ilu_sp.spec_from_file_location(
            "forecast_spread", os.path.join(_sp_root, "procedures", "forecast_spread.py")
        )
        _mod = _ilu_sp.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        return _mod

    if st.button("▶ Run Spread Forecast", key="sp_run", type="primary"):
        st.divider()
        st.subheader("Running spread forecast")
        _sp_log_box = st.empty()
        _sp_lines = []

        def _sp_log(msg):
            _sp_lines.append(str(msg))
            _sp_log_box.code("\n".join(_sp_lines), language="bash")

        _sp_mod = _load_sp_mod()
        _sp_result = _sp_mod.run_pipeline(db_path=FORECAST_DB_PATH, app_dir=_sp_root, log=_sp_log)

        if _sp_result.get("status") == "ok":
            st.success(_sp_result["message"])
        else:
            st.error(_sp_result.get("message", "Pipeline error."))

    # ── Last runs ─────────────────────────────────────────────────────────────
    st.divider()
    st.subheader("Last runs")
    try:
        import duckdb as _ddb_sp
        if os.path.exists(FORECAST_DB_PATH):
            _sp_con = _ddb_sp.connect(FORECAST_DB_PATH, read_only=True)
            try:
                _sp_runs = _sp_con.execute("""
                    SELECT run_id,
                           CAST(snapshot_ts AS VARCHAR) AS run_time,
                           CAST(forecast_start AS VARCHAR) AS fc_start,
                           CAST(forecast_end   AS VARCHAR) AS fc_end,
                           CAST(last_spread_date AS VARCHAR) AS "Last Spread Date"
                    FROM spread_runs
                    ORDER BY snapshot_ts DESC
                    LIMIT 20
                """).df()
            except Exception:
                _sp_runs = pd.DataFrame()
            _sp_con.close()
            if _sp_runs.empty:
                st.info("No spread forecast runs yet.")
            else:
                st.dataframe(_sp_runs, use_container_width=True, hide_index=True)
        else:
            st.info(f"Forecast DB not found at `{FORECAST_DB_PATH}`.")
    except Exception as _sp_e:
        st.warning(f"Could not load run history: {_sp_e}")

    # ── Data readiness ────────────────────────────────────────────────────────
    st.divider()
    st.subheader("Data readiness")

    def _sp_last_date(path, date_col, value_col=None):
        """Last date with non-null data. If value_col is given, checks THAT
        column specifically (e.g. f1_price_PLN vs sdac_price_PLN can have
        different freshness even though they share the same date column)."""
        try:
            if not os.path.exists(path):
                return None, "file missing"
            _cols = [date_col] if value_col is None else [date_col, value_col]
            _df = pd.read_parquet(path, columns=_cols)
            if value_col is not None:
                _df = _df[_df[value_col].notna()]
            if _df.empty:
                return None, "no data"
            _d = pd.to_datetime(_df[date_col]).max()
            return _d.date(), str(_d.date())
        except Exception as _ex:
            return None, f"error: {_ex}"

    _today_sp = date.today()

    _sp_sources = [
        ("Fixing1 (F1) last date",  PARQUET_PATH, "delivery_date", "f1_price_PLN",
         "Spread target = F1 − F2"),
        ("Fixing2 (SDAC) last date", PARQUET_PATH, "delivery_date", "sdac_price_PLN",
         "Spread target = F1 − F2 (SDAC history only starts 2025-12-05)"),
        ("DE prices last date (Electricity Maps)", DE_PRICES_PATH, "business_date", "price_eur",
         "DE_spot_PLN feature (realized — NaN for future days)"),
        ("CEN last date (RB)", RB_H_PATH, "delivery_date", "cen_cost",
         "CEN_lag24 feature (realized — NaN beyond day 1)"),
    ]
    _rh1, _rh2, _rh3, _rh4 = st.columns([2, 1.6, 1, 2.7])
    _rh1.markdown("**Source**"); _rh2.markdown("**Last date**")
    _rh3.markdown("**Status**"); _rh4.markdown("**Role**")
    st.divider()
    for _src_name, _src_path, _src_col, _src_val, _src_role in _sp_sources:
        _last_d, _last_str = _sp_last_date(_src_path, _src_col, _src_val)
        _is_ok = (_last_d is not None) and (_last_d >= _today_sp - timedelta(days=1))
        _icon  = "✅" if _is_ok else ("⚠️" if _last_d else "❌")
        _c1, _c2, _c3, _c4 = st.columns([2, 1.6, 1, 2.7])
        _c1.markdown(_src_name); _c2.markdown(f"`{_last_str}`")
        _c3.markdown(_icon)
        _c4.markdown(f"<small style='color:#888'>{_src_role}</small>", unsafe_allow_html=True)

    try:
        _pk5_df = pd.read_parquet(PK5_PATH, columns=["publication_ts"])
        _pk5_ts = pd.to_datetime(_pk5_df["publication_ts"]).max()
        _pk5_ok = _pk5_ts.date() >= _today_sp - timedelta(days=1)
        _pk5_icon, _pk5_str = ("✅" if _pk5_ok else "⚠️"), _pk5_ts.strftime("%Y-%m-%d %H:%M")
    except Exception:
        _pk5_icon, _pk5_str = "❌", "error"
    _pc1, _pc2, _pc3, _pc4 = st.columns([2, 1.6, 1, 2.7])
    _pc1.markdown("PK5 last update"); _pc2.markdown(f"`{_pk5_str}`")
    _pc3.markdown(_pk5_icon)
    _pc4.markdown("<small style='color:#888'>Core demand/RES/WRM features</small>", unsafe_allow_html=True)

    with st.expander("Features used", expanded=True):
        st.markdown("""
**Target**: `Fixing1 - Fixing2` (F1 minus SDAC), modeled directly as one variable.

| Feature | Source | Why |
|---|---|---|
| RL, demand, PV, wind forecast | PK5 | core supply/demand drivers (same as F1/F2 models) |
| Wymiana systemowa (exchange) | PK5 | cross-border flows — directly relevant to RDN-vs-SDAC basis |
| Niedyspozycyjność sieci | PK5 | transmission constraints / local congestion |
| Nadwyżka nad WRM | PK5 (col. 6) | system tightness / scarcity risk |
| DE_spot_PLN | DE prices (Electricity Maps, realized) + energy-charts 72H forecast | SDAC couples PL with DE — direct exposure. Training uses the realized price (de_prices.parquet — updated daily, not the netztransparenz.de source which currently lags by weeks); forecast days use the **real energy-charts 72H forecast** where it overlaps (~first 1-1.5 days of the horizon), then falls back to historical median. |
| CEN_lag24 | RB prices | yesterday's balancing-market stress as a leading indicator. **Only truly known for forecast day 1** (tomorrow); falls back to historical median for later days. |
| wind_share, pv_share | derived | RES penetration relative to demand |
| hour, weekday, month, is_weekend, is_holiday | calendar | liquidity/behavior differs by day type (PL public holidays) |
| spread_lag24, spread_lag168, spread_roll24_std | derived | spread autocorrelation / mean-reversion / volatility regime |

**Models**: DecisionTree, RandomForest, XGBoost, SARIMAX — same 4-model ensemble as the
F1/F2 forecast, for direct comparability against the "naive subtraction" baseline shown
in Plotting → Arbitrage.

**Known limitation**: CEN_lag24 is a *realized* value, only known for forecast day 1 —
it falls back to historical median from day 2 onward. DE_spot_PLN now gets a real
forward-looking value for roughly the first 1-1.5 days (from the 72H DE forecast,
generated daily at 07:10), then also falls back to historical median for the rest of
the horizon. Expect the model to lean more on PK5-based and calendar features for the
back end of the 14-day window.
        """)


def render_spread_plotting():
    import matplotlib.pyplot as plt
    import numpy as _np
    import duckdb as _ddb_sp2

    st.title("Spread Forecast — Plotting")

    if not os.path.exists(FORECAST_DB_PATH):
        st.error(f"Forecast DB not found: `{FORECAST_DB_PATH}`")
        st.stop()

    try:
        _spcon = _ddb_sp2.connect(FORECAST_DB_PATH, read_only=True)
    except Exception as _e:
        st.error(f"Cannot connect to forecast DB: {_e}")
        st.stop()

    try:
        _sp_runs = _spcon.execute("""
            SELECT run_id, CAST(snapshot_ts AS TIMESTAMP) AS snapshot_ts,
                   CAST(forecast_start AS DATE) AS forecast_start,
                   CAST(forecast_end AS DATE) AS forecast_end
            FROM spread_runs ORDER BY snapshot_ts DESC
        """).df()
    except Exception:
        _sp_runs = pd.DataFrame()

    if _sp_runs.empty:
        st.info("No spread forecast runs yet. Run it from the SpreadForecast page first.")
        _spcon.close()
        st.stop()

    _sp_latest_run = _sp_runs.iloc[0]
    _sp_run_id     = _sp_latest_run["run_id"]
    _sp_snap       = _sp_latest_run["snapshot_ts"]

    _sp_dates = sorted(
        pd.Timestamp(d).date()
        for d in _spcon.execute(f"""
            SELECT DISTINCT CAST(ts AS DATE) AS d
            FROM spread_forecast_prices WHERE run_id = '{_sp_run_id}'
            ORDER BY d
        """).df()["d"].tolist()
    )
    if not _sp_dates:
        st.info("No spread forecast data yet.")
        _spcon.close()
        st.stop()

    # ── Date navigator ────────────────────────────────────────────────────────
    _sp_tomorrow = date.today() + timedelta(days=1)
    if "spp_date" not in st.session_state or st.session_state.spp_date not in _sp_dates:
        st.session_state.spp_date = _sp_tomorrow if _sp_tomorrow in _sp_dates else _sp_dates[0]

    _dnav = st.columns([0.07, 0.20, 0.07, 0.66])
    with _dnav[0]:
        _go_prev = st.button("◀", use_container_width=True, key="spp_prev")
    with _dnav[1]:
        _picked = st.date_input("date", value=st.session_state.spp_date,
                                min_value=_sp_dates[0], max_value=_sp_dates[-1],
                                label_visibility="collapsed", key="spp_date_inp")
    with _dnav[2]:
        _go_next = st.button("▶", use_container_width=True, key="spp_next")

    _picked = _picked if isinstance(_picked, type(_sp_dates[0])) else pd.Timestamp(_picked).date()

    _cur_i = _sp_dates.index(st.session_state.spp_date)
    if _go_prev and _cur_i > 0:
        st.session_state.spp_date = _sp_dates[_cur_i - 1]; st.rerun()
    elif _go_next and _cur_i < len(_sp_dates) - 1:
        st.session_state.spp_date = _sp_dates[_cur_i + 1]; st.rerun()
    elif _picked != st.session_state.spp_date:
        st.session_state.spp_date = _picked; st.rerun()

    _sel_date = st.session_state.spp_date

    _MODEL_COLORS = {"DT": "#2196F3", "RF": "#4CAF50", "XGB": "#FF9800", "SARIMAX": "#9C27B0"}

    _sp_day = _spcon.execute(f"""
        SELECT CAST(EXTRACT(HOUR FROM ts) + 1 AS INTEGER) AS H, model, spread_pln_mwh
        FROM spread_forecast_prices
        WHERE run_id = '{_sp_run_id}' AND CAST(ts AS DATE) = '{_sel_date}'
        ORDER BY H, model
    """).df()

    def _hourly_generic(df, model, col):
        if model == "Average":
            return df.groupby("H")[col].mean().reset_index()
        return df[df["model"] == model][["H", col]].sort_values("H").reset_index(drop=True)

    _tab1, _tab2 = st.tabs(["Spread model", "vs. naive F1−F2 subtraction"])

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # TAB 1 — Spread model (hourly, all 4 models + average)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    with _tab1:
        if _sp_day.empty:
            st.info(f"No spread forecast for {_sel_date}.")
        else:
            _models = sorted(_sp_day["model"].unique())
            _cb_cols = st.columns(len(_models) + 1)
            _show = {m: _cb_cols[i].checkbox(m, value=True, key=f"spp_cb_{m}")
                     for i, m in enumerate(_models)}
            _show_avg = _cb_cols[-1].checkbox("Average", value=True, key="spp_cb_avg")
            _show_market = st.checkbox("Show market spread (realized F1−F2)",
                                       value=True, key="spp_show_market")

            fig, ax = plt.subplots(figsize=(13, 5))
            fig.patch.set_facecolor("white"); ax.set_facecolor("white")
            ax.axhline(0, color="#999", linewidth=0.8, linestyle="--")

            if _show_market:
                _real_h = load_prices()
                _real_day = _real_h[_real_h["delivery_date"] == _sel_date].copy()
                _real_day["realized_spread"] = (
                    _real_day["f1_price_PLN"] - _real_day["sdac_price_PLN"]
                )
                _real_day = _real_day.dropna(subset=["realized_spread"])
                if not _real_day.empty:
                    ax.bar(_real_day["H"], _real_day["realized_spread"],
                           color="#90A4AE", alpha=0.5, width=0.6, zorder=1,
                           label=f"Market (realized)  avg: {_real_day['realized_spread'].mean():.0f}")
                else:
                    st.caption(f"No realized F1/SDAC spread yet for {_sel_date} — not settled.")

            _all_vals = []
            for m in _models:
                if not _show[m]:
                    continue
                sub = _hourly_generic(_sp_day, m, "spread_pln_mwh")
                ax.plot(sub["H"], sub["spread_pln_mwh"], color=_MODEL_COLORS.get(m, "#666"),
                        linewidth=2, zorder=2, label=f"{m}  avg: {sub['spread_pln_mwh'].mean():.0f}")
                _all_vals.append(sub["spread_pln_mwh"].values)

            if _show_avg and _all_vals:
                _mean_v = _np.mean(_np.vstack(_all_vals), axis=0)
                _h_axis = _hourly_generic(_sp_day, _models[0], "spread_pln_mwh")["H"]
                ax.plot(_h_axis, _mean_v, color="black", linewidth=2.5, linestyle="--", zorder=3,
                        label=f"Average  avg: {_mean_v.mean():.0f}")

            ax.set_title(f"Spread forecast (F1−F2) — {_sel_date}  |  run: {str(_sp_snap)[:16]}",
                        fontsize=11, pad=10)
            ax.set_xlabel("Hour"); ax.set_ylabel("PLN/MWh")
            ax.set_xticks(range(1, 25)); ax.grid(True, alpha=0.2)
            ax.legend(loc="upper left", fontsize=9)
            fig.tight_layout()
            st.pyplot(fig); plt.close(fig)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # TAB 2 — Dedicated spread model vs naive F1-F2 subtraction
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    with _tab2:
        try:
            _naive_runs = _spcon.execute("""
                SELECT run_id, fixing_type, CAST(snapshot_ts AS TIMESTAMP) AS snapshot_ts
                FROM runs ORDER BY snapshot_ts DESC
            """).df()
        except Exception:
            _naive_runs = pd.DataFrame()

        if _naive_runs.empty or not {"F1", "F2"}.issubset(set(_naive_runs["fixing_type"])):
            st.warning("Both F1 and F2 runs are required for the naive comparison. "
                      "Run them from the Forecast page first.")
        elif _sp_day.empty:
            st.info(f"No spread forecast for {_sel_date}.")
        else:
            _naive_latest = _naive_runs.drop_duplicates("fixing_type", keep="first").set_index("fixing_type")
            _model_sel = st.selectbox("Model (for both)",
                                      sorted(_sp_day["model"].unique()) + ["Average"],
                                      key="spp_naive_model")

            def _load_fc_day(run_id, sel_date):
                return _spcon.execute(f"""
                    SELECT CAST(EXTRACT(HOUR FROM ts) + 1 AS INTEGER) AS H, model, price_pln_mwh
                    FROM forecast_prices
                    WHERE run_id = '{run_id}' AND CAST(ts AS DATE) = '{sel_date}'
                    ORDER BY H, model
                """).df()

            _f1_day = _load_fc_day(_naive_latest.loc["F1", "run_id"], _sel_date)
            _f2_day = _load_fc_day(_naive_latest.loc["F2", "run_id"], _sel_date)

            if _f1_day.empty or _f2_day.empty:
                st.info(f"Missing F1/F2 forecast data for {_sel_date} — run both on the Forecast page first.")
            else:
                _f1h = _hourly_generic(_f1_day, _model_sel, "price_pln_mwh")
                _f2h = _hourly_generic(_f2_day, _model_sel, "price_pln_mwh")
                _sph = _hourly_generic(_sp_day, _model_sel, "spread_pln_mwh")

                _mrg = _f1h.merge(_f2h, on="H", suffixes=("_f1", "_f2")).merge(_sph, on="H")
                _mrg["naive_spread"] = _mrg["price_pln_mwh_f1"] - _mrg["price_pln_mwh_f2"]

                fig2, ax2 = plt.subplots(figsize=(13, 5))
                fig2.patch.set_facecolor("white"); ax2.set_facecolor("white")
                ax2.axhline(0, color="#999", linewidth=0.8, linestyle="--")
                ax2.plot(_mrg["H"], _mrg["naive_spread"], color="#9E9E9E", linewidth=2,
                         linestyle=":", label=f"Naive F1−F2  avg: {_mrg['naive_spread'].mean():.0f}")
                ax2.plot(_mrg["H"], _mrg["spread_pln_mwh"], color="#D32F2F", linewidth=2.5,
                         label=f"Dedicated spread model  avg: {_mrg['spread_pln_mwh'].mean():.0f}")
                ax2.set_title(f"Dedicated vs naive spread — {_model_sel}  |  {_sel_date}", fontsize=11, pad=10)
                ax2.set_xlabel("Hour"); ax2.set_ylabel("PLN/MWh")
                ax2.set_xticks(range(1, 25)); ax2.grid(True, alpha=0.2)
                ax2.legend(loc="upper left", fontsize=9)
                fig2.tight_layout()
                st.pyplot(fig2); plt.close(fig2)
                st.caption(
                    "Compares the dedicated spread model against subtracting two "
                    "independently-forecast F1/F2 prices (the old Plotting → Arbitrage approach)."
                )

    _spcon.close()


# ══════════════════════════════════════════════════════════════════════════════
#  DE FORECAST — compare the two independent German day-ahead forecasts
# ══════════════════════════════════════════════════════════════════════════════

def _render_de_accuracy(hist: pd.DataFrame):
    """On-demand accuracy report — compare D+1 forecasts vs. actual DE prices."""
    if hist.empty:
        st.info("Brak historii prognoz do analizy.")
        return

    _window = st.radio(
        "Okres analizy",
        ["1 dzień", "3 dni", "7 dni", "30 dni"],
        horizontal=True,
        key="def_acc_window",
    )
    _n = {"1 dzień": 1, "3 dni": 3, "7 dni": 7, "30 dni": 30}[_window]

    _today = date.today()
    _cutoff = _today - timedelta(days=_n)

    # Only D+1 captures: forecast_date = capture_date + 1 day
    _h = hist.copy()
    _h["_fdt"] = pd.to_datetime(_h["forecast_date"])
    _h["_cdt"] = pd.to_datetime(_h["capture_date"])
    _h_d1 = _h[
        (_h["forecast_date"] >= _cutoff) &
        (_h["forecast_date"] < _today) &
        ((_h["_fdt"] - _h["_cdt"]).dt.days == 1)
    ].drop(columns=["_fdt", "_cdt"])

    if _h_d1.empty:
        st.info("Brak danych prognoz D+1 w wybranym okresie.")
        return

    _actuals = load_de_prices()
    if _actuals.empty or "price_eur" not in _actuals.columns:
        st.warning("Brak rzeczywistych cen DE (de_prices.parquet).")
        return

    _act = _actuals[["business_date", "hour", "price_eur"]].rename(
        columns={"business_date": "forecast_date", "price_eur": "actual_eur"}
    )
    _merged = _h_d1.merge(_act, on=["forecast_date", "hour"], how="inner")

    if _merged.empty:
        st.info("Brak pokrycia między prognozami D+1 a cenami rzeczywistymi.")
        return

    _src_labels = {"energy_charts": "energy-charts", "energyforecast_de": "energyforecast.de"}
    _results = []
    for _src in sorted(_merged["source"].unique()):
        _s = _merged[_merged["source"] == _src]
        _err = _s["price_eur"] - _s["actual_eur"]
        _results.append({
            "Źródło":          _src_labels.get(_src, _src),
            "MAE (EUR/MWh)":   round(abs(_err).mean(), 2),
            "RMSE (EUR/MWh)":  round((_err ** 2).mean() ** 0.5, 2),
            "Bias (EUR/MWh)":  round(_err.mean(), 2),
            "Dni":             _s["forecast_date"].nunique(),
        })

    _df_res = pd.DataFrame(_results).sort_values("MAE (EUR/MWh)").reset_index(drop=True)
    st.dataframe(_df_res, hide_index=True, use_container_width=True)

    if len(_df_res) > 1:
        _winner = _df_res.iloc[0]["Źródło"]
        _mae_w  = _df_res.iloc[0]["MAE (EUR/MWh)"]
        _mae_l  = _df_res.iloc[1]["MAE (EUR/MWh)"]
        st.caption(f"Lepsza prognoza (niższe MAE): **{_winner}** — {_mae_w:.2f} vs {_mae_l:.2f} EUR/MWh")


def render_de_forecast():
    st.title("DE Forecast")

    # ── Load history ───────────────────────────────────────────────────────────
    _hist = pd.DataFrame()
    if os.path.exists(DE_FORE_HIST_PATH):
        _hist = pd.read_parquet(DE_FORE_HIST_PATH)
        _hist["capture_date"]  = pd.to_datetime(_hist["capture_date"]).dt.date
        _hist["forecast_date"] = pd.to_datetime(_hist["forecast_date"]).dt.date
        _hist["hour"]          = _hist["hour"].astype(int)

    # ── Load rolling (latest) files ────────────────────────────────────────────
    _de1 = pd.DataFrame()
    _de2 = pd.DataFrame()
    if os.path.exists(DE_FORE_PATH):
        _de1 = pd.read_parquet(DE_FORE_PATH)
        _de1["datetime"] = pd.to_datetime(_de1["datetime"], utc=True).dt.tz_convert("Europe/Warsaw")
        _de1["date"] = _de1["datetime"].dt.date
        _de1["H"]    = _de1["datetime"].dt.hour + 1
    if os.path.exists(DE_EFDE_PATH):
        _de2 = pd.read_parquet(DE_EFDE_PATH)
        _de2["datetime"] = pd.to_datetime(_de2["datetime"], utc=True).dt.tz_convert("Europe/Warsaw")
        _de2["date"] = _de2["datetime"].dt.date
        _de2["H"]    = _de2["datetime"].dt.hour + 1

    _rolling_dates = (set(_de1["date"]) if not _de1.empty else set()) | (set(_de2["date"]) if not _de2.empty else set())
    _hist_dates    = set(_hist["forecast_date"].unique()) if not _hist.empty else set()
    _all_dates     = sorted(_rolling_dates | _hist_dates)

    if not _all_dates:
        st.warning("Brak danych prognozy DE. Uruchom pipeline z Admin.")
        return

    # ── Navigation ─────────────────────────────────────────────────────────────
    _tomorrow = date.today() + timedelta(days=1)
    if "def_fdate" not in st.session_state or st.session_state.def_fdate not in _all_dates:
        st.session_state.def_fdate = _tomorrow if _tomorrow in _all_dates else _all_dates[-1]

    _dnav = st.columns([0.06, 0.16, 0.06, 0.10, 0.10, 0.52])
    with _dnav[0]:
        _go_prev = st.button("◀", use_container_width=True, key="def_prev")
    with _dnav[1]:
        _picked = st.date_input("d", value=st.session_state.def_fdate,
                                min_value=_all_dates[0], max_value=_all_dates[-1],
                                label_visibility="collapsed")
    with _dnav[2]:
        _go_next = st.button("▶", use_container_width=True, key="def_next")
    with _dnav[3]:
        _to_pln = st.checkbox("PLN", value=True, key="def_pln")
    with _dnav[4]:
        _show_real = st.checkbox("Real", value=True, key="def_real")

    _picked = _picked if isinstance(_picked, type(date.today())) else pd.Timestamp(_picked).date()
    try:
        _cur_i = _all_dates.index(st.session_state.def_fdate)
    except ValueError:
        _cur_i = len(_all_dates) - 1
        st.session_state.def_fdate = _all_dates[_cur_i]

    if _go_prev and _cur_i > 0:
        st.session_state.def_fdate = _all_dates[_cur_i - 1]; st.rerun()
    elif _go_next and _cur_i < len(_all_dates) - 1:
        st.session_state.def_fdate = _all_dates[_cur_i + 1]; st.rerun()
    elif _picked != st.session_state.def_fdate:
        st.session_state.def_fdate = _picked; st.rerun()

    _sel_date = st.session_state.def_fdate

    # ── FX ─────────────────────────────────────────────────────────────────────
    _eur_rate = None
    if _to_pln:
        _fx = load_eurpln()
        if not _fx.empty:
            _eur_rate = float(_fx["rate"].iloc[-1])

    def _conv(s):
        return s * (_eur_rate or 1.0) if _to_pln else s

    # ── Forecast data source ───────────────────────────────────────────────────
    # For historical dates: use history (capture_date = sel_date − 1)
    # For dates in rolling files: use rolling (latest forecast)
    _use_rolling = _sel_date in _rolling_dates
    _expected_cap = _sel_date - timedelta(days=1)
    _day_hist = pd.DataFrame()
    if not _hist.empty and not _use_rolling:
        _day_hist = _hist[
            (_hist["forecast_date"] == _sel_date) &
            (_hist["capture_date"] == _expected_cap)
        ]
        if _day_hist.empty:  # fallback: any capture for this date
            _day_hist = _hist[_hist["forecast_date"] == _sel_date]

    # ── Build chart ─────────────────────────────────────────────────────────────
    fig = go.Figure()
    _unit = "PLN/MWh" if _to_pln else "EUR/MWh"
    _y_ec = _y_efde = _y_act = None  # collected for summary table

    if _use_rolling:
        if not _de1.empty:
            _d = _de1[_de1["date"] == _sel_date].sort_values("H")
            if not _d.empty:
                _y_ec = (_d["PricePL"] if (_to_pln and "PricePL" in _d.columns) else _conv(_d["PriceEU"])).reset_index(drop=True)
                fig.add_trace(go.Scatter(x=_d["H"], y=_y_ec, mode="lines+markers",
                    name="energy-charts", line=dict(color="#1565C0", width=2.5)))
        if not _de2.empty:
            _d = _de2[_de2["date"] == _sel_date].sort_values("H")
            if not _d.empty:
                _y_efde = _conv(_d["price_eur_mwh"]).reset_index(drop=True)
                fig.add_trace(go.Scatter(x=_d["H"], y=_y_efde, mode="lines+markers",
                    name="energyforecast.de", line=dict(color="#D32F2F", width=2.5, dash="dash"),
                    customdata=_d["price_origin"],
                    hovertemplate="H%{x}<br>%{y:.1f}<br>%{customdata}<extra></extra>"))
    elif not _day_hist.empty:
        for _src, _col, _dash, _nm in [
            ("energy_charts",    "#1565C0", "solid", "energy-charts"),
            ("energyforecast_de","#D32F2F",  "dash",  "energyforecast.de"),
        ]:
            _s = _day_hist[_day_hist["source"] == _src].sort_values("hour")
            if not _s.empty:
                _yv = _conv(_s["price_eur"]).reset_index(drop=True)
                if _src == "energy_charts":
                    _y_ec = _yv
                else:
                    _y_efde = _yv
                fig.add_trace(go.Scatter(x=_s["hour"], y=_yv, mode="lines+markers",
                    name=_nm, line=dict(color=_col, width=2.5, dash=_dash)))

    # Real prices overlay
    _actuals_de = load_de_prices()
    if _show_real:
        if not _actuals_de.empty and "price_eur" in _actuals_de.columns:
            _a = _actuals_de[_actuals_de["business_date"] == _sel_date].sort_values("hour")
            if not _a.empty:
                _y_act = _conv(_a["price_eur"]).reset_index(drop=True)
                fig.add_trace(go.Scatter(x=_a["hour"], y=_y_act, mode="lines+markers",
                    name="Actual DE SPOT", line=dict(color="#2E7D32", width=3)))

    if not fig.data:
        st.info(f"Brak danych dla {_sel_date}.")
        return

    # Title caption
    if _use_rolling:
        _tcap = "(aktualna prognoza)"
    elif not _day_hist.empty:
        _tcap = f"(prognoza z {_day_hist['capture_date'].iloc[0]})"
    else:
        _tcap = ""

    fig.update_layout(
        **CHART_THEME,
        xaxis=dict(title="Godzina", tickmode="linear", tick0=1, dtick=1),
        yaxis_title=_unit,
        height=460,
        title=dict(text=f"DE Day-Ahead — {_sel_date} {_tcap}", x=0.5, font=dict(size=14)),
        legend=dict(orientation="h", y=-0.15),
        margin=dict(l=40, r=20, t=50, b=60),
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── Summary table ──────────────────────────────────────────────────────────
    def _stats(s):
        if s is None or len(s) == 0:
            return "—", "—", "—"
        return f"{s.mean():.1f}", f"{s.max():.1f}", f"{s.min():.1f}"

    _tbl_rows = [
        {"Źródło": "energy-charts",    **dict(zip(["Base", "Max", "Min"], _stats(_y_ec)))},
        {"Źródło": "energyforecast.de", **dict(zip(["Base", "Max", "Min"], _stats(_y_efde)))},
        {"Źródło": "Actual DE SPOT",   **dict(zip(["Base", "Max", "Min"], _stats(_y_act)))},
    ]
    _tbl_unit = f" ({_unit})"
    _tbl_df = pd.DataFrame(_tbl_rows).rename(columns={
        "Base": f"Base{_tbl_unit}", "Max": f"Max{_tbl_unit}", "Min": f"Min{_tbl_unit}"
    })
    st.dataframe(_tbl_df, hide_index=True, use_container_width=True)

    with st.expander("Statystyki dokładności"):
        _render_de_accuracy(_hist)

    with st.expander("Opis"):
        st.markdown("""
**DE Forecast** — dwie niezależne prognozy dnia następnego dla rynku DE + ceny rzeczywiste EPEX.

**Real** — rzeczywiste ceny EPEX z `de_prices.parquet`, widoczne dla dni historycznych.

**Statystyki dokładności** — MAE / RMSE / Bias dla prognoz D+1 vs. ceny rzeczywiste DE.
Historia prognoz zapisywana automatycznie przy każdym uruchomieniu pipeline'u.

---

#### Procedury (`procedures/`)

| Plik | Opis | Cron |
|---|---|---|
| `de_forecast_ec.py` | Prognoza DE 72H — Electricity Maps API (energy-charts) | `07:10` codziennie |
| `de_forecast_efde.py` | Prognoza DE 48H — energyforecast.de API | `07:10` codziennie |
| `de_prices.py` | Ceny rzeczywiste EPEX — backfill z Electricity Maps API | `00:00` codziennie (night) |
| `de_load.py` | Obciążenie sieci DE (net load, total load) | — (manual) |

#### Pliki (`data/de/`)

| Plik | Zawartość |
|---|---|
| `DE_Price_72H_Forecast.parquet` | Rolling snapshot prognozy energy-charts (72H) — nadpisywany codziennie |
| `DE_Price_EnergyForecastDE.parquet` | Rolling snapshot prognozy energyforecast.de (48H) — nadpisywany codziennie |
| `de_forecast_history.parquet` | Historia obu prognoz (append-only): `capture_date`, `forecast_date`, `hour`, `source`, `price_eur` |
| `de_prices.parquet` | Rzeczywiste ceny godzinowe EPEX DE: `business_date`, `hour`, `price_eur` |
| `DE_fore_hist.parquet` | Legacy historia energy-charts (wewnętrzna, nie używana przez app) |
| `de_netload.parquet` | Obciążenie netto KSE DE (MWh) |
| `de_totalload.parquet` | Całkowite obciążenie KSE DE (MWh) |
        """)



