import streamlit as st
import pandas as pd
import os, importlib.util
from datetime import date
from shared import (
    APP_DIR,
    PARQUET_PATH, PSE_PRICES_PATH, PK5_PATH,
    DE_PRICES_PATH, OTF_EE_PATH, OTF_GAS_PATH,
    ETS_CO2_PATH, RB_H_PATH, PSE_DEMAND_PATH, DE_SPOT_PATH, DE_EFDE_PATH,
    DE_FORE_HIST_PATH, DE_NETLOAD_PATH,
    CDS_PARAMS_PATH, CCS_PARAMS_PATH, ANCILLARY_PATH,
    load_prices, load_pse, load_ets, load_eurpln,
    load_otf_ee, load_otf_gas, load_pscmi, load_de_spot, load_ancillary, load_de_prices,
)

def render_parquet():
    prices = load_prices()
    available_dates = sorted(prices["fixing_date"].unique())
    st.title("Parquet Data")

    # Filter controls
    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        filter_mode = st.radio("Filter by", ["Month", "Date range"], horizontal=True)

    pq = prices.copy()

    if filter_mode == "Month":
        months = sorted({(d.year, d.month) for d in pq["fixing_date"].unique()}, reverse=True)
        month_labels = {f"{y}-{m:02d}": (y, m) for y, m in months}
        with c2:
            sel_month = st.selectbox("Month", list(month_labels.keys()))
        yr, mo = month_labels[sel_month]
        pq = pq[(pq["fixing_date"].apply(lambda d: d.year == yr and d.month == mo))]
    else:
        with c2:
            d_from = st.date_input("From", value=available_dates[0])
        with c3:
            d_to   = st.date_input("To",   value=available_dates[-1])
        pq = pq[(pq["fixing_date"] >= d_from) & (pq["fixing_date"] <= d_to)]

    pq = pq[pq["H"] >= 1].sort_values(["fixing_date", "H"])

    st.caption(f"Showing {len(pq):,} rows  ·  "
               f"{pq['fixing_date'].nunique()} days  ·  "
               f"delivery {pq['delivery_date'].min()} → {pq['delivery_date'].max()}")

    # Display
    pq_disp = pq.rename(columns={
        "fixing_date":    "Fixing date",
        "delivery_date":  "Delivery date",
        "H":              "Hour",
        "f1_price_PLN":   "F1 (PLN/MWh)",
        "sdac_price_PLN": "SDAC (PLN/MWh)",
        "spread_f1_sdac": "Spread (PLN/MWh)",
    })

    def _color_spread(val):
        if pd.isna(val):
            return ""
        return "background-color:#c8f7c5;color:#155724" if val > 0 \
               else "background-color:#fcd5d5;color:#7b0000"

    styled_pq = pq_disp.style.applymap(_color_spread, subset=["Spread (PLN/MWh)"])
    st.dataframe(styled_pq, use_container_width=True, hide_index=True, height=600)

    st.divider()
    st.subheader("Daily averages")
    daily_avg = (
        pq.groupby("fixing_date")
        .agg(
            F1_avg=("f1_price_PLN", "mean"),
            SDAC_avg=("sdac_price_PLN", "mean"),
            Spread_avg=("spread_f1_sdac", "mean"),
            Spread_max=("spread_f1_sdac", "max"),
            Spread_min=("spread_f1_sdac", "min"),
        )
        .reset_index()
        .rename(columns={"fixing_date": "Date"})
        .sort_values("Date", ascending=False)
    )
    for col in ["F1_avg", "SDAC_avg", "Spread_avg", "Spread_max", "Spread_min"]:
        daily_avg[col] = daily_avg[col].round(2)
    st.dataframe(daily_avg, use_container_width=True, hide_index=True)





def render_logs():
    st.title("Logs")

    _logs_dir = os.path.join(APP_DIR, "logs")

    if not os.path.exists(_logs_dir):
        st.warning(f"Logs folder not found: `{_logs_dir}`")
        st.stop()

    _log_files = sorted([
        f for f in os.listdir(_logs_dir)
        if f.endswith(".log")
    ])

    if not _log_files:
        st.info("No log files found in the logs folder.")
        st.stop()

    _lc1, _lc2, _lc3 = st.columns([2, 1, 1])

    with _lc1:
        _sel_log = st.selectbox("Log file", options=_log_files, key="log_sel")

    with _lc2:
        _n_lines = st.number_input("Last N lines", min_value=10, max_value=1000,
                                   value=100, step=10, key="log_lines")
    with _lc3:
        st.markdown("&nbsp;", unsafe_allow_html=True)
        _refresh = st.button("Refresh", key="log_refresh")

    _log_path = os.path.join(_logs_dir, _sel_log)

    # File info
    _stat      = os.stat(_log_path)
    _size_kb   = _stat.st_size / 1024
    _mod_time  = date.fromtimestamp(_stat.st_mtime)
    st.caption(f"Size: {_size_kb:.1f} KB  ·  Last modified: {_mod_time}")

    # Read last N lines
    try:
        with open(_log_path, "r", encoding="utf-8", errors="replace") as _f:
            _all_lines = _f.readlines()
        _shown = _all_lines[-int(_n_lines):]
        _content = "".join(_shown)
    except Exception as _e:
        st.error(f"Could not read log: {_e}")
        st.stop()

    if not _content.strip():
        st.info("Log file is empty.")
    else:
        st.code(_content, language="bash")





