import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import os, importlib.util
from datetime import date, timedelta
import matplotlib
import matplotlib.pyplot as plt
from shared import (
    CHART_THEME, APP_DIR,
    load_otf_ee, load_otf_gas, load_ets, load_eurpln, load_pscmi,
    load_rb_h_cached, load_de_prices,
    OTF_EE_PATH, OTF_GAS_PATH, ETS_CO2_PATH, PSCMI_PATH,
    CDS_PARAMS_PATH, CCS_PARAMS_PATH,
    _otf_delivery_hours,
)

def render_ets():
    st.title("ETS CO2")
    st.caption("ICE EU Allowances futures — settlement prices (EUR/tCO₂)")

    if "ets_man_msg" in st.session_state:
        st.success(st.session_state.pop("ets_man_msg"))

    ets_df = load_ets()

    if not ets_df.empty:
        # ── Staleness check ───────────────────────────────────────────────────
        for _sym in ["CKZ26.F", "CKZ27.F"]:
            _sym_rows = ets_df[ets_df["symbol"] == _sym]
            if not _sym_rows.empty:
                _last_s = _sym_rows["date"].max()
                _gap = sum(
                    1 for i in range(1, (date.today() - _last_s).days)
                    if (_last_s + timedelta(days=i)).weekday() < 5
                )
                if _gap > 1:
                    st.warning(
                        f"**{_sym}**: last saved {_last_s} — "
                        f"~{_gap - 1} trading day(s) may be unrecoverable. "
                        f"Press **Update ETS** to recover the most recent missing day.")

        # ── Metrics ───────────────────────────────────────────────────────────
        _contracts = ["CKZ26.F", "CKZ27.F"]
        _labels    = {"CKZ26.F": "Dec 2026", "CKZ27.F": "Dec 2027"}
        _colors    = {"CKZ26.F": "#1565c0",  "CKZ27.F": "#e65100"}

        _last = {}
        for _sym in _contracts:
            _rows = ets_df[ets_df["symbol"] == _sym].sort_values("date")
            if not _rows.empty:
                _last[_sym] = _rows.iloc[-1]

        mc = st.columns(len(_last) + 1)
        for i, _sym in enumerate([s for s in _contracts if s in _last]):
            _r    = _last[_sym]
            _prev = ets_df[ets_df["symbol"] == _sym].sort_values("date")
            _delta = None
            if len(_prev) >= 2:
                _delta = round(float(_r["settlement"]) - float(_prev.iloc[-2]["settlement"]), 2)
            mc[i].metric(
                f"{_labels[_sym]} ({_sym})",
                f"{_r['settlement']:.2f} EUR",
                delta=f"{_delta:+.2f}" if _delta is not None else None,
            )
        if len(_last) == 2 and all(s in _last for s in _contracts):
            _spread_val = round(
                float(_last["CKZ27.F"]["settlement"]) - float(_last["CKZ26.F"]["settlement"]), 2)
            mc[2].metric("Spread 27−26", f"{_spread_val:+.2f} EUR")

        # ── Date range filter ─────────────────────────────────────────────────
        _all_dates = sorted(ets_df["date"].unique())
        _default_start = date.today() - timedelta(days=90)
        _min_date = _all_dates[0]
        _max_date = _all_dates[-1]
        _dc1, _dc2 = st.columns(2)
        with _dc1:
            _date_from = st.date_input("From", value=max(_default_start, _min_date),
                                       min_value=_min_date, max_value=_max_date, key="ets_from")
        with _dc2:
            _date_to = st.date_input("To", value=_max_date,
                                     min_value=_min_date, max_value=_max_date, key="ets_to")

        ets_filtered = ets_df[(ets_df["date"] >= _date_from) & (ets_df["date"] <= _date_to)]

        # ── Chart ─────────────────────────────────────────────────────────────
        fig = go.Figure()
        for _sym in _contracts:
            _s = ets_filtered[ets_filtered["symbol"] == _sym].sort_values("date")
            if _s.empty:
                continue
            fig.add_trace(go.Scatter(
                x=_s["date"].tolist(),
                y=_s["settlement"].tolist(),
                mode="lines",
                name=_labels[_sym],
                line=dict(color=_colors[_sym], width=2.5),
                hovertemplate="%{x}  <b>%{y:.2f} EUR</b><extra>" + _labels[_sym] + "</extra>",
            ))

        fig.update_layout(
            **CHART_THEME,
            title="ICE EUA Futures — Settlement Price (EUR/tCO₂)",
            xaxis=dict(title="", gridcolor="#eee", linecolor="#ccc"),
            yaxis=dict(title="EUR / tCO₂", gridcolor="#eee", linecolor="#ccc"),
            legend=dict(orientation="h", y=1.08, x=0, bgcolor="white"),
            height=460, margin=dict(t=80, b=40, l=60, r=20),
            hovermode="x unified",
        )
        st.plotly_chart(fig, use_container_width=True,
                        config={"displayModeBar": True,
                                "toImageButtonOptions": {"format": "png", "filename": "ets_co2", "scale": 2}})
        st.caption("Use the 📷 camera icon in the chart toolbar to download as PNG.")

        # ── Data table ────────────────────────────────────────────────────────
        with st.expander("History table"):
            _tbl_raw = ets_filtered.copy().sort_values(["date", "symbol"], ascending=[False, True])
            _tbl_raw["date"]       = _tbl_raw["date"].astype(str)
            _tbl_raw["settlement"] = _tbl_raw["settlement"].round(2)
            for _col in ["open", "high", "low"]:
                if _col in _tbl_raw.columns:
                    _tbl_raw[_col] = pd.to_numeric(_tbl_raw[_col], errors="coerce").round(2)
            _raw_cols = [c for c in ["date","symbol","contract","open","high","low","settlement","volume"]
                         if c in _tbl_raw.columns]
            _col_cfg_ets = {
                "date":       st.column_config.TextColumn("Date",        disabled=True),
                "symbol":     st.column_config.TextColumn("Symbol",      disabled=True),
                "contract":   st.column_config.TextColumn("Contract",    disabled=True),
                "open":       st.column_config.NumberColumn("Open",      disabled=True, format="%.2f"),
                "high":       st.column_config.NumberColumn("High",      disabled=True, format="%.2f"),
                "low":        st.column_config.NumberColumn("Low",       disabled=True, format="%.2f"),
                "settlement": st.column_config.NumberColumn("Settlement",disabled=True, format="%.2f"),
                "volume":     st.column_config.NumberColumn("Volume",    disabled=True),
            }
            _edited_ets = st.data_editor(
                _tbl_raw[_raw_cols],
                use_container_width=True,
                hide_index=True,
                num_rows="dynamic",
                column_config=_col_cfg_ets,
                key="ets_hist_editor",
            )
            _n_del = len(_tbl_raw) - len(_edited_ets)
            if _n_del > 0:
                if st.button(f"🗑 Save deletions ({_n_del} row(s))",
                             type="primary", key="ets_hist_del_btn"):
                    _PATH_ETS_D = os.path.join(APP_DIR, "data", "ets", "ets_co2.parquet")
                    _df_full = pd.read_parquet(_PATH_ETS_D)
                    _df_full["date"] = pd.to_datetime(_df_full["date"]).dt.date
                    _remaining = set(zip(_edited_ets["date"].astype(str), _edited_ets["symbol"]))
                    _mask_in   = (_df_full["date"] >= _date_from) & (_df_full["date"] <= _date_to)
                    _kept = _df_full[_mask_in][_df_full[_mask_in].apply(
                        lambda r: (str(r["date"]), r["symbol"]) in _remaining, axis=1
                    )]
                    _final = (pd.concat([_df_full[~_mask_in], _kept], ignore_index=True)
                              .sort_values(["symbol", "date"]).reset_index(drop=True))
                    _tmp_d = _PATH_ETS_D + ".tmp"
                    _final.to_parquet(_tmp_d, index=False)
                    os.replace(_tmp_d, _PATH_ETS_D)
                    load_ets.clear()
                    st.rerun()

    else:
        st.info("No ETS data yet. Press **Update ETS** below to fetch today's prices.")

    # ── Update button ─────────────────────────────────────────────────────────
    st.divider()
    if st.button("Update ETS", key="ets_update"):
        import importlib.util as _ilu
        _spec = _ilu.spec_from_file_location(
            "ets_co2",
            os.path.join(APP_DIR, "procedures", "ets_co2.py")
        )
        _mod = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        _lines = []
        with st.spinner("Fetching ETS prices..."):
            _result = _mod.run_pipeline(
                app_dir=APP_DIR,
                log=lambda m: _lines.append(m),
            )
        load_ets.clear()
        if _result.get("status") == "ok":
            st.success(_result.get("message", "Done."))
        else:
            st.error(_result.get("message", "Something went wrong."))
        with st.expander("Pipeline log"):
            st.text("\n".join(_lines))
        st.rerun()

    # ── Manual price entry ────────────────────────────────────────────────────
    st.divider()
    with st.expander("Manual price entry", expanded=False):
        st.caption("Enter settlement prices manually when the automatic pipeline is unavailable.")
        _mc1, _mc2, _mc3 = st.columns([0.7, 0.7, 0.7])
        _man_date  = _mc1.date_input("Date", value=date.today(), key="ets_man_date")
        _man_ck26  = _mc2.number_input("CKZ26.F  [EUR/tCO₂]", min_value=0.0,
                                        value=0.0, step=0.01, format="%.2f", key="ets_man_26")
        _man_ck27  = _mc3.number_input("CKZ27.F  [EUR/tCO₂]", min_value=0.0,
                                        value=0.0, step=0.01, format="%.2f", key="ets_man_27")

        if st.button("Save manual entry", key="ets_man_save"):
            if _man_ck26 <= 0 and _man_ck27 <= 0:
                st.warning("Enter at least one price above zero.")
            else:
                _PATH_ETS = os.path.join(APP_DIR, "data", "ets", "ets_co2.parquet")
                _rows = []
                if _man_ck26 > 0:
                    _rows.append({"date": _man_date, "symbol": "CKZ26.F",
                                  "contract": "ICE CO2 EUA DEC 2026",
                                  "open": None, "high": None, "low": None,
                                  "settlement": round(_man_ck26, 2), "volume": None})
                if _man_ck27 > 0:
                    _rows.append({"date": _man_date, "symbol": "CKZ27.F",
                                  "contract": "ICE CO2 EUA DEC 2027",
                                  "open": None, "high": None, "low": None,
                                  "settlement": round(_man_ck27, 2), "volume": None})
                _df_new  = pd.DataFrame(_rows)
                _df_new["date"] = pd.to_datetime(_df_new["date"]).dt.date
                if os.path.exists(_PATH_ETS):
                    _df_ex = pd.read_parquet(_PATH_ETS)
                    _df_ex["date"] = pd.to_datetime(_df_ex["date"]).dt.date
                    _df_all = pd.concat([_df_ex, _df_new], ignore_index=True)
                else:
                    _df_all = _df_new
                _df_all = (_df_all
                           .sort_values(["symbol", "date"])
                           .drop_duplicates(["symbol", "date"], keep="last")
                           .reset_index(drop=True))
                _tmp = _PATH_ETS + ".tmp"
                _df_all.to_parquet(_tmp, index=False)
                os.replace(_tmp, _PATH_ETS)
                load_ets.clear()
                syms = ", ".join([r["symbol"] for r in _rows])
                st.session_state["ets_man_msg"] = f"Saved {syms} for {_man_date} → {len(_df_all)} total rows."
                st.rerun()




