"""
spot_update.py -- SPOT section manual update page.

Consolidates all data-refresh actions for the SPOT section:
  1. TGE Fixing (F1 + SDAC)   -- Polish SPOT / SPOT Daily
  2. DE Prices (EPEX)          -- German SPOT / Polish SPOT DE overlay
  3. EUR/PLN Rate (NBP)        -- currency conversion for DE prices
"""

import os
import importlib.util
import streamlit as st
from datetime import date, timedelta

from shared import APP_DIR, load_prices, load_de_prices, load_eurpln


def _load_mod(rel_path: str, name: str):
    path = os.path.join(APP_DIR, rel_path)
    spec = importlib.util.spec_from_file_location(name, path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def render_spot_update():
    st.title("SPOT — Update")
    st.caption(
        "Manual data refresh for the SPOT section. "
        "Most pipelines run automatically via cron — use these buttons only when "
        "you need data outside the scheduled window or want to backfill a missing date."
    )

    # ── 1. TGE Fixing ────────────────────────────────────────────────────────
    st.subheader("TGE Fixing — F1 & SDAC")
    st.markdown(
        "<div style='font-size:0.85rem;color:#666;line-height:1.8;margin-bottom:8px'>"
        "<b>Pages:</b> Polish SPOT, SPOT Daily<br>"
        "<b>Pipeline:</b> <code>procedures/tge_fixing.py</code><br>"
        "<b>Auto-update:</b> daily at <b>06:00 CET</b> via cron "
        "(<code>cron_daily.sh morning</code>)<br>"
        "<b>File:</b> <code>data/pl_spot/FixingPricesH.parquet</code>"
        "</div>",
        unsafe_allow_html=True,
    )
    _tf_c1, _tf_c2, _tf_c3 = st.columns([0.3, 0.15, 0.55])
    _tf_date = _tf_c1.date_input(
        "Delivery date", value=date.today(),
        min_value=date(2020, 1, 1), max_value=date.today() + timedelta(days=1),
        key="su_tf_date",
    )
    _tf_fix = _tf_c2.selectbox("Fixing", ["F1", "F2 (SDAC)", "Both"], key="su_tf_fix")
    _tf_c3.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)

    if st.button("Run TGE Fixing", key="su_tf_run", type="primary"):
        _fixing_date = _tf_date - timedelta(days=1)
        _msgs = []
        try:
            mod = _load_mod("procedures/tge_fixing.py", "tge_fixing")
            with st.spinner(f"Running TGE Fixing for delivery {_tf_date} ..."):
                res = mod.run_pipeline(
                    app_dir=APP_DIR,
                    start_date=_fixing_date,
                    end_date=_fixing_date,
                    log=_msgs.append,
                )
            if res.get("status") == "ok":
                st.success(res.get("message", "Done."))
                load_prices.clear()
                st.cache_data.clear()
            else:
                st.error(res.get("message", "Pipeline returned error."))
        except Exception as ex:
            st.error(f"Pipeline error: {ex}")
        if _msgs:
            with st.expander("Pipeline log"):
                st.text("\n".join(_msgs))

    st.divider()

    # ── 2. DE Prices (EPEX) ───────────────────────────────────────────────────
    st.subheader("DE Prices — EPEX Day-Ahead")
    st.markdown(
        "<div style='font-size:0.85rem;color:#666;line-height:1.8;margin-bottom:8px'>"
        "<b>Pages:</b> German SPOT, Polish SPOT (DE overlay)<br>"
        "<b>Pipeline:</b> <code>procedures/de_prices.py</code><br>"
        "<b>Auto-update:</b> daily at <b>04:00 CET</b> via cron "
        "(<code>cron_daily.sh night</code>)<br>"
        "<b>File:</b> <code>data/de/de_prices.parquet</code>"
        "</div>",
        unsafe_allow_html=True,
    )
    if st.button("Update DE Prices", key="su_de_run", type="primary"):
        _msgs_de = []
        try:
            mod_de = _load_mod("procedures/de_prices.py", "de_prices")
            with st.spinner("Fetching EPEX Day-Ahead prices ..."):
                res_de = mod_de.run_pipeline(app_dir=APP_DIR, log=_msgs_de.append)
            if res_de.get("status") == "ok":
                st.success(f"Done — {res_de.get('new_rows', 0)} new rows.")
                load_de_prices.clear()
            else:
                st.error(res_de.get("message", "Pipeline returned error."))
        except Exception as ex:
            st.error(f"Pipeline error: {ex}")
        if _msgs_de:
            with st.expander("Pipeline log"):
                st.text("\n".join(_msgs_de))

    st.divider()

    # ── 3. EUR/PLN Rate ───────────────────────────────────────────────────────
    st.subheader("EUR/PLN Rate — NBP")
    st.markdown(
        "<div style='font-size:0.85rem;color:#666;line-height:1.8;margin-bottom:8px'>"
        "<b>Pages:</b> German SPOT, Polish SPOT (DE overlay)<br>"
        "<b>Pipeline:</b> <code>procedures/nbp_eurpln.py</code><br>"
        "<b>Auto-update:</b> <b>none</b> — manual only<br>"
        "<b>File:</b> <code>data/market/EURPLN_Rate.parquet</code>"
        "</div>",
        unsafe_allow_html=True,
    )
    if st.button("Update EUR/PLN Rate", key="su_fx_run", type="primary"):
        _msgs_fx = []
        try:
            mod_fx = _load_mod("procedures/nbp_eurpln.py", "nbp_eurpln")
            with st.spinner("Fetching EUR/PLN rate from NBP ..."):
                res_fx = mod_fx.run_pipeline(app_dir=APP_DIR, log=_msgs_fx.append)
            if res_fx.get("status") == "ok":
                st.success(f"Done — {res_fx.get('new_rows', 0)} new rows.")
                load_eurpln.clear()
            else:
                st.error(res_fx.get("message", "Pipeline returned error."))
        except Exception as ex:
            st.error(f"Pipeline error: {ex}")
        if _msgs_fx:
            with st.expander("Pipeline log"):
                st.text("\n".join(_msgs_fx))