def render_cds_config():
    import json as _json
    import datetime as _dt_cds

    st.title("CDS — Parametry kosztowe")
    st.caption("Clean Dark Spread — kalkulacja kosztów wytwarzania energii z węgla")

    _CUR_YEAR = _dt_cds.date.today().year
    _YEAR_KEYS = ["Y", "Y+1", "Y+2", "Y+3"]
    _ADJ_DEFAULTS = {
        "Y":   {"ets_delta": 0.0, "swap_delta": 0.0,  "coal_delta": 0.0},
        "Y+1": {"ets_delta": 2.5, "swap_delta": 0.13, "coal_delta": 3.0},
        "Y+2": {"ets_delta": 0.0, "swap_delta": 0.23, "coal_delta": 4.0},
        "Y+3": {"ets_delta": 0.0, "swap_delta": 0.24, "coal_delta": 5.0},
    }

    def _load_cds_params():
        if os.path.exists(CDS_PARAMS_PATH):
            with open(CDS_PARAMS_PATH, "r") as f:
                return _json.load(f)
        return {}

    def _save_cds_params(p):
        with open(CDS_PARAMS_PATH, "w") as f:
            _json.dump(p, f, indent=2)

    _p          = _load_cds_params()
    _blocks_cfg = _p.get("blocks", {})
    _adj_saved  = _p.get("year_adjustments", _ADJ_DEFAULTS)
    BLOCK_NAMES = ["1000 MW", "500 MW", "200 MW"]

    # ── Market data ───────────────────────────────────────────────────────────
    _coal = load_pscmi()
    _ets  = load_ets()
    _fx   = load_eurpln()

    _pscmi_q  = float(_coal["pscmi_q"].iloc[-1]) if not _coal.empty else 0.0
    _pscmi_dt = _coal["date"].iloc[-1]            if not _coal.empty else "—"
    _eurpln   = float(_fx["rate"].iloc[-1])       if not _fx.empty   else 0.0
    _fx_dt    = _fx["date"].iloc[-1]              if not _fx.empty   else "—"
    _ets26    = float(_ets[_ets["symbol"] == "CKZ26.F"]["settlement"].iloc[-1]) \
                if not _ets[_ets["symbol"] == "CKZ26.F"].empty else 0.0
    _ets_dt   = _ets["date"].max() if not _ets.empty else "—"

    # ── Section 1 ─────────────────────────────────────────────────────────────
    st.subheader("1. Dane rynkowe i parametry wejściowe")

    _c1, _c2 = st.columns(2)
    with _c1:
        st.markdown("**Węgiel (baza: PSCMI 1/Q)**")
        st.markdown(f"PSCMI 1/Q: **{_pscmi_q:.2f} PLN/GJ** ({_pscmi_dt})")
        _transport = st.number_input(
            "Transport (PLN/GJ)", min_value=0.0, max_value=100.0, step=0.5,
            value=float(_p.get("transport_pln_gj", 10.0)), key="cds_transport",
        )
        _coal_base = _pscmi_q + _transport
        st.markdown(f"Baza węgiel+transport: **{_coal_base:.2f} PLN/GJ**")
    with _c2:
        st.markdown("**ETS CO₂ (baza: DEC26)**")
        st.markdown(f"DEC26: **{_ets26:.2f} EUR/t** ({_ets_dt})")
        st.markdown(f"EUR/PLN: **{_eurpln:.4f}** ({_fx_dt})")

    st.markdown("**Korekty roczne** (wartości dodawane do bazy)")

    # Table header
    _th0, _th1, _th2, _th3 = st.columns([1.2, 1.5, 1.5, 2.0])
    _th0.markdown("<small><b>Rok</b></small>", unsafe_allow_html=True)
    _th1.markdown("<small><b>EU ETS delta (EUR/t)</b></small>", unsafe_allow_html=True)
    _th2.markdown("<small><b>SWAP delta (PLN/EUR)</b></small>", unsafe_allow_html=True)
    _th3.markdown("<small><b>Węgiel+Transport delta (PLN/GJ)</b></small>", unsafe_allow_html=True)

    _new_adj = {}
    for _yk in _YEAR_KEYS:
        _yr_num = _CUR_YEAR + _YEAR_KEYS.index(_yk)
        _sv     = _adj_saved.get(_yk, _ADJ_DEFAULTS[_yk])
        _rc0, _rc1, _rc2, _rc3 = st.columns([1.2, 1.5, 1.5, 2.0])
        _rc0.markdown(f"**{_yk}** ({_yr_num})")
        _ed = _rc1.number_input("e", value=float(_sv.get("ets_delta",  0.0)),
                                 step=0.5, format="%.2f", label_visibility="collapsed",
                                 key=f"cds_adj_ets_{_yk}")
        _sd = _rc2.number_input("s", value=float(_sv.get("swap_delta", 0.0)),
                                 step=0.01, format="%.4f", label_visibility="collapsed",
                                 key=f"cds_adj_swap_{_yk}")
        _cd = _rc3.number_input("c", value=float(_sv.get("coal_delta", 0.0)),
                                 step=0.5, format="%.2f", label_visibility="collapsed",
                                 key=f"cds_adj_coal_{_yk}")
        _new_adj[_yk] = {"ets_delta": _ed, "swap_delta": _sd, "coal_delta": _cd}

    st.divider()

    # ── Section 2 ─────────────────────────────────────────────────────────────
    st.subheader("2. Parametry bloków")

    _new_blocks = {}
    _bcols = st.columns(3)
    for i, bname in enumerate(BLOCK_NAMES):
        _bdef = _blocks_cfg.get(bname, {"efficiency_pct": 40.0, "emission_tco2_mwh": 0.95, "other_costs_pln_mwh": 0.0})
        with _bcols[i]:
            st.markdown(f"**{bname}**")
            _eff   = st.number_input("Sprawność (%)", min_value=20.0, max_value=60.0, step=0.5,
                                     value=float(_bdef.get("efficiency_pct", 40.0)), key=f"cds_eff_{bname}")
            _em    = st.number_input("Emisyjność (tCO₂/MWh)", min_value=0.5, max_value=2.0, step=0.01,
                                     value=float(_bdef.get("emission_tco2_mwh", 0.95)), key=f"cds_em_{bname}")
            _other = st.number_input("Inne koszty (PLN/MWh)", min_value=0.0, max_value=200.0, step=1.0,
                                     value=float(_bdef.get("other_costs_pln_mwh", 0.0)), key=f"cds_other_{bname}")
            _new_blocks[bname] = {"efficiency_pct": _eff, "emission_tco2_mwh": _em, "other_costs_pln_mwh": _other}

    if st.button("💾 Zapisz parametry", key="cds_save"):
        _save_cds_params({
            "transport_pln_gj":  _transport,
            "year_adjustments":  _new_adj,
            "blocks":            _new_blocks,
        })
        st.success("Parametry zapisane.")

    st.divider()

    # ── Section 3 ─────────────────────────────────────────────────────────────
    st.subheader("3. Podsumowanie kosztów (PLN/MWh)")

    _yr_labels = [f"{yk}  ({_CUR_YEAR + i})" for i, yk in enumerate(_YEAR_KEYS)]
    _yr_sel_lbl = st.selectbox("Rok kalkulacji", _yr_labels, index=1, key="cds_yr_sel")
    _yr_sel     = _YEAR_KEYS[_yr_labels.index(_yr_sel_lbl)]
    _yr_num_sel = _CUR_YEAR + _YEAR_KEYS.index(_yr_sel)

    _adj      = _new_adj[_yr_sel]
    _ets_yr   = _ets26    + _adj["ets_delta"]
    _fx_yr    = _eurpln   + _adj["swap_delta"]
    _coal_yr  = _coal_base + _adj["coal_delta"]

    _mv1, _mv2, _mv3 = st.columns(3)
    _mv1.metric("Węgiel+Transport (PLN/GJ)", f"{_coal_yr:.2f}",
                delta=f"{_adj['coal_delta']:+.2f}" if _adj["coal_delta"] else None)
    _mv2.metric("ETS DEC26 + delta (EUR/t)", f"{_ets_yr:.2f}",
                delta=f"{_adj['ets_delta']:+.2f}" if _adj["ets_delta"] else None)
    _mv3.metric("EUR/PLN efektywny", f"{_fx_yr:.4f}",
                delta=f"{_adj['swap_delta']:+.4f}" if _adj["swap_delta"] else None)

    _rows = []
    for bname in BLOCK_NAMES:
        b        = _new_blocks[bname]
        _eff_dec = b["efficiency_pct"] / 100.0
        _coal_mwh = _coal_yr * 3.6 / _eff_dec
        _co2_mwh  = _ets_yr * _fx_yr * b["emission_tco2_mwh"]
        _other    = b["other_costs_pln_mwh"]
        _rows.append({
            "Blok":             bname,
            "Węgiel (PLN/MWh)": round(_coal_mwh, 2),
            "CO₂ (PLN/MWh)":    round(_co2_mwh, 2),
            "Inne (PLN/MWh)":   round(_other, 2),
            "Koszt całkowity":  round(_coal_mwh + _co2_mwh + _other, 2),
        })

    _df_sum = pd.DataFrame(_rows).set_index("Blok")
    st.caption(f"Rok {_yr_sel} ({_yr_num_sel}) — ETS: {_ets_yr:.2f} EUR/t  ·  EUR/PLN: {_fx_yr:.4f}  ·  Węgiel: {_coal_yr:.2f} PLN/GJ")
    st.dataframe(
        _df_sum.style.set_properties(subset=["Koszt całkowity"],
                                     **{"font-weight": "bold", "background-color": "#f0f4ff"}),
        use_container_width=True,
    )

    with st.expander("Wzory kalkulacji"):
        st.markdown("""
    **Koszt węgla (PLN/MWh_el)**
    ```
    (PSCMI 1/Q + transport + delta_węgiel) [PLN/GJ] × 3.6 [GJ/MWh_th] / sprawność
    ```
    **Koszt CO₂ (PLN/MWh_el)**
    ```
    (DEC26 + delta_ETS) [EUR/t] × (EUR/PLN + delta_SWAP) × emisyjność [tCO₂/MWh_el]
    ```
    **Łączny koszt**
    ```
    Koszt węgla + Koszt CO₂ + Inne koszty
    ```
    """)