def render_coal():
    st.title("PSCMI 1 — Polski Indeks Rynku Węgla")
    st.markdown(
        "<p style='font-size:0.9rem; color:#666;'>"
        "Miesięczny indeks cen węgla energetycznego na rynku krajowym · "
        "<a href='https://polskirynekwegla.pl/notowania-indeksow' target='_blank' style='color:#1565c0; text-decoration:none;'>"
        "polskirynekwegla.pl/notowania-indeksow →</a>"
        "</p>",
        unsafe_allow_html=True
    )

    coal_df = load_pscmi()

    if not coal_df.empty:
        # ── Metrics ───────────────────────────────────────────────────────────
        _last  = coal_df.iloc[-1]
        _prev  = coal_df.iloc[-2] if len(coal_df) >= 2 else None
        mc1, mc2, mc3 = st.columns(3)
        mc1.metric(
            f"PSCMI 1/T  ({_last['date'].strftime('%m.%Y')})",
            f"{_last['pscmi_t']:.2f} PLN/T",
            delta=f"{_last['pscmi_t'] - _prev['pscmi_t']:+.2f}" if _prev is not None else None,
        )
        mc2.metric(
            f"PSCMI 1/Q  ({_last['date'].strftime('%m.%Y')})",
            f"{_last['pscmi_q']:.2f} PLN/GJ",
            delta=f"{_last['pscmi_q'] - _prev['pscmi_q']:+.2f}" if _prev is not None else None,
        )
        mc3.metric("Miesięcy w historii", len(coal_df))

        # ── Date range filter ─────────────────────────────────────────────────
        _all_dates = sorted(coal_df["date"].unique())
        _default_from = date(date.today().year - 2, 1, 1)
        _cc1, _cc2 = st.columns(2)
        with _cc1:
            _coal_from = st.date_input("Od", value=max(_default_from, _all_dates[0]),
                                       min_value=_all_dates[0], max_value=_all_dates[-1],
                                       key="coal_from")
        with _cc2:
            _coal_to = st.date_input("Do", value=_all_dates[-1],
                                     min_value=_all_dates[0], max_value=_all_dates[-1],
                                     key="coal_to")

        _cf = coal_df[(coal_df["date"] >= _coal_from) & (coal_df["date"] <= _coal_to)]

        # ── Unit selector ─────────────────────────────────────────────────────
        _cc_unit1, _cc_unit2 = st.columns([1, 4])
        with _cc_unit1:
            _show_pln_t = st.checkbox("PLN/Mg", value=False, key="coal_unit_mg")
        with _cc_unit2:
            st.caption("Domyślnie: PLN/GJ (energia) · Zaznacz aby zmienić na PLN/Mg (waga)")

        _unit_label = "PLN/Mg" if _show_pln_t else "PLN/GJ"
        _price_col = "pscmi_t" if _show_pln_t else "pscmi_q"

        # ── Chart data: limit to 12 months, sort for display ────────────────────
        _cf_chart = _cf.copy()
        if len(_cf_chart) > 12:
            _cf_chart = _cf_chart.tail(12)
        _cf_chart = _cf_chart.sort_values("date")

        # ── Chart ─────────────────────────────────────────────────────────────
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=_cf_chart["date"], y=_cf_chart[_price_col],
            name=_unit_label,
            marker=dict(color="#1565c0"),
            text=_cf_chart[_price_col].round(2),
            textposition="outside",
            textfont=dict(size=12, color="#1565c0"),
            hovertemplate="%{x|%m.%Y}  <b>%{y:.2f} " + _unit_label + "</b><extra></extra>",
        ))
        fig.update_layout(
            **CHART_THEME,
            title="PSCMI 1 — cena węgla energetycznego",
            xaxis=dict(title="", gridcolor="#eee"),
            yaxis=dict(title=_unit_label, gridcolor="#eee"),
            height=420, margin=dict(t=60, b=40, l=60, r=20),
            hovermode="x unified",
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True,
                        config={"displayModeBar": True,
                                "toImageButtonOptions": {"format": "png", "filename": "pscmi1", "scale": 2}})
        st.caption("Użyj ikony 📷 w pasku narzędzi wykresu, aby pobrać jako PNG.")

        # ── History table ─────────────────────────────────────────────────────
        with st.expander("Tabela historyczna"):
            _tbl = _cf.copy().sort_values("date", ascending=False)
            _tbl["date"] = _tbl["date"].apply(lambda d: d.strftime("%m.%Y"))
            _tbl = _tbl.rename(columns={"date": "Miesiąc", "pscmi_t": "PLN/T", "pscmi_q": "PLN/GJ"})
            _tbl["PLN/T"]  = _tbl["PLN/T"].round(2)
            _tbl["PLN/GJ"] = _tbl["PLN/GJ"].round(2)
            st.dataframe(_tbl, use_container_width=True, hide_index=True)
    else:
        st.info("Brak danych PSCMI. Wgraj plik CSV poniżej.")

    # ── Upload CSV ────────────────────────────────────────────────────────────
    st.divider()
    st.subheader("Aktualizacja danych")
    st.caption("Pobierz CSV z polskirynekwegla.pl (format: Date, PSCMI 1/T, PSCMI 1/Q) i wgraj poniżej.")
    _uploaded = st.file_uploader("Wybierz plik CSV", type=["csv"], key="coal_upload")
    if _uploaded is not None:
        try:
            import io as _io
            _raw = pd.read_csv(_io.BytesIO(_uploaded.read()))
            _raw.columns = ["date_str", "pscmi_t", "pscmi_q"]

            def _parse_month(s):
                m, y = str(s).split(".")
                return date(int(y), int(m), 1)

            _raw["date"] = _raw["date_str"].map(_parse_month)
            _raw = _raw[["date", "pscmi_t", "pscmi_q"]]
            _raw["pscmi_t"] = pd.to_numeric(_raw["pscmi_t"], errors="coerce")
            _raw["pscmi_q"] = pd.to_numeric(_raw["pscmi_q"], errors="coerce")
            _raw = _raw.dropna(subset=["pscmi_t"]).sort_values("date").reset_index(drop=True)

            # Convert dates to datetime for merge compatibility
            _raw["date"] = pd.to_datetime(_raw["date"])
            if not coal_df.empty:
                coal_df_temp = coal_df.copy()
                coal_df_temp["date"] = pd.to_datetime(coal_df_temp["date"])
                _merged = (
                    pd.concat([coal_df_temp, _raw], ignore_index=True)
                    .sort_values("date")
                    .drop_duplicates("date", keep="last")
                    .reset_index(drop=True)
                )
            else:
                _merged = _raw

            tmp = PSCMI_PATH + ".tmp"
            _merged.to_parquet(tmp, index=False)
            os.replace(tmp, PSCMI_PATH)
            load_pscmi.clear()
            st.success(f"Zapisano {len(_merged)} miesięcy ({_merged['date'].min().strftime('%m.%Y')} – {_merged['date'].max().strftime('%m.%Y')})")
            st.rerun()
        except Exception as _e:
            st.error(f"Błąd wczytywania pliku: {_e}")

    # ── Last upload timestamp ──────────────────────────────────────────────────
    st.divider()
    if os.path.exists(PSCMI_PATH):
        _mtime = os.path.getmtime(PSCMI_PATH)
        _last_upload = pd.Timestamp(_mtime, unit="s").to_pydatetime()
        st.caption(f"Ostatni upload: {_last_upload.strftime('%d.%m.%Y o %H:%M:%S')}")