def render_ccs_config():
    import json as _json_ccs_adm

    st.title("CCS — Cost Parameters")
    st.caption("Clean Spark Spread — gas-fired power plant cost parameters")

    def _load_ccs_params():
        if os.path.exists(CCS_PARAMS_PATH):
            with open(CCS_PARAMS_PATH, "r") as f:
                return _json_ccs_adm.load(f)
        return {}

    def _save_ccs_params(p):
        with open(CCS_PARAMS_PATH, "w") as f:
            _json_ccs_adm.dump(p, f, indent=2)

    _ccs_p   = _load_ccs_params()
    _cds_p2  = {}
    if os.path.exists(CDS_PARAMS_PATH):
        with open(CDS_PARAMS_PATH, "r") as _f2:
            _cds_p2 = _json_ccs_adm.load(_f2)

    CCS_TECH_NAMES = ["CCGT modern", "CCGT older", "OCGT"]
    _tech_cfg = _ccs_p.get("technologies", {})

    # ── Market data ───────────────────────────────────────────────────────────
    _ets_adm  = load_ets()
    _fx_adm   = load_eurpln()
    _gas_adm  = load_otf_gas()

    _eurpln_adm  = float(_fx_adm["rate"].iloc[-1])  if not _fx_adm.empty  else 0.0
    _fx_dt_adm   = _fx_adm["date"].iloc[-1]          if not _fx_adm.empty  else "—"
    _ets26_adm   = float(_ets_adm[_ets_adm["symbol"] == "CKZ26.F"]["settlement"].iloc[-1]) if not _ets_adm[_ets_adm["symbol"] == "CKZ26.F"].empty else 0.0
    _ets27_adm   = float(_ets_adm[_ets_adm["symbol"] == "CKZ27.F"]["settlement"].iloc[-1]) if not _ets_adm[_ets_adm["symbol"] == "CKZ27.F"].empty else 0.0
    _ets_dt_adm  = _ets_adm["date"].max() if not _ets_adm.empty else "—"
    _cds_yr_adj_adm = _cds_p2.get("year_adjustments", {})

    # ── Section 1: Market inputs ──────────────────────────────────────────────
    st.subheader("1. Market inputs")

    _mcol1, _mcol2 = st.columns(2)

    with _mcol1:
        st.markdown("**ETS CO₂** *(shared with CDS — edit on CDS page)*")
        st.markdown(f"EUR/PLN: **{_eurpln_adm:.4f}** ({_fx_dt_adm})")
        _c26a, _c27a = st.columns(2)
        with _c26a:
            st.markdown(f"DEC 26: **{_ets26_adm:.2f} EUR/t** ({_ets_dt_adm})")
            _s_y = float(_cds_yr_adj_adm.get("Y", {}).get("swap_delta", 0.0))
            st.markdown(f"Swap (Y): **{_s_y:+.4f}** → eff. rate: **{_eurpln_adm + _s_y:.4f}**")
        with _c27a:
            st.markdown(f"DEC 27: **{_ets27_adm:.2f} EUR/t** ({_ets_dt_adm})")
            _s_y1 = float(_cds_yr_adj_adm.get("Y+1", {}).get("swap_delta", 0.0))
            st.markdown(f"Swap (Y+1): **{_s_y1:+.4f}** → eff. rate: **{_eurpln_adm + _s_y1:.4f}**")

    with _mcol2:
        st.markdown("**Gas (OTF TGE)** — last available prices")
        if not _gas_adm.empty:
            _gas_latest = (
                _gas_adm[_gas_adm["product_type"].isin(["Y", "Q"])]
                .sort_values("date")
                .groupby("Kontrakt")
                .last()
                .reset_index()[["Kontrakt", "price", "date"]]
                .rename(columns={"price": "PLN/MWh", "date": "Date"})
                .sort_values("Kontrakt")
            )
            _gas_latest["PLN/MWh"] = _gas_latest["PLN/MWh"].round(2)
            _gas_latest["Date"] = _gas_latest["Date"].dt.date
            st.dataframe(_gas_latest, use_container_width=True, hide_index=True)
        else:
            st.warning("No gas data.")

    st.divider()

    # ── Section 2: Technology parameters ─────────────────────────────────────
    st.subheader("2. Power plant parameters")

    _tech_defaults = {
        "CCGT modern": {"efficiency_pct": 60.0, "emission_tco2_mwh": 0.34, "other_costs_pln_mwh": 0.0},
        "CCGT older":  {"efficiency_pct": 54.0, "emission_tco2_mwh": 0.38, "other_costs_pln_mwh": 0.0},
        "OCGT":        {"efficiency_pct": 38.0, "emission_tco2_mwh": 0.54, "other_costs_pln_mwh": 0.0},
    }

    _new_techs = {}
    _tcols = st.columns(3)
    _tech_hints = {
        "CCGT modern": "58–62% / 0.32–0.36 tCO₂/MWh",
        "CCGT older":  "52–56% / 0.36–0.40 tCO₂/MWh",
        "OCGT":        "35–40% / 0.50–0.58 tCO₂/MWh",
    }
    for i, tname in enumerate(CCS_TECH_NAMES):
        _tdef = _tech_cfg.get(tname, _tech_defaults[tname])
        with _tcols[i]:
            st.markdown(f"**{tname}**")
            st.caption(_tech_hints[tname])
            _eff_t = st.number_input(
                "Efficiency (%)", min_value=20.0, max_value=70.0, step=0.5,
                value=float(_tdef.get("efficiency_pct", _tech_defaults[tname]["efficiency_pct"])),
                key=f"ccs_eff_{tname}",
            )
            _em_t = st.number_input(
                "Emission (tCO₂/MWh)", min_value=0.1, max_value=1.0, step=0.01,
                value=float(_tdef.get("emission_tco2_mwh", _tech_defaults[tname]["emission_tco2_mwh"])),
                format="%.3f",
                key=f"ccs_em_{tname}",
            )
            _other_t = st.number_input(
                "Other costs (PLN/MWh)", min_value=0.0, max_value=200.0, step=1.0,
                value=float(_tdef.get("other_costs_pln_mwh", 0.0)),
                key=f"ccs_other_{tname}",
            )
            _new_techs[tname] = {
                "efficiency_pct":    _eff_t,
                "emission_tco2_mwh": _em_t,
                "other_costs_pln_mwh": _other_t,
            }

    if st.button("💾 Save parameters", key="ccs_save"):
        _save_ccs_params({"technologies": _new_techs})
        st.success("Parameters saved.")

    st.divider()

    # ── Section 3: Cost summary ───────────────────────────────────────────────
    st.subheader("3. Cost summary (PLN/MWh) — reference gas prices")

    if not _gas_adm.empty:
        _gas_ref_opts = sorted(_gas_adm["Kontrakt"].unique().tolist())
        _gas_ref_sel  = st.selectbox("Gas reference contract", _gas_ref_opts, key="ccs_gas_ref")
        _gas_ref_row  = _gas_adm[_gas_adm["Kontrakt"] == _gas_ref_sel].sort_values("date").iloc[-1]
        _gas_ref_price = float(_gas_ref_row["price"])
        st.caption(f"Gas price: **{_gas_ref_price:.2f} PLN/MWh** ({pd.Timestamp(_gas_ref_row['date']).date()})")
    else:
        _gas_ref_price = 0.0
        st.warning("No gas data for cost summary.")

    _eff_fx26_ccs = _eurpln_adm + float(_cds_yr_adj_adm.get("Y",   {}).get("swap_delta", 0.0))
    _eff_fx27_ccs = _eurpln_adm + float(_cds_yr_adj_adm.get("Y+1", {}).get("swap_delta", 0.0))

    _sum_rows = []
    for tname in CCS_TECH_NAMES:
        t = _new_techs[tname]
        _eff_dec = t["efficiency_pct"] / 100.0
        _gas_mwh = _gas_ref_price / _eff_dec
        _co2_26  = _ets26_adm * _eff_fx26_ccs * t["emission_tco2_mwh"]
        _co2_27  = _ets27_adm * _eff_fx27_ccs * t["emission_tco2_mwh"]
        _other   = t["other_costs_pln_mwh"]
        _sum_rows.append({
            "Technology":               tname,
            "Gas cost (PLN/MWh)":       round(_gas_mwh, 2),
            "CO₂ DEC26 (PLN/MWh)":     round(_co2_26, 2),
            "CO₂ DEC27 (PLN/MWh)":     round(_co2_27, 2),
            "Other (PLN/MWh)":          round(_other, 2),
            "Total cost DEC26 (PLN/MWh)": round(_gas_mwh + _co2_26 + _other, 2),
            "Total cost DEC27 (PLN/MWh)": round(_gas_mwh + _co2_27 + _other, 2),
        })

    _df_ccs_sum = pd.DataFrame(_sum_rows).set_index("Technology")

    def _style_ccs_summary(df):
        styled = df.style
        for col in ["Total cost DEC26 (PLN/MWh)", "Total cost DEC27 (PLN/MWh)"]:
            styled = styled.set_properties(subset=[col], **{"font-weight": "bold", "background-color": "#f0f4ff"})
        return styled

    st.dataframe(_style_ccs_summary(_df_ccs_sum), use_container_width=True)

    with st.expander("Calculation formulas"):
        st.markdown("""
    **Gas fuel cost (PLN/MWh_el)**
    ```
    Gas_price [PLN/MWh_th] / efficiency
    ```
    **CO₂ cost (PLN/MWh_el)**
    ```
    ETS [EUR/t] × (EUR/PLN + Swap) × emission [tCO₂/MWh_el]
    ```
    **Total cost**
    ```
    Gas cost + CO₂ cost + Other costs
    ```
    **CCS**
    ```
    Power price − Total cost
    ```
    """)




def render_admin():
    st.title("Admin — Data Pipelines")
    st.caption("Run pipelines manually, view last available data date per source.")

    import importlib.util as _ilu_adm

    _root_adm = APP_DIR

    def _load_mod_adm(path, name):
        _spec = _ilu_adm.spec_from_file_location(name, path)
        _mod  = _ilu_adm.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        return _mod

    def _last_date_adm(path, date_col="date"):
        try:
            if not os.path.exists(path):
                return "no data"
            _df = pd.read_parquet(path, columns=[date_col])
            return str(pd.to_datetime(_df[date_col]).max().date())
        except Exception:
            return "?"

    # ── Pipeline registry ──────────────────────────────────────────────────────
    # (key, label, description, affects, parquet_path, date_col, cron_note)
    _ADM_PIPELINES = [
        ("tge_fixing", "TGE Fixing",
         "Day-ahead fixing prices (RDN) from TGE website",
         "Prices, FixTrade",
         PARQUET_PATH, "fixing_date", None),
        ("pse_prices", "PSE Prices",
         "CEN day-ahead prices from PSE API",
         "PSE",
         PSE_PRICES_PATH, "business_date", None),
        ("pk5", "PK5 Forecast",
         "PSE 5-day generation plan: wind, PV, demand",
         "PK5",
         PK5_PATH, "business_date", None),
        ("de_spot", "DE Spot (EPEX)",
         "German EPEX day-ahead prices from netztransparenz.de",
         "Prices",
         DE_SPOT_PATH, "date", "auto 06:00 daily"),
        ("de_efde", "DE Forecast (EFDE)",
         "2nd DE forecast — next 48h, energyforecast.de (not yet wired into models)",
         "—",
         DE_EFDE_PATH, "datetime", "auto 07:10 daily"),
        ("ets_co2", "ETS CO₂",
         "ICE EU Allowances settlement prices (EUR/tCO₂)",
         "ETS1",
         ETS_CO2_PATH, "date", None),
        ("otf_ee", "OTF / EE",
         "TGE OTF electricity forward prices (DKR)",
         "OTF / EE",
         OTF_EE_PATH, "date", "auto 17:00 Mon–Fri"),
        ("otf_gas", "OTF / Gas",
         "TGE OTF gas forward prices (DKR)",
         "OTF / Gas",
         OTF_GAS_PATH, "date", "auto 17:00 Mon–Fri"),
        ("rmb_pipeline", "RMB Ancillary",
         "PSE API mbp-tp: FCR, aFRR, mFRR, RR prices",
         "Ancillary History, Daily",
         ANCILLARY_PATH, "business_date", "auto 07:15 daily"),
        ("de_prices_ec", "DE Prices (EC)",
         "German hourly actual prices from Electricity Maps API",
         "DE Forecast",
         DE_PRICES_PATH, "business_date", None),
        ("de_load_ec", "DE Load (EC)",
         "German net/total load from Electricity Maps API",
         "—",
         DE_NETLOAD_PATH, "business_date", None),
        ("de_forecast_ec", "DE Forecast (EC)",
         "German 72H day-ahead forecast from Electricity Maps (energy-charts)",
         "DE Forecast",
         DE_FORE_HIST_PATH, "capture_date", "auto 07:10 daily"),
    ]

    # ── Table header ───────────────────────────────────────────────────────────
    _ah1, _ah2, _ah3, _ah4, _ah5, _ah6 = st.columns([1.6, 2.8, 1.7, 1.3, 1.8, 1.0])
    _ah1.markdown("**Pipeline**")
    _ah2.markdown("**Description**")
    _ah3.markdown("**Affects**")
    _ah4.markdown("**Last date**")
    _ah5.markdown("**Schedule**")
    _ah6.markdown("**Action**")
    st.divider()

    _adm_to_run = None

    for _akey, _alabel, _adesc, _aaffects, _apath, _adcol, _acron in _ADM_PIPELINES:
        _ac1, _ac2, _ac3, _ac4, _ac5, _ac6 = st.columns([1.6, 2.8, 1.7, 1.3, 1.8, 1.0])
        _ac1.markdown(f"**{_alabel}**")
        _ac2.markdown(f"<small>{_adesc}</small>", unsafe_allow_html=True)
        _ac3.markdown(f"<small>{_aaffects}</small>", unsafe_allow_html=True)
        _ac4.markdown(
            f"<small style='font-family:monospace'>{_last_date_adm(_apath, _adcol)}</small>",
            unsafe_allow_html=True,
        )
        _ac5.markdown(
            f"<small style='color:#888'>{'🕔 ' + _acron if _acron else '—'}</small>",
            unsafe_allow_html=True,
        )
        if _ac6.button("Run", key=f"adm_run_{_akey}"):
            _adm_to_run = (_akey, _alabel)

    # ── Run selected pipeline ──────────────────────────────────────────────────
    if _adm_to_run:
        _run_key, _run_label = _adm_to_run
        st.divider()
        st.subheader(f"Running: {_run_label}")
        _adm_log_box = st.empty()
        _adm_lines   = []

        def _adm_log(msg):
            _adm_lines.append(str(msg))
            _adm_log_box.code("\n".join(_adm_lines), language="bash")

        _adm_result = None

        if _run_key == "tge_fixing":
            _m = _load_mod_adm(os.path.join(_root_adm, "procedures", "tge_fixing.py"), "tge_fixing")
            _adm_result = _m.run_pipeline(app_dir=_root_adm, log=_adm_log)
            load_prices.clear()

        elif _run_key == "pse_prices":
            _m = _load_mod_adm(os.path.join(_root_adm, "procedures", "pse_prices.py"), "pse_prices")
            _adm_result = _m.run_pipeline(app_dir=_root_adm, log=_adm_log)
            load_pse.clear()

        elif _run_key == "pk5":
            _m = _load_mod_adm(os.path.join(_root_adm, "procedures", "pk5_pipeline.py"), "pk5_pipeline")
            _adm_result = _m.run_pipeline(app_dir=_root_adm, log=_adm_log)
            load_pk5.clear()

        elif _run_key == "de_spot":
            _m = _load_mod_adm(os.path.join(_root_adm, "procedures", "de_spot.py"), "de_spot")
            _adm_result = _m.run_pipeline(app_dir=_root_adm, log=_adm_log)
            load_de_spot.clear()

        elif _run_key == "de_efde":
            _m = _load_mod_adm(os.path.join(_root_adm, "procedures", "de_forecast_efde.py"), "de_forecast_efde")
            _adm_result = _m.run_pipeline(app_dir=_root_adm, log=_adm_log)

        elif _run_key == "ets_co2":
            _m = _load_mod_adm(os.path.join(_root_adm, "procedures", "ets_co2.py"), "ets_co2")
            _adm_result = _m.run_pipeline(app_dir=_root_adm, log=_adm_log)
            load_ets.clear()

        elif _run_key == "otf_ee":
            _m = _load_mod_adm(os.path.join(_root_adm, "procedures", "tge_otf_ee.py"), "tge_otf_ee")
            _adm_result = _m.run_pipeline(app_dir=_root_adm, log=_adm_log)
            load_otf_ee.clear()

        elif _run_key == "otf_gas":
            _m = _load_mod_adm(os.path.join(_root_adm, "procedures", "tge_otf_gas.py"), "tge_otf_gas")
            _adm_result = _m.run_pipeline(app_dir=_root_adm, log=_adm_log)
            load_otf_gas.clear()

        elif _run_key == "rmb_pipeline":
            _m = _load_mod_adm(os.path.join(_root_adm, "procedures", "rmb_pipeline.py"), "rmb_pipeline")
            _adm_result = _m.run_pipeline(app_dir=_root_adm, log=_adm_log)
            load_ancillary.clear()

        elif _run_key == "de_prices_ec":
            _m = _load_mod_adm(os.path.join(_root_adm, "procedures", "de_prices.py"), "de_prices")
            _adm_result = _m.run_pipeline(app_dir=_root_adm, log=_adm_log)
            load_de_prices.clear()

        elif _run_key == "de_load_ec":
            _m = _load_mod_adm(os.path.join(_root_adm, "procedures", "de_load.py"), "de_load")
            _adm_result = _m.run_pipeline(app_dir=_root_adm, log=_adm_log)

        elif _run_key == "de_forecast_ec":
            _m = _load_mod_adm(os.path.join(_root_adm, "procedures", "de_forecast_ec.py"), "de_forecast_ec")
            _adm_result = _m.run_pipeline(app_dir=_root_adm, log=_adm_log)

        if _adm_result:
            if _adm_result.get("status") == "ok":
                st.success(_adm_result.get("message", "Done."))
            else:
                st.error(_adm_result.get("message", "Pipeline returned an error."))