def render_otf_ee():
    st.title("OTF / EE")
    st.caption("TGE OTF — settlement price (DKR) and volume by contract")

    _ee = load_otf_ee()

    if _ee.empty:
        st.warning("No EE data. Run the TGE OTF EE pipeline first.")
        if st.button("Update EE data", type="primary"):
            import sys as _sys
            _sys.path.insert(0, os.path.join(APP_DIR, "procedures"))
            from tge_otf_ee import run_pipeline as _ee_pipeline
            _lines = []
            with st.spinner("Downloading from TGE..."):
                _result = _ee_pipeline(app_dir=APP_DIR,
                                       log=lambda m: _lines.append(m))
            load_otf_ee.clear()
            if _result["status"] == "ok":
                st.success(_result["message"])
            else:
                st.error(_result["message"])
            with st.expander("Pipeline log"):
                st.text("\n".join(_lines))
            st.rerun()
        st.stop()

    # ── Year selector + hide expired ─────────────────────────────────────────
    _cur_yr_ee = pd.Timestamp.now().year
    _ee_yr_opts = {
        f"{_cur_yr_ee} (Y)":     _cur_yr_ee,
        f"{_cur_yr_ee+1} (Y+1)": _cur_yr_ee + 1,
        f"{_cur_yr_ee+2} (Y+2)": _cur_yr_ee + 2,
        f"{_cur_yr_ee+3} (Y+3)": _cur_yr_ee + 3,
    }
    _ey1, _ey2 = st.columns([2, 2])
    with _ey1:
        _ee_yr_label = st.selectbox(
            "Delivery year", list(_ee_yr_opts.keys()), index=1, key="ee_del_year"
        )
        _ee_del_year = _ee_yr_opts[_ee_yr_label]
    with _ey2:
        _ee_hide_exp = st.checkbox("Hide expired products", value=True, key="ee_hide_expired")

    def _ee_parse_year(pname):
        try:
            yr = int(str(pname).rsplit("-", 1)[-1])
            return 2000 + yr if yr < 100 else yr
        except Exception:
            return None

    def _ee_is_expired(pname):
        import re as _re2
        import datetime as _dt_exp
        _now = pd.Timestamp.now()
        _pstr = str(pname)

        # Check week (W-27-26 → week 27, year 2026)
        _ww = _re2.search(r"W-(\d{1,2})-(\d{2})$", _pstr)
        if _ww:
            _week = int(_ww.group(1))
            _year = 2000 + int(_ww.group(2))
            try:
                _week_end = _dt_exp.date.fromisocalendar(_year, _week, 7)  # Sunday
                return _now.date() > _week_end
            except ValueError:
                return False

        # Check month (M01-26, M12-26, etc)
        for _part in _pstr.split("-"):
            _mm = _re2.match(r"M(\d{1,2})$", _part)
            if _mm:
                _month = int(_mm.group(1))
                _year_m = _ee_parse_year(_pstr)
                if _year_m and _year_m == _now.year:
                    return _month < _now.month
            # Check quarter (Q1-26, etc)
            _qq = _re2.match(r"Q(\d)$", _part)
            if _qq:
                _q = int(_qq.group(1))
                _year_q = _ee_parse_year(_pstr)
                if _year_q and _year_q == _now.year:
                    return _q < ((_now.month - 1) // 3 + 1)
        return False

    _ee["_del_year"] = _ee["product_name"].apply(_ee_parse_year)
    _ee_yr_filt = _ee[_ee["_del_year"] == _ee_del_year]
    if _ee_hide_exp:
        _ee_yr_filt = _ee_yr_filt[~_ee_yr_filt["product_name"].apply(_ee_is_expired)]

    # ── Controls ──────────────────────────────────────────────────────────────
    _ec1, _ec2, _ec3 = st.columns([1.5, 2, 1])

    _ee_types_avail = sorted(_ee_yr_filt["product_type"].dropna().unique())

    with _ec1:
        _ee_types_sel = st.multiselect(
            "Product type",
            options=_ee_types_avail,
            default=[t for t in ["Y", "Q", "M"] if t in _ee_types_avail],
            key="ee_types",
        )

    with _ec2:
        _ee_segments = sorted(_ee_yr_filt["segment"].dropna().unique()) if "segment" in _ee_yr_filt.columns else []
        _ee_seg_default = ["BASE"] if "BASE" in _ee_segments else (_ee_segments[:1] if _ee_segments else [])
        _ee_seg_sel  = st.multiselect("Segment", options=_ee_segments,
                                       default=_ee_seg_default, key="ee_segment")

    with _ec3:
        _ee_only_traded = st.checkbox("Only traded days", value=False, key="ee_liquidity")

    _ee_contracts = sorted(
        _ee_yr_filt[
            (_ee_yr_filt["product_type"].isin(_ee_types_sel)) &
            (_ee_yr_filt["segment"].isin(_ee_seg_sel))
        ]["product_name"].unique()
    ) if _ee_types_sel and _ee_seg_sel else []

    _ee_end_def  = _ee["date"].max().date()
    _ee_min_date = _ee["date"].min().date()

    if "ee_date_from" not in st.session_state:
        st.session_state["ee_date_from"] = (_ee["date"].max() - pd.Timedelta(days=14)).date()
    if "ee_date_to" not in st.session_state:
        st.session_state["ee_date_to"] = _ee_end_def
    if st.session_state["ee_date_from"] < _ee_min_date:
        st.session_state["ee_date_from"] = _ee_min_date
    if st.session_state["ee_date_to"] > _ee_end_def:
        st.session_state["ee_date_to"] = _ee_end_def

    _ep1, _ep2, _ep3, _ep4, _ep5, _ep6 = st.columns(6)
    for _pcol, _plbl, _pdays in zip(
        [_ep1, _ep2, _ep3, _ep4, _ep5, _ep6],
        ["1W", "1M", "3M", "6M", "1Y", "All"],
        [7, 30, 90, 180, 365, None],
    ):
        with _pcol:
            if st.button(_plbl, key=f"ee_preset_{_plbl}"):
                st.session_state["ee_date_to"]   = _ee_end_def
                st.session_state["ee_date_from"] = (
                    (_ee["date"].max() - pd.Timedelta(days=_pdays)).date() if _pdays else _ee_min_date
                )
                st.rerun()

    _ed1, _ed2 = st.columns(2)
    with _ed1:
        st.date_input("From", min_value=_ee_min_date, max_value=_ee_end_def, key="ee_date_from")
    with _ed2:
        st.date_input("To",   min_value=_ee_min_date, max_value=_ee_end_def, key="ee_date_to")

    # Contract selector on its own row (can be wide)
    _ee_contract = st.selectbox("Contract", options=_ee_contracts, key="ee_contract")

    if not _ee_contract:
        st.info("No contracts match selected filters.")
        st.stop()

    # ── Filter ────────────────────────────────────────────────────────────────
    _ee_from = pd.Timestamp(st.session_state["ee_date_from"])
    _ee_to   = pd.Timestamp(st.session_state["ee_date_to"])

    _dfee = _ee[
        (_ee["product_name"] == _ee_contract) &
        (_ee["date"] >= _ee_from) &
        (_ee["date"] <= _ee_to)
    ].copy()

    if _ee_only_traded:
        _dfee = _dfee[_dfee["is_traded"]]

    _dfee = _dfee.sort_values("date").reset_index(drop=True)

    if _dfee.empty:
        st.info("No data for selected contract and date range.")
        st.stop()

    # ── Chart ─────────────────────────────────────────────────────────────────
    _fig_ee = go.Figure()

    _fig_ee.add_trace(go.Scatter(
        x=_dfee["date"],
        y=_dfee["price"],
        mode="lines+markers+text",
        name="DKR (PLN/MWh)",
        line=dict(color="#2a9d8f", width=2),
        marker=dict(size=5),
        text=_dfee["price"].apply(lambda v: f"{v:.1f}" if pd.notna(v) else ""),
        textposition="top center",
        textfont=dict(size=12, color="#2a9d8f"),
        yaxis="y1",
    ))

    _fig_ee.add_trace(go.Bar(
        x=_dfee["date"],
        y=_dfee["quantity_mw"],
        name="Volume (MW)",
        marker_color="rgba(100,149,237,0.3)",
        yaxis="y2",
    ))

    # Weekly separators
    for _i in range(1, len(_dfee)):
        if _dfee.loc[_i-1, "date"].weekday() == 4 and _dfee.loc[_i, "date"].weekday() == 0:
            _fig_ee.add_vline(
                x=_dfee.loc[_i, "date"],
                line_dash="dash", line_color="#aaa",
                line_width=1, opacity=0.5,
            )

    _fig_ee.update_layout(
        **CHART_THEME,
        title=f"{_ee_contract} — DKR price & volume",
        xaxis=dict(title="Date", gridcolor="#eee",
                   rangebreaks=[dict(bounds=["sat", "mon"])]),
        yaxis=dict(title="DKR (PLN/MWh)", gridcolor="#eee"),
        yaxis2=dict(title="Volume (MW)", overlaying="y", side="right", showgrid=False),
        legend=dict(orientation="h", y=1.08),
        height=500,
        hovermode="x unified",
    )

    st.plotly_chart(_fig_ee, use_container_width=True)
    st.caption(f"{len(_dfee)} trading days · {_dfee['date'].min().date()} to {_dfee['date'].max().date()}")

    st.divider()
    if st.button("Update EE data", key="ee_update_btn"):
        import sys as _sys
        _sys.path.insert(0, os.path.join(APP_DIR, "procedures"))
        from tge_otf_ee import run_pipeline as _ee_pipeline
        _lines = []
        with st.spinner("Downloading from TGE..."):
            _result = _ee_pipeline(app_dir=APP_DIR,
                                   log=lambda m: _lines.append(m))
        load_otf_ee.clear()
        if _result["status"] == "ok":
            st.success(_result["message"])
        else:
            st.error(_result["message"])
        with st.expander("Pipeline log"):
            st.text("\n".join(_lines))
        st.rerun()




def render_cds():
    import json as _json_cds

    st.title("CurrentCDS")
    st.caption("CDS dla bieżących produktów OTF EE na TGE")

    # ── Load data ─────────────────────────────────────────────────────────────
    _otf = pd.read_parquet(OTF_EE_PATH)
    _otf["date"] = pd.to_datetime(_otf["date"]).dt.date
    _otf["dkr"]  = pd.to_numeric(_otf["dkr"], errors="coerce")
    _otf = _otf[_otf["product_type"].isin(["M", "Q", "Y"])].dropna(subset=["dkr"])

    _coal_df = load_pscmi()
    _ets_df  = load_ets()
    _fx_df   = load_eurpln()

    if _otf.empty or _coal_df.empty or _ets_df.empty or _fx_df.empty:
        st.warning("Brak danych — sprawdź PSCMI, ETS i OTF EE.")
        st.stop()

    # ── Extract delivery year from product_name ───────────────────────────────
    def _delivery_year(pname):
        try:
            last = pname.rsplit("-", 1)[-1]
            yr = int(last)
            return 2000 + yr if yr < 100 else yr
        except Exception:
            return None

    _otf["delivery_year"] = _otf["product_name"].apply(_delivery_year)
    _otf = _otf.dropna(subset=["delivery_year"])
    _otf["delivery_year"] = _otf["delivery_year"].astype(int)

    # ── Available years ───────────────────────────────────────────────────────
    _avail_years = sorted(_otf["delivery_year"].unique())

    # ── Filters ───────────────────────────────────────────────────────────────
    _f1, _f2, _f3 = st.columns(3)
    with _f1:
        _sel_year = st.selectbox("Rok dostawy", _avail_years,
                                 index=_avail_years.index(2026) if 2026 in _avail_years else 0,
                                 key="ccds_year")
    with _f2:
        _sel_seg = st.multiselect("Strefa", ["BASE", "PEAK5", "OFFPEAK"], default=["BASE"], key="ccds_seg")
    with _f3:
        _sel_period = st.multiselect("Okres", ["M", "Q", "Y"], default=["M", "Q", "Y"],
                                     key="ccds_period")

    # ── Find last date for selected filters ───────────────────────────────────
    if not _sel_seg or not _sel_period:
        st.info("Wybierz co najmniej jedną strefę i jeden okres.")
        st.stop()

    _filtered_all = _otf[
        (_otf["delivery_year"] == _sel_year) &
        (_otf["segment"].isin(_sel_seg)) &
        (_otf["product_type"].isin(_sel_period))
    ]
    if _filtered_all.empty:
        st.info(f"Brak produktów dla roku {_sel_year}.")
        st.stop()

    _last_date = _filtered_all["date"].max()
    _filtered = _filtered_all[_filtered_all["date"] == _last_date].sort_values("product_name")

    # ── Load CDS params ───────────────────────────────────────────────────────
    _p = {}
    if os.path.exists(CDS_PARAMS_PATH):
        with open(CDS_PARAMS_PATH, "r") as _f:
            _p = _json_cds.load(_f)

    _transport   = float(_p.get("transport_pln_gj", 10.0))
    _year_adj    = _p.get("year_adjustments", {})
    _blocks_cfg  = _p.get("blocks", {})

    _pscmi_q     = float(_coal_df["pscmi_q"].iloc[-1])
    _coal_base   = _pscmi_q + _transport

    _eurpln      = float(_fx_df["rate"].iloc[-1])

    _ets26_row   = _ets_df[_ets_df["symbol"] == "CKZ26.F"].sort_values("date")
    _ets26       = float(_ets26_row["settlement"].iloc[-1]) if not _ets26_row.empty else 0.0

    # Map absolute delivery year → relative key Y / Y+1 / Y+2 / Y+3
    _cur_year  = pd.Timestamp.now().year
    _yr_diff   = _sel_year - _cur_year
    _yr_keys   = {0: "Y", 1: "Y+1", 2: "Y+2", 3: "Y+3"}
    _yr_key    = _yr_keys.get(_yr_diff, f"Y+{_yr_diff}" if _yr_diff > 0 else "Y")
    _adj       = _year_adj.get(_yr_key, {"ets_delta": 0.0, "swap_delta": 0.0, "coal_delta": 0.0})

    _ets_price  = _ets26  + float(_adj.get("ets_delta",  0.0))
    _eff_fx     = _eurpln + float(_adj.get("swap_delta", 0.0))
    _coal_total = _coal_base + float(_adj.get("coal_delta", 0.0))
    _ets_label  = f"ETS DEC26 ({_yr_key}): {_ets_price:.2f} EUR/t"

    # ── Header info ───────────────────────────────────────────────────────────
    _coal_delta_val = float(_adj.get("coal_delta", 0.0))
    _coal_display = (
        f"{_pscmi_q:.2f} + {_transport:.2f} + {_coal_delta_val:.2f} = {_coal_total:.2f} PLN/GJ"
        if _coal_delta_val != 0.0
        else f"{_pscmi_q:.2f} + {_transport:.2f} = {_coal_total:.2f} PLN/GJ"
    )
    st.markdown(
        f"<div style='font-size:1.5rem; font-weight:700; margin-bottom:4px;'>"
        f"CDSy dla produktów notowanych w: {_last_date.strftime('%d.%m.%Y')}"
        f"</div>"
        f"<div style='font-size:0.9rem; color:#555;'>"
        f"{_ets_label} &nbsp;·&nbsp; EUR/PLN: {_eff_fx:.4f} &nbsp;·&nbsp; "
        f"Węgiel: {_coal_display}"
        f"</div>",
        unsafe_allow_html=True,
    )
    st.markdown("<div style='margin-bottom:12px'></div>", unsafe_allow_html=True)

    # ── Build CDS table ───────────────────────────────────────────────────────
    BLOCK_NAMES = ["1000 MW", "500 MW", "200 MW"]
    _block_defaults = {
        "1000 MW": {"efficiency_pct": 45.0, "emission_tco2_mwh": 0.82, "other_costs_pln_mwh": 0.0},
        "500 MW":  {"efficiency_pct": 39.0, "emission_tco2_mwh": 0.95, "other_costs_pln_mwh": 0.0},
        "200 MW":  {"efficiency_pct": 34.0, "emission_tco2_mwh": 1.10, "other_costs_pln_mwh": 0.0},
    }

    _rows = []
    for idx, row in enumerate(_filtered.itertuples(), 1):
        _price = float(row.dkr)
        _cds_vals = {}
        for bname in BLOCK_NAMES:
            _b    = _blocks_cfg.get(bname, _block_defaults[bname])
            _eff  = float(_b["efficiency_pct"]) / 100.0
            _em   = float(_b["emission_tco2_mwh"])
            _oth  = float(_b["other_costs_pln_mwh"])
            _coal_mwh = _coal_total * 3.6 / _eff
            _co2_mwh  = _ets_price * _eff_fx * _em
            _cost     = _coal_mwh + _co2_mwh + _oth
            _cds_vals[bname] = round(_price - _cost, 2)
        _rows.append({
            "LP":          idx,
            "Produkt":     row.product_name,
            "Cena":        round(_price, 2),
            "CDS 1000":    _cds_vals["1000 MW"],
            "CDS 500":     _cds_vals["500 MW"],
            "CDS 200":     _cds_vals["200 MW"],
        })

    _df_cds = pd.DataFrame(_rows)

    def _color_cds(val):
        if not isinstance(val, (int, float)):
            return ""
        return "color: #2dc653; font-weight:600" if val > 0 else "color: #e63946; font-weight:600"

    _cds_cols = ["CDS 1000", "CDS 500", "CDS 200"]
    _fmt = {c: "{:.2f}" for c in ["Cena"] + _cds_cols}
    st.dataframe(
        _df_cds.style.format(_fmt).applymap(_color_cds, subset=_cds_cols),
        use_container_width=True, hide_index=True,
    )

    with st.expander("Parametry kalkulacji"):
        _cost_rows = []
        for bname in BLOCK_NAMES:
            _b   = _blocks_cfg.get(bname, _block_defaults[bname])
            _eff = float(_b["efficiency_pct"]) / 100.0
            _em  = float(_b["emission_tco2_mwh"])
            _oth = float(_b["other_costs_pln_mwh"])
            _cost_rows.append({
                "Blok":               bname,
                "Sprawność (%)":      _b["efficiency_pct"],
                "Emisyjność (tCO₂/MWh)": _em,
                "Koszt węgla (PLN/MWh)": round(_coal_total * 3.6 / _eff, 2),
                "Koszt CO₂ (PLN/MWh)":  round(_ets_price * _eff_fx * _em, 2),
                "Inne (PLN/MWh)":        _oth,
                "Łączny koszt (PLN/MWh)": round(_coal_total * 3.6 / _eff + _ets_price * _eff_fx * _em + _oth, 2),
            })
        st.dataframe(pd.DataFrame(_cost_rows).set_index("Blok"), use_container_width=True)
        st.caption("Zmień parametry na stronie CDS (Admin → CDS).")




def render_ccs():
    import json as _json_ccs

    st.title("CurrentCCS")
    st.caption("Clean Spark Spread — bieżące produkty OTF EE vs. OTF Gas na TGE")

    # ── Load data ─────────────────────────────────────────────────────────────
    _otf_ee  = pd.read_parquet(OTF_EE_PATH)
    _otf_ee["date"] = pd.to_datetime(_otf_ee["date"]).dt.date
    _otf_ee["dkr"]  = pd.to_numeric(_otf_ee["dkr"], errors="coerce")
    _otf_ee = _otf_ee[_otf_ee["product_type"].isin(["M", "Q", "Y"])].dropna(subset=["dkr"])

    _otf_gas = load_otf_gas()
    _ets_df  = load_ets()
    _fx_df   = load_eurpln()

    if _otf_ee.empty or _otf_gas.empty or _ets_df.empty or _fx_df.empty:
        st.warning("Brak danych — sprawdź OTF EE, OTF Gas, ETS i EUR/PLN.")
        st.stop()

    # ── Extract delivery year from product_name ───────────────────────────────
    def _ccs_year(pname):
        try:
            last = pname.rsplit("-", 1)[-1]
            yr = int(last)
            return 2000 + yr if yr < 100 else yr
        except Exception:
            return None

    _otf_ee["delivery_year"] = _otf_ee["product_name"].apply(_ccs_year)
    _otf_ee = _otf_ee.dropna(subset=["delivery_year"])
    _otf_ee["delivery_year"] = _otf_ee["delivery_year"].astype(int)

    _avail_years = sorted(_otf_ee["delivery_year"].unique())

    # ── Filters ───────────────────────────────────────────────────────────────
    _cf1, _cf2, _cf3 = st.columns(3)
    with _cf1:
        _ccs_year_sel = st.selectbox("Rok dostawy", _avail_years,
                                     index=_avail_years.index(2026) if 2026 in _avail_years else 0,
                                     key="cccs_year")
    with _cf2:
        _ccs_seg = st.multiselect("Strefa", ["BASE", "PEAK5", "OFFPEAK"], default=["BASE"], key="cccs_seg")
    with _cf3:
        _ccs_period = st.multiselect("Okres", ["M", "Q", "Y"], default=["M", "Q", "Y"],
                                     key="cccs_period")

    if not _ccs_seg or not _ccs_period:
        st.info("Wybierz co najmniej jedną strefę i jeden okres.")
        st.stop()

    _ccs_filtered_all = _otf_ee[
        (_otf_ee["delivery_year"] == _ccs_year_sel) &
        (_otf_ee["segment"].isin(_ccs_seg)) &
        (_otf_ee["product_type"].isin(_ccs_period))
    ]
    if _ccs_filtered_all.empty:
        st.info(f"Brak produktów EE dla roku {_ccs_year_sel}.")
        st.stop()

    _ccs_last_date = _ccs_filtered_all["date"].max()
    _ccs_filtered  = _ccs_filtered_all[_ccs_filtered_all["date"] == _ccs_last_date].sort_values("product_name")

    # ── Gas contract selector ─────────────────────────────────────────────────
    _gas_yr_str  = str(_ccs_year_sel)[-2:]
    _gas_year_contracts = (
        _otf_gas[_otf_gas["Kontrakt"].str.contains(_gas_yr_str, na=False)]
        ["Kontrakt"].unique().tolist()
    )
    _gas_year_contracts = sorted(_gas_year_contracts) if _gas_year_contracts else sorted(_otf_gas["Kontrakt"].unique().tolist())

    _gas_sel_contract = st.selectbox(
        "Kontrakt gazowy (cena referencyjna)",
        _gas_year_contracts,
        key="cccs_gas_contract",
    )

    _gas_last_row = (
        _otf_gas[_otf_gas["Kontrakt"] == _gas_sel_contract]
        .sort_values("date")
        .iloc[-1]
    )
    _gas_price_pln    = float(_gas_last_row["price"])
    _gas_price_date   = pd.Timestamp(_gas_last_row["date"]).date()

    # ── Load CCS + CDS params ─────────────────────────────────────────────────
    _ccs_p = {}
    if os.path.exists(CCS_PARAMS_PATH):
        with open(CCS_PARAMS_PATH, "r") as _f:
            _ccs_p = _json_ccs.load(_f)

    _cds_p = {}
    if os.path.exists(CDS_PARAMS_PATH):
        with open(CDS_PARAMS_PATH, "r") as _f:
            _cds_p = _json_ccs.load(_f)

    _ccs_year_adj = _cds_p.get("year_adjustments", {})
    _tech_cfg   = _ccs_p.get("technologies", {})

    _eurpln     = float(_fx_df["rate"].iloc[-1])
    _ets26_row  = _ets_df[_ets_df["symbol"] == "CKZ26.F"].sort_values("date")
    _ets26      = float(_ets26_row["settlement"].iloc[-1]) if not _ets26_row.empty else 0.0

    # Map absolute delivery year → relative key Y / Y+1 / Y+2 / Y+3
    _ccs_cur_year = pd.Timestamp.now().year
    _ccs_yr_diff  = _ccs_year_sel - _ccs_cur_year
    _ccs_yr_keys  = {0: "Y", 1: "Y+1", 2: "Y+2", 3: "Y+3"}
    _ccs_yr_key   = _ccs_yr_keys.get(_ccs_yr_diff, f"Y+{_ccs_yr_diff}" if _ccs_yr_diff > 0 else "Y")
    _ccs_adj      = _ccs_year_adj.get(_ccs_yr_key, {"ets_delta": 0.0, "swap_delta": 0.0, "coal_delta": 0.0})

    _ccs_ets_price = _ets26  + float(_ccs_adj.get("ets_delta",  0.0))
    _ccs_eff_fx    = _eurpln + float(_ccs_adj.get("swap_delta", 0.0))
    _ccs_ets_label = f"ETS DEC26 ({_ccs_yr_key}): {_ccs_ets_price:.2f} EUR/t"

    # ── Header info ───────────────────────────────────────────────────────────
    st.markdown(
        f"<div style='font-size:1.5rem; font-weight:700; margin-bottom:4px;'>"
        f"CCS dla produktów notowanych w: {_ccs_last_date.strftime('%d.%m.%Y')}"
        f"</div>"
        f"<div style='font-size:0.9rem; color:#555;'>"
        f"{_ccs_ets_label} &nbsp;·&nbsp; EUR/PLN: {_ccs_eff_fx:.4f} &nbsp;·&nbsp; "
        f"Gaz ({_gas_sel_contract}): {_gas_price_pln:.2f} PLN/MWh ({_gas_price_date})"
        f"</div>",
        unsafe_allow_html=True,
    )
    st.markdown("<div style='margin-bottom:12px'></div>", unsafe_allow_html=True)

    # ── Build CCS table ───────────────────────────────────────────────────────
    CCS_TECH_NAMES = ["CCGT modern", "CCGT older", "OCGT"]
    _tech_defaults = {
        "CCGT modern": {"efficiency_pct": 60.0, "emission_tco2_mwh": 0.34, "other_costs_pln_mwh": 0.0},
        "CCGT older":  {"efficiency_pct": 54.0, "emission_tco2_mwh": 0.38, "other_costs_pln_mwh": 0.0},
        "OCGT":        {"efficiency_pct": 38.0, "emission_tco2_mwh": 0.54, "other_costs_pln_mwh": 0.0},
    }

    _ccs_rows = []
    for idx, row in enumerate(_ccs_filtered.itertuples(), 1):
        _price = float(row.dkr)
        _ccs_vals = {}
        for tname in CCS_TECH_NAMES:
            _t    = _tech_cfg.get(tname, _tech_defaults[tname])
            _eff  = float(_t["efficiency_pct"]) / 100.0
            _em   = float(_t["emission_tco2_mwh"])
            _oth  = float(_t["other_costs_pln_mwh"])
            _gas_mwh  = _gas_price_pln / _eff
            _co2_mwh  = _ccs_ets_price * _ccs_eff_fx * _em
            _cost     = _gas_mwh + _co2_mwh + _oth
            _ccs_vals[tname] = round(_price - _cost, 2)
        _ccs_rows.append({
            "LP":            idx,
            "Produkt":       row.product_name,
            "Cena":          round(_price, 2),
            "CCS CCGT mod.": _ccs_vals["CCGT modern"],
            "CCS CCGT st.":  _ccs_vals["CCGT older"],
            "CCS OCGT":      _ccs_vals["OCGT"],
        })

    _df_ccs_tbl = pd.DataFrame(_ccs_rows)

    def _color_ccs(val):
        if not isinstance(val, (int, float)):
            return ""
        return "color: #2dc653; font-weight:600" if val > 0 else "color: #e63946; font-weight:600"

    _ccs_spread_cols = ["CCS CCGT mod.", "CCS CCGT st.", "CCS OCGT"]
    _ccs_fmt = {c: "{:.2f}" for c in ["Cena"] + _ccs_spread_cols}
    st.dataframe(
        _df_ccs_tbl.style.format(_ccs_fmt).applymap(_color_ccs, subset=_ccs_spread_cols),
        use_container_width=True, hide_index=True,
    )

    with st.expander("Parametry kalkulacji"):
        _ccs_cost_rows = []
        for tname in CCS_TECH_NAMES:
            _t   = _tech_cfg.get(tname, _tech_defaults[tname])
            _eff = float(_t["efficiency_pct"]) / 100.0
            _em  = float(_t["emission_tco2_mwh"])
            _oth = float(_t["other_costs_pln_mwh"])
            _ccs_cost_rows.append({
                "Technologia":              tname,
                "Sprawność (%)":            _t["efficiency_pct"],
                "Emisyjność (tCO₂/MWh)":   _em,
                "Koszt gazu (PLN/MWh)":     round(_gas_price_pln / _eff, 2),
                "Koszt CO₂ (PLN/MWh)":      round(_ccs_ets_price * _ccs_eff_fx * _em, 2),
                "Inne (PLN/MWh)":           _oth,
                "Łączny koszt (PLN/MWh)":   round(_gas_price_pln / _eff + _ccs_ets_price * _ccs_eff_fx * _em + _oth, 2),
            })
        st.dataframe(pd.DataFrame(_ccs_cost_rows).set_index("Technologia"), use_container_width=True)
        st.caption("Zmień parametry na stronie CCS (Admin → CCS).")




def render_otf_gas():
    st.title("OTF / Gas")
    st.caption("TGE OTF — settlement price (DKR) and volume by contract")

    _gas = load_otf_gas()

    if _gas.empty:
        st.warning("No gas data. Run the TGE OTF Gas pipeline first.")
        st.stop()

    # ── Year selector + hide expired ─────────────────────────────────────────
    _cur_yr_gas = pd.Timestamp.now().year
    _gas_yr_opts = {
        f"{_cur_yr_gas} (Y)":     _cur_yr_gas,
        f"{_cur_yr_gas+1} (Y+1)": _cur_yr_gas + 1,
        f"{_cur_yr_gas+2} (Y+2)": _cur_yr_gas + 2,
        f"{_cur_yr_gas+3} (Y+3)": _cur_yr_gas + 3,
    }
    _gy1, _gy2 = st.columns([2, 2])
    with _gy1:
        _gas_yr_label = st.selectbox(
            "Delivery year", list(_gas_yr_opts.keys()), index=1, key="gas_del_year"
        )
        _gas_del_year = _gas_yr_opts[_gas_yr_label]
    with _gy2:
        _gas_hide_exp = st.checkbox("Hide expired products", value=True, key="gas_hide_expired")

    def _gas_parse_year(pname):
        try:
            yr = int(str(pname).rsplit("-", 1)[-1])
            return 2000 + yr if yr < 100 else yr
        except Exception:
            return None

    def _gas_is_expired(pname):
        import re as _re3
        _now = pd.Timestamp.now()
        for _part in str(pname).split("-"):
            _mm = _re3.match(r"M(\d{1,2})$", _part)
            if _mm:
                return int(_mm.group(1)) < _now.month
            _qq = _re3.match(r"Q(\d)$", _part)
            if _qq:
                return int(_qq.group(1)) < ((_now.month - 1) // 3 + 1)
        return False

    _gas["_del_year"] = _gas["Kontrakt"].apply(_gas_parse_year)
    _gas_yr_filt = _gas[_gas["_del_year"] == _gas_del_year]
    if _gas_hide_exp and _gas_del_year == _cur_yr_gas:
        _gas_yr_filt = _gas_yr_filt[~_gas_yr_filt["Kontrakt"].apply(_gas_is_expired)]

    # ── Controls ──────────────────────────────────────────────────────────────
    _gc1, _gc2, _gc3 = st.columns([1.5, 2, 1])

    with _gc1:
        _types_sel = st.multiselect(
            "Product type",
            options=["Y", "S", "Q", "M", "W"],
            default=["Y", "Q", "M"],
            key="gas_types",
        )

    _contracts_avail = sorted(
        _gas_yr_filt[_gas_yr_filt["product_type"].isin(_types_sel)]["Kontrakt"].unique()
    ) if _types_sel else []

    with _gc2:
        _contract = st.selectbox(
            "Contract",
            options=_contracts_avail,
            key="gas_contract",
        )

    with _gc3:
        _only_traded = st.checkbox("Only traded days", value=False, key="gas_liquidity")

    if not _contract:
        st.info("No contracts match selected product types.")
        st.stop()

    _gas_end_def  = _gas["date"].max().date()
    _gas_min_date = _gas["date"].min().date()

    if "gas_date_from" not in st.session_state:
        st.session_state["gas_date_from"] = (_gas["date"].max() - pd.Timedelta(days=14)).date()
    if "gas_date_to" not in st.session_state:
        st.session_state["gas_date_to"] = _gas_end_def
    if st.session_state["gas_date_from"] < _gas_min_date:
        st.session_state["gas_date_from"] = _gas_min_date
    if st.session_state["gas_date_to"] > _gas_end_def:
        st.session_state["gas_date_to"] = _gas_end_def

    _gp1, _gp2, _gp3, _gp4, _gp5, _gp6 = st.columns(6)
    for _pcol, _plbl, _pdays in zip(
        [_gp1, _gp2, _gp3, _gp4, _gp5, _gp6],
        ["1W", "1M", "3M", "6M", "1Y", "All"],
        [7, 30, 90, 180, 365, None],
    ):
        with _pcol:
            if st.button(_plbl, key=f"gas_preset_{_plbl}"):
                st.session_state["gas_date_to"]   = _gas_end_def
                st.session_state["gas_date_from"] = (
                    (_gas["date"].max() - pd.Timedelta(days=_pdays)).date() if _pdays else _gas_min_date
                )
                st.rerun()

    _gd1, _gd2 = st.columns(2)
    with _gd1:
        st.date_input("From", min_value=_gas_min_date, max_value=_gas_end_def, key="gas_date_from")
    with _gd2:
        st.date_input("To",   min_value=_gas_min_date, max_value=_gas_end_def, key="gas_date_to")

    # ── Filter ────────────────────────────────────────────────────────────────
    _g_from = pd.Timestamp(st.session_state["gas_date_from"])
    _g_to   = pd.Timestamp(st.session_state["gas_date_to"])

    _dfp = _gas[
        (_gas["Kontrakt"] == _contract) &
        (_gas["date"] >= _g_from) &
        (_gas["date"] <= _g_to)
    ].copy()

    if _only_traded:
        _dfp = _dfp[_dfp["is_traded"]]

    _dfp = _dfp.sort_values("date").reset_index(drop=True)

    if _dfp.empty:
        st.info("No data for selected contract and date range.")
        st.stop()

    # ── Chart ─────────────────────────────────────────────────────────────────
    _fig = go.Figure()

    # Price line (primary y-axis)
    _fig.add_trace(go.Scatter(
        x=_dfp["date"],
        y=_dfp["price"],
        mode="lines+markers+text",
        name="DKR (PLN/MWh)",
        line=dict(color="#e63946", width=2),
        marker=dict(size=5),
        text=_dfp["price"].apply(lambda v: f"{v:.1f}" if pd.notna(v) else ""),
        textposition="top center",
        textfont=dict(size=12, color="#e63946"),
        yaxis="y1",
    ))

    # Volume bars (secondary y-axis)
    _fig.add_trace(go.Bar(
        x=_dfp["date"],
        y=_dfp["quantity_mw"],
        name="Volume (MW)",
        marker_color="rgba(100,149,237,0.3)",
        yaxis="y2",
    ))

    # Weekly separator lines
    for _i in range(1, len(_dfp)):
        if _dfp.loc[_i-1, "date"].weekday() == 4 and _dfp.loc[_i, "date"].weekday() == 0:
            _fig.add_vline(
                x=_dfp.loc[_i, "date"],
                line_dash="dash",
                line_color="#aaa",
                line_width=1,
                opacity=0.5,
            )

    _fig.update_layout(
        **CHART_THEME,
        title=f"{_contract} — DKR price & volume",
        xaxis=dict(title="Date", gridcolor="#eee",
                   rangebreaks=[dict(bounds=["sat", "mon"])]),
        yaxis=dict(title="DKR (PLN/MWh)", gridcolor="#eee"),
        yaxis2=dict(title="Volume (MW)", overlaying="y", side="right",
                    showgrid=False),
        legend=dict(orientation="h", y=1.08),
        height=500,
        hovermode="x unified",
    )

    st.plotly_chart(_fig, use_container_width=True)
    st.caption(f"{len(_dfp)} trading days · {_dfp['date'].min().date()} to {_dfp['date'].max().date()}")




def render_compare():
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates

        st.title("Compare")
        st.caption("Forward price comparison — Energy vs Gas vs ETS (PLN/MWh)")

        _cmp_ee  = load_otf_ee()
        _cmp_gas = load_otf_gas()
        _cmp_ets = load_ets()
        _cmp_fx  = load_eurpln()

        if _cmp_ee.empty or _cmp_gas.empty or _cmp_ets.empty or _cmp_fx.empty:
            st.warning("Missing data — check OTF EE, OTF Gas, ETS and EUR/PLN files.")
            st.stop()

        # ── Row 1: Year + date range ──────────────────────────────────────────────
        _cmp_cur_yr = pd.Timestamp.now().year
        _cmp_yr_opts = {
            f"{_cmp_cur_yr} (Y)":     _cmp_cur_yr,
            f"{_cmp_cur_yr+1} (Y+1)": _cmp_cur_yr + 1,
            f"{_cmp_cur_yr+2} (Y+2)": _cmp_cur_yr + 2,
            f"{_cmp_cur_yr+3} (Y+3)": _cmp_cur_yr + 3,
        }
        _cr1, _cr2, _cr3 = st.columns([2, 1.5, 1.5])
        with _cr1:
            _cmp_yr_lbl = st.selectbox(
                "Delivery year", list(_cmp_yr_opts.keys()), index=1, key="cmp_year"
            )
            _cmp_yr = _cmp_yr_opts[_cmp_yr_lbl]
        with _cr2:
            _cmp_from = st.date_input(
                "From", value=date.today() - timedelta(days=30), key="cmp_from"
            )
        with _cr3:
            _cmp_to = st.date_input(
                "To", value=date.today(), key="cmp_to"
            )

        # ── Parse delivery year helper ─────────────────────────────────────────────
        def _cmp_parse_yr(pname):
            try:
                yr = int(str(pname).rsplit("-", 1)[-1])
                return 2000 + yr if yr < 100 else yr
            except Exception:
                return None

        # ── Row 2: product filters ────────────────────────────────────────────────
        _cmp_ee["_cyr"] = _cmp_ee["product_name"].apply(_cmp_parse_yr)
        _cmp_gas["_cyr"] = _cmp_gas["Kontrakt"].apply(_cmp_parse_yr)

        _ets_syms_all = sorted(_cmp_ets["symbol"].unique())
        _ets_sym_def  = f"CKZ{str(_cmp_yr)[-2:]}.F"
        _ets_def_idx  = _ets_syms_all.index(_ets_sym_def) if _ets_sym_def in _ets_syms_all else 0

        _cf1, _cf2, _cf3, _cf4, _cf5 = st.columns([1.4, 1.2, 1.2, 1.8, 1.1])
        with _cf1:
            _cmp_ee_seg = st.selectbox(
                "Energy segment", ["BASE", "PEAK5", "OFFPEAK"], index=0, key="cmp_ee_seg"
            )
        with _cf2:
            _cmp_ee_period = st.selectbox(
                "Energy period", ["Y", "Q", "M"], index=0, key="cmp_ee_period"
            )
        with _cf3:
            _cmp_gas_period = st.selectbox(
                "Gas period", ["Y", "S", "Q", "M", "W"], index=0, key="cmp_gas_period"
            )
        with _cf4:
            _cmp_ets_sym = st.selectbox(
                "ETS contract", _ets_syms_all, index=_ets_def_idx, key="cmp_ets_sym"
            )
        with _cf5:
            _cmp_mult = st.number_input(
                "ETS multiplier", value=1.0, min_value=0.0, max_value=10.0,
                step=0.01, format="%.2f", key="cmp_ets_mult",
                help="Emission factor tCO₂/MWh — scales ETS to PLN/MWh equivalent"
            )

        # ── Product combos (filtered by year + segment/period) ────────────────────
        _ee_filt = _cmp_ee[
            (_cmp_ee["_cyr"] == _cmp_yr) &
            (_cmp_ee["segment"] == _cmp_ee_seg) &
            (_cmp_ee["product_type"] == _cmp_ee_period)
        ]
        _ee_prods = sorted(_ee_filt["product_name"].unique())

        _gas_filt = _cmp_gas[
            (_cmp_gas["_cyr"] == _cmp_yr) &
            (_cmp_gas["product_type"] == _cmp_gas_period)
        ]
        _gas_prods = sorted(_gas_filt["Kontrakt"].unique())

        _pp1, _pp2 = st.columns(2)
        with _pp1:
            _cmp_ee_prod = st.selectbox(
                "Energy product", _ee_prods if _ee_prods else ["—"], key="cmp_ee_prod"
            )
        with _pp2:
            _cmp_gas_prod = st.selectbox(
                "Gas product", _gas_prods if _gas_prods else ["—"], key="cmp_gas_prod"
            )

        if _cmp_ee_prod == "—" or _cmp_gas_prod == "—":
            st.info(f"No products found for {_cmp_yr_lbl} with selected filters.")
            st.stop()

        # ── Build time series with date range filter ──────────────────────────────
        _cmp_from_ts = pd.Timestamp(_cmp_from)
        _cmp_to_ts   = pd.Timestamp(_cmp_to)

        _ee_ts = (
            _cmp_ee[_cmp_ee["product_name"] == _cmp_ee_prod][["date", "price"]]
            .dropna()
            .sort_values("date")
            .drop_duplicates("date")
            .rename(columns={"price": "Energy"})
        )
        _ee_ts["date"] = pd.to_datetime(_ee_ts["date"])
        _ee_ts = _ee_ts[(_ee_ts["date"] >= _cmp_from_ts) & (_ee_ts["date"] <= _cmp_to_ts)]

        _gas_ts = (
            _cmp_gas[_cmp_gas["Kontrakt"] == _cmp_gas_prod][["date", "price"]]
            .dropna()
            .sort_values("date")
            .drop_duplicates("date")
            .rename(columns={"price": "Gas"})
        )
        _gas_ts["date"] = pd.to_datetime(_gas_ts["date"])
        _gas_ts = _gas_ts[(_gas_ts["date"] >= _cmp_from_ts) & (_gas_ts["date"] <= _cmp_to_ts)]

        _ets_raw = (
            _cmp_ets[_cmp_ets["symbol"] == _cmp_ets_sym][["date", "settlement"]]
            .dropna()
            .sort_values("date")
            .drop_duplicates("date")
        )
        _ets_raw["date"] = pd.to_datetime(_ets_raw["date"])
        _fx_df_cmp = _cmp_fx[["date", "rate"]].copy()
        _fx_df_cmp["date"] = pd.to_datetime(_fx_df_cmp["date"])
        _ets_merged = _ets_raw.merge(_fx_df_cmp, on="date", how="left")
        _ets_merged["rate"] = _ets_merged["rate"].ffill()
        _ets_merged["ETS"] = _ets_merged["settlement"] * _ets_merged["rate"] * _cmp_mult
        _ets_ts = _ets_merged[["date", "ETS"]].dropna()
        _ets_ts = _ets_ts[(_ets_ts["date"] >= _cmp_from_ts) & (_ets_ts["date"] <= _cmp_to_ts)]

        _cmp_df = (
            _ee_ts
            .merge(_gas_ts, on="date", how="outer")
            .merge(_ets_ts, on="date", how="outer")
            .sort_values("date")
            .reset_index(drop=True)
        )

        if _cmp_df.empty or _cmp_df[["Energy", "Gas", "ETS"]].isna().all().all():
            st.info("No data for selected products and date range.")
            st.stop()

        _ets_legend = (
            f"ETS: {_cmp_ets_sym} × {_cmp_mult:.2f}"
            if _cmp_mult != 1.0
            else f"ETS: {_cmp_ets_sym}"
        )

        _tab1, _tab2 = st.tabs(["Absolute prices", "Normalized (price drivers)"])

        # ── Tab 1: Absolute prices ────────────────────────────────────────────────
        with _tab1:
            _fig1, _ax1 = plt.subplots(figsize=(13, 5))

            if _cmp_df["Energy"].notna().any():
                _ax1.plot(_cmp_df["date"], _cmp_df["Energy"],
                          color="#27ae60", linewidth=2, label=f"Energy: {_cmp_ee_prod}")
            if _cmp_df["Gas"].notna().any():
                _ax1.plot(_cmp_df["date"], _cmp_df["Gas"],
                          color="#f1c40f", linewidth=2, label=f"Gas: {_cmp_gas_prod}")
            if _cmp_df["ETS"].notna().any():
                _ax1.plot(_cmp_df["date"], _cmp_df["ETS"],
                          color="#222222", linewidth=1.8, linestyle="dotted", label=_ets_legend)

            _ax1.set_ylabel("PLN/MWh", fontsize=11)
            _ax1.set_title(
                f"Forward prices — {_cmp_yr_lbl}  ({_cmp_from} → {_cmp_to})",
                fontsize=13, fontweight="bold",
            )
            _ax1.xaxis.set_major_formatter(mdates.DateFormatter("%d %b %Y"))
            _ax1.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
            plt.setp(_ax1.xaxis.get_majorticklabels(), rotation=45, ha="right")
            _ax1.grid(True, color="#eeeeee", linewidth=0.8)
            _ax1.legend(loc="best", fontsize=10, framealpha=0.9)
            _ax1.spines["top"].set_visible(False)
            _ax1.spines["right"].set_visible(False)
            _fig1.tight_layout()
            st.pyplot(_fig1)
            plt.close(_fig1)

            with st.expander("Show data table"):
                _tbl1 = _cmp_df.copy()
                _tbl1["date"] = _tbl1["date"].dt.date
                for _c in ["Energy", "Gas", "ETS"]:
                    if _c in _tbl1.columns:
                        _tbl1[_c] = _tbl1[_c].round(2)
                st.dataframe(_tbl1, use_container_width=True, hide_index=True)

        # ── Tab 2: Normalized + correlation ──────────────────────────────────────
        with _tab2:
            st.markdown(
                """
    **How to read this chart**

    All three series are rebased to **100** at the first available date in the selected period.
    A value of 110 means the price has risen 10 % relative to that starting point.

    When the **Energy** line moves in parallel with **Gas**, gas is the dominant cost driver.
    When it tracks **ETS** (dotted black), carbon cost is leading the move.
    A divergence between Energy and both inputs suggests margin expansion or compression.

    The **Pearson R** table below quantifies the linear co-movement over the selected window
    (R close to 1 = strong positive correlation, close to 0 = no relationship).
                """
            )

            _norm_df = _cmp_df[["date", "Energy", "Gas", "ETS"]].copy().dropna(
                subset=["Energy", "Gas", "ETS"]
            )

            if _norm_df.empty:
                st.info("Not enough overlapping data to build the normalized chart.")
            else:
                _first = _norm_df.iloc[0]
                for _c in ["Energy", "Gas", "ETS"]:
                    if _first[_c] and _first[_c] != 0:
                        _norm_df[_c] = _norm_df[_c] / _first[_c] * 100

                _fig2, _ax2 = plt.subplots(figsize=(13, 5))
                _ax2.plot(_norm_df["date"], _norm_df["Energy"],
                          color="#27ae60", linewidth=2, label=f"Energy: {_cmp_ee_prod}")
                _ax2.plot(_norm_df["date"], _norm_df["Gas"],
                          color="#f1c40f", linewidth=2, label=f"Gas: {_cmp_gas_prod}")
                _ax2.plot(_norm_df["date"], _norm_df["ETS"],
                          color="#222222", linewidth=1.8, linestyle="dotted", label=_ets_legend)

                _ax2.axhline(100, color="#aaaaaa", linewidth=0.8, linestyle="--")
                _ax2.set_ylabel("Index (start = 100)", fontsize=11)
                _ax2.set_title(
                    f"Normalized price movements — {_cmp_yr_lbl}  ({_cmp_from} → {_cmp_to})",
                    fontsize=13, fontweight="bold",
                )
                _ax2.xaxis.set_major_formatter(mdates.DateFormatter("%d %b %Y"))
                _ax2.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
                plt.setp(_ax2.xaxis.get_majorticklabels(), rotation=45, ha="right")
                _ax2.grid(True, color="#eeeeee", linewidth=0.8)
                _ax2.legend(loc="best", fontsize=10, framealpha=0.9)
                _ax2.spines["top"].set_visible(False)
                _ax2.spines["right"].set_visible(False)
                _fig2.tight_layout()
                st.pyplot(_fig2)
                plt.close(_fig2)

                # Pearson correlation table
                _r_eg = _norm_df["Energy"].corr(_norm_df["Gas"])
                _r_ee = _norm_df["Energy"].corr(_norm_df["ETS"])
                _r_ge = _norm_df["Gas"].corr(_norm_df["ETS"])

                _corr_df = pd.DataFrame({
                    "Pair":        ["Energy vs Gas", "Energy vs ETS", "Gas vs ETS"],
                    "Pearson R":   [round(_r_eg, 3), round(_r_ee, 3), round(_r_ge, 3)],
                    "R²":          [round(_r_eg**2, 3), round(_r_ee**2, 3), round(_r_ge**2, 3)],
                })

                st.markdown("**Correlation table** (selected period)")

                def _style_corr(val):
                    if not isinstance(val, float):
                        return ""
                    if abs(val) >= 0.8:
                        return "color: #27ae60; font-weight: 700"
                    if abs(val) >= 0.5:
                        return "color: #f39c12; font-weight: 600"
                    return "color: #e74c3c"

                st.dataframe(
                    _corr_df.style.applymap(_style_corr, subset=["Pearson R", "R²"]),
                    use_container_width=False,
                    hide_index=True,
                )




def render_liquidity():
    st.title("Liquidity")
    st.caption("Monthly trading volume for the same product shape across completed delivery years")

    _liq_today = pd.Timestamp.now().normalize()

    def _liq_expiry(pname: str):
        sub = str(pname).split("_")[-1].split("-")
        try:
            year = 2000 + int(sub[-1])
            pt = sub[0]
            if pt == "Y":
                return pd.Timestamp(year - 1, 12, 1)
            if pt == "Q":
                ey, em = {1: (year-1, 12), 2: (year, 3), 3: (year, 6), 4: (year, 9)}[int(sub[1])]
                return pd.Timestamp(ey, em, 1)
            if pt == "M":
                m = int(sub[1])
                return pd.Timestamp(year - 1, 12, 1) if m == 1 else pd.Timestamp(year, m - 1, 1)
            if pt == "S":
                return pd.Timestamp(year, 3, 1) if sub[1].upper() == "S" else pd.Timestamp(year, 9, 1)
        except Exception:
            return None
        return None

    def _liq_delivery_end(pname: str):
        """Last day of the delivery period — used to determine if contract is completed."""
        sub = str(pname).split("_")[-1].split("-")
        try:
            year = 2000 + int(sub[-1])
            pt = sub[0]
            if pt == "Y":
                return pd.Timestamp(year, 12, 31)
            if pt == "Q":
                ey, em = {1: (year, 3), 2: (year, 6), 3: (year, 9), 4: (year, 12)}[int(sub[1])]
                return pd.Timestamp(ey, em, 1) + pd.offsets.MonthEnd(0)
            if pt == "M":
                m = int(sub[1])
                return pd.Timestamp(year, m, 1) + pd.offsets.MonthEnd(0)
            if pt == "S":
                return pd.Timestamp(year, 9, 30) if sub[1].upper() == "S" else pd.Timestamp(year + 1, 3, 31)
        except Exception:
            return None
        return None

    def _liq_shape(pname: str) -> str:
        return str(pname).rsplit("-", 1)[0]

    def _liq_del_year(pname: str):
        try:
            return 2000 + int(str(pname).rsplit("-", 1)[1])
        except Exception:
            return None

    def _build_liq(df, col, shape, n_years):
        df = df[df[col].apply(_liq_shape) == shape].copy()
        df["_dy"] = df[col].apply(_liq_del_year)
        avail = sorted([int(x) for x in df["_dy"].dropna().unique()])
        # Exclude far-forward contracts: keep only years whose expiry is within 13 months from today
        _cutoff = _liq_today + pd.DateOffset(months=13)
        avail = [
            yr for yr in avail
            if (exp := _liq_expiry(df[df["_dy"] == yr][col].iloc[0])) is not None and exp <= _cutoff
        ]
        sel = avail[-int(n_years):] if len(avail) >= int(n_years) else avail
        rows = []
        for yr in sel:
            yr_df = df[df["_dy"] == yr]
            if yr_df.empty:
                continue
            exp = _liq_expiry(yr_df[col].iloc[0])
            if exp is None:
                continue
            for pos in range(1, 13):
                ms = exp - pd.DateOffset(months=12 - pos)
                me = ms + pd.offsets.MonthEnd(0)
                qty = yr_df.loc[(yr_df["date"] >= ms) & (yr_df["date"] <= me), "quantity_mw"].fillna(0).sum()
                rows.append({
                    "yr": f"'{yr % 100:02d}",
                    "pos": pos,
                    "mon": ms.strftime("%b"),
                    "qty": round(float(qty), 1),
                })
        x_map = {r["pos"]: r["mon"] for r in rows}
        x_labels = [x_map.get(i, "") for i in range(1, 13)]
        return pd.DataFrame(rows), sel, x_labels

    def _liq_chart(liq_df, x_labels, shape, as_line=False):
        if liq_df.empty:
            st.info("No data for selected product.")
            return
        _colors = ["#264653", "#2a9d8f", "#e9c46a", "#f4a261", "#e76f51", "#a8dadc"]
        fig = go.Figure()
        for ci, yr_label in enumerate(sorted(liq_df["yr"].unique())):
            d = liq_df[liq_df["yr"] == yr_label].sort_values("pos")
            c = _colors[ci % len(_colors)]
            if as_line:
                fig.add_trace(go.Scatter(
                    name=yr_label,
                    x=d["pos"],
                    y=d["qty"],
                    mode="lines+markers",
                    line=dict(color=c, width=2),
                    marker=dict(size=6),
                    hovertemplate="%{y:.0f} MW<extra></extra>",
                ))
            else:
                fig.add_trace(go.Bar(
                    name=yr_label,
                    x=d["pos"],
                    y=d["qty"],
                    marker_color=c,
                    hovertemplate="%{y:.0f} MW<extra></extra>",
                ))
        fig.update_layout(
            **CHART_THEME,
            title=f"{shape} — monthly trading volume by delivery year",
            xaxis=dict(
                title="Month before expiry (M-12 = furthest · M-1 = expiry month)",
                tickmode="array",
                tickvals=list(range(1, 13)),
                ticktext=[x_labels[i] if i < len(x_labels) else "" for i in range(12)],
                gridcolor="#eee",
            ),
            yaxis=dict(title="Volume (MW)", gridcolor="#eee"),
            barmode="group",
            legend=dict(orientation="h", y=1.08),
            height=500,
            hovermode="x unified",
        )
        st.plotly_chart(fig, use_container_width=True)
        st.caption(f"Delivery years: {', '.join(sorted(liq_df['yr'].unique()))}")
        with st.expander("Data table"):
            _pivot = liq_df.pivot_table(
                index="pos", columns="yr", values="qty", aggfunc="sum", fill_value=0
            )
            _pivot.index = pd.Index(
                [x_labels[i - 1] if i - 1 < len(x_labels) else str(i) for i in _pivot.index],
                name="Month",
            )
            st.dataframe(_pivot, use_container_width=True)

    _tab_ee, _tab_gas = st.tabs(["Energy", "Gas"])

    with _tab_ee:
        _liq_ee = load_otf_ee()
        if _liq_ee.empty:
            st.warning("No EE data available.")
        else:
            # All shapes, filtered to Y / Q / M types only
            _ee_all_shapes = sorted({
                _liq_shape(p) for p in _liq_ee["product_name"].dropna().unique()
                if _liq_shape(p).split("_")[-1][0] in ("Y", "Q", "M")
            })
            _ee_segs = sorted({s.split("_")[0] for s in _ee_all_shapes})
            _lc1, _lc2, _lc3 = st.columns([1.2, 2, 0.8])
            with _lc1:
                _ee_seg = st.selectbox(
                    "Segment", options=_ee_segs,
                    index=_ee_segs.index("BASE") if "BASE" in _ee_segs else 0,
                    key="liq_ee_seg",
                )
            _ee_shapes_filt = [s for s in _ee_all_shapes if s.split("_")[0] == _ee_seg]
            with _lc2:
                _ee_shape = st.selectbox("Product", options=_ee_shapes_filt, key="liq_ee_shape")
            with _lc3:
                _ee_ny = int(st.number_input("Years", min_value=1, max_value=20, value=5, step=1, key="liq_ee_ny"))
            _ee_as_line = st.checkbox("Line chart", value=False, key="liq_ee_line")
            _ee_liq_df, _ee_sel, _ee_xl = _build_liq(_liq_ee, "product_name", _ee_shape, _ee_ny)
            _liq_chart(_ee_liq_df, _ee_xl, _ee_shape, as_line=_ee_as_line)

    with _tab_gas:
        _liq_gas = load_otf_gas()
        if _liq_gas.empty:
            st.warning("No Gas data available.")
        else:
            # Gas shapes, filtered to Y / Q / M only (exclude seasonal S)
            _gas_all_shapes = sorted({
                _liq_shape(p) for p in _liq_gas["Kontrakt"].dropna().unique()
                if _liq_shape(p).split("_")[-1][0] in ("Y", "Q", "M")
            })
            _gc1, _gc2 = st.columns([3, 1])
            with _gc1:
                _gas_shape = st.selectbox("Product", options=_gas_all_shapes, key="liq_gas_shape")
            with _gc2:
                _gas_ny = int(st.number_input("Years", min_value=1, max_value=20, value=5, step=1, key="liq_gas_ny"))
            _gas_as_line = st.checkbox("Line chart", value=False, key="liq_gas_line")
            _gas_liq_df, _gas_sel, _gas_xl = _build_liq(_liq_gas, "Kontrakt", _gas_shape, _gas_ny)
            _liq_chart(_gas_liq_df, _gas_xl, _gas_shape, as_line=_gas_as_line)