def render_backup():
    import glob as _glob

    BACKUP_DIR = "/home/ubuntu/backups/quant_energy"

    st.title("Backup")
    st.caption(f"Snapshots stored in `{BACKUP_DIR}` · daily at 06:00 · last 30 kept")

    # README
    readme_path = os.path.join(BACKUP_DIR, "README.txt")
    if os.path.exists(readme_path):
        with st.expander("README", expanded=False):
            with open(readme_path, "r") as _f:
                st.text(_f.read())

    if not os.path.isdir(BACKUP_DIR):
        st.warning("Backup directory not found — only available on the production server.")
        return

    # List snapshot folders
    snapshots = sorted(
        [d for d in os.listdir(BACKUP_DIR)
         if os.path.isdir(os.path.join(BACKUP_DIR, d))],
        reverse=True,
    )

    if not snapshots:
        st.info("No snapshots found yet.")
        return

    st.markdown(f"**{len(snapshots)} snapshot(s) available**")
    st.divider()

    # Header
    hc1, hc2, hc3, hc4 = st.columns([1.8, 1.2, 1.0, 2.0])
    hc1.markdown("**Snapshot**")
    hc2.markdown("**Size**")
    hc3.markdown("**Files**")
    hc4.markdown("**Contents**")
    st.divider()

    for snap in snapshots:
        snap_path = os.path.join(BACKUP_DIR, snap)

        # Size
        total_bytes = 0
        file_count  = 0
        all_files   = []
        for root, dirs, files in os.walk(snap_path):
            for fname in files:
                fpath = os.path.join(root, fname)
                sz    = os.path.getsize(fpath)
                total_bytes += sz
                file_count  += 1
                rel = os.path.relpath(fpath, snap_path)
                all_files.append(rel)

        if total_bytes < 1024 * 1024:
            size_str = f"{total_bytes / 1024:.0f} KB"
        else:
            size_str = f"{total_bytes / 1024 / 1024:.1f} MB"

        top_level = sorted({f.split(os.sep)[0] for f in all_files})
        contents  = "  ·  ".join(top_level)

        rc1, rc2, rc3, rc4 = st.columns([1.8, 1.2, 1.0, 2.0])
        rc1.markdown(f"`{snap}`")
        rc2.markdown(f"<small>{size_str}</small>", unsafe_allow_html=True)
        rc3.markdown(f"<small>{file_count}</small>", unsafe_allow_html=True)
        rc4.markdown(f"<small style='color:#666'>{contents}</small>", unsafe_allow_html=True)


# ─── Data Files Browser ────────────────────────────────────────────────────────

def render_data_files():
    from io import BytesIO
    import glob as _glob
    from datetime import datetime

    st.title("Data Files")
    st.caption("Browse and download parquet files from the data directory (converted to Excel on the fly).")

    data_dir     = os.path.join(APP_DIR, "data")
    app_data_dir = os.path.join(APP_DIR, "app_data")

    files = []
    for base_dir in [data_dir, app_data_dir]:
        for fpath in sorted(_glob.glob(os.path.join(base_dir, "**", "*.parquet"), recursive=True)):
            rel      = os.path.relpath(fpath, APP_DIR).replace("\\", "/")
            category = "/".join(rel.split("/")[:-1])
            name     = os.path.basename(fpath)
            try:
                size_kb  = round(os.path.getsize(fpath) / 1024, 1)
                mtime    = datetime.fromtimestamp(os.path.getmtime(fpath)).strftime("%Y-%m-%d %H:%M")
            except OSError:
                size_kb, mtime = 0, "—"
            files.append({"Category": category, "File": name,
                          "Size (KB)": size_kb, "Modified": mtime,
                          "_path": fpath, "_rel": rel})

    if not files:
        st.warning("No parquet files found in data/ or app_data/.")
        return

    df_index = pd.DataFrame([{k: v for k, v in f.items() if not k.startswith("_")}
                              for f in files])
    st.dataframe(df_index, hide_index=True, use_container_width=True,
                 height=min(len(files) * 35 + 40, 520))

    st.divider()
    st.subheader("Download as Excel")

    labels  = [f["_rel"] for f in files]
    sel_idx = st.selectbox("Select file", range(len(labels)),
                           format_func=lambda i: labels[i])
    sel     = files[sel_idx]

    try:
        df = pd.read_parquet(sel["_path"])
        c1, c2 = st.columns(2)
        c1.metric("Rows", f"{len(df):,}")
        c2.metric("Columns", len(df.columns))
        st.dataframe(df.head(8), use_container_width=True, hide_index=True)

        buf = BytesIO()
        df_xl = df.copy()
        for col in df_xl.columns:
            if pd.api.types.is_datetime64_any_dtype(df_xl[col]):
                try:
                    df_xl[col] = df_xl[col].dt.tz_localize(None)
                except Exception:
                    try:
                        df_xl[col] = df_xl[col].dt.tz_convert(None)
                    except Exception:
                        pass
        df_xl.to_excel(buf, index=False, engine="openpyxl")
        buf.seek(0)

        fname = sel["File"].replace(".parquet", ".xlsx")
        st.download_button(
            label=f"Download {fname}",
            data=buf,
            file_name=fname,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
        )
    except FileNotFoundError:
        st.error("File not found (are you running locally without server data?).")
    except Exception as exc:
        st.error(f"Error loading file: {exc}")


