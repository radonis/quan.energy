import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import os, json, time
from datetime import date, timedelta
from shared import (
    CHART_THEME, APP_DIR,
    load_prices, load_trades, save_trades,
    load_tso_trades, save_tso_trades, calc_pnl,
    load_pse, load_rb_h_cached,
    TRADES_PATH, TSO_TRADES_PATH,
)

def render_fixtrade():
    prices = load_prices()
    trades = load_trades()
    st.title("FixTrade")

    # ── Date header ───────────────────────────────────────────────────────────
    if "_fix_date_val" not in st.session_state:
        st.session_state._fix_date_val = date.today()

    _fa, _fb, _fc, _fd, _ = st.columns([0.28, 1.6, 0.28, 1.4, 2.4])
    with _fa:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("◀", key="fix_prev", use_container_width=True):
            st.session_state._fix_date_val -= timedelta(days=1)
            st.rerun()
    with _fb:
        entry_date = st.date_input("Fixing date", value=st.session_state._fix_date_val)
        st.session_state._fix_date_val = entry_date
    with _fc:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("▶", key="fix_next", use_container_width=True):
            if st.session_state._fix_date_val < date.today():
                st.session_state._fix_date_val += timedelta(days=1)
            st.rerun()
    with _fd:
        delivery_date = entry_date + timedelta(days=1)
        st.markdown(
            '<p style="font-size:0.875rem;color:#555;margin-bottom:0">Delivery date</p>'
            f'<p style="font-size:1rem;font-weight:500;margin-top:8px">{delivery_date}</p>',
            unsafe_allow_html=True,
        )

    date_str      = str(entry_date)
    date_trades   = [t for t in trades if t["fixing_date"] == date_str]
    is_locked     = any(t.get("locked", False) for t in date_trades)
    priced_count  = sum(1 for t in date_trades if t.get("pnl") is not None)
    is_priced     = priced_count > 0 and priced_count == len(date_trades)

    st.divider()
    left, right = st.columns([1, 1])

    # ── LEFT: compact data-editor grid ───────────────────────────────────────
    with left:
        st.subheader("Positions")

        existing = {t["hour"]: t for t in date_trades}

        # Build 24-row dataframe
        rows = []
        for h in range(1, 25):
            ex = existing.get(h)
            rows.append({
                "H":         f"H{h:02d}",
                "MW":        float(ex["volume_mw"]) if ex else 0.0,
                "Direction": ex["direction"] if ex else "—",
            })
        df_grid = pd.DataFrame(rows)

        if not is_locked:
            edited = st.data_editor(
                df_grid,
                column_config={
                    "H":         st.column_config.TextColumn("H",   disabled=True, width=55),
                    "MW":        st.column_config.NumberColumn("MW", min_value=0.0,
                                     max_value=500.0, step=0.5, width=80),
                    "Direction": st.column_config.SelectboxColumn(
                                     "Direction",
                                     options=["—", "Short", "Long"],
                                     width=110),
                },
                hide_index=True,
                use_container_width=False,
                height=882,          # 24 rows × ~35 px + header — no inner scroll
                key=f"grid_{date_str}",
            )

            if st.button("Save Trades", type="primary", use_container_width=True):
                added = 0
                for _, row in edited.iterrows():
                    h    = int(row["H"][1:])   # "H03" → 3
                    vol  = float(row["MW"])
                    dir_ = row["Direction"]
                    # Always remove then re-add so edits overwrite
                    trades[:] = [t for t in trades
                                  if not (t["fixing_date"] == date_str and t["hour"] == h)]
                    if dir_ != "—" and vol > 0:
                        trades.append({
                            "id":            int(time.time() * 1000) + h,
                            "fixing_date":   date_str,
                            "delivery_date": str(delivery_date),
                            "hour":          h,
                            "direction":     dir_,
                            "volume_mw":     vol,
                            "pnl":           None,
                            "locked":        False,
                        })
                        added += 1
                save_trades(trades)
                st.success(f"Saved {added} trade(s) for fixing {entry_date} / delivery {delivery_date}.")
                st.rerun()
        else:
            # Read-only view when locked
            st.dataframe(df_grid, hide_index=True, use_container_width=False,
                         height=882)
            st.info("Locked — no further edits allowed.")

    # ── RIGHT: summary table + Lock / Price Trade / Day summary ──────────────
    with right:
        date_trades = [t for t in trades if t["fixing_date"] == date_str]

        if date_trades:
            st.subheader(f"Open trades — delivery {delivery_date}")

            df_dt = pd.DataFrame(date_trades).sort_values("hour")
            df_dt["Hour"] = df_dt["hour"].apply(lambda h: f"H{h:02d}")
            df_show = df_dt[["Hour", "direction", "volume_mw"]].rename(
                columns={"direction": "Dir", "volume_mw": "MW"})

            def _row_color(row):
                if row["Dir"] == "Long":
                    return ["background-color:#c8f7c5;color:#155724"] * len(row)
                if row["Dir"] == "Short":
                    return ["background-color:#fcd5d5;color:#7b0000"] * len(row)
                return [""] * len(row)

            st.dataframe(df_show.style.apply(_row_color, axis=1),
                         use_container_width=True, hide_index=True)

            st.divider()

            if not is_locked:
                if st.button("🔒  Lock trades", type="secondary", use_container_width=True):
                    for t in trades:
                        if t["fixing_date"] == date_str:
                            t["locked"] = True
                    save_trades(trades)
                    st.rerun()
            else:
                st.success("Trades are locked.")
                if not is_priced:
                    st.caption("Step 1 — pull latest prices from TGE (~15:00 onwards).")
                    if st.button("🔄  Update prices from TGE", use_container_width=True):
                        import sys
                        sys.path.insert(0, os.path.join(APP_DIR, "procedures"))
                        from tge_fixing import run_pipeline
                        lines = []
                        with st.spinner("Downloading from TGE..."):
                            result = run_pipeline(
                                app_dir=APP_DIR,
                                log=lambda msg: lines.append(msg),
                            )
                        if result["status"] == "ok":
                            st.success(result["message"])
                            load_prices.clear()
                        else:
                            st.error(result["message"])
                        with st.expander("Pipeline log"):
                            st.text("\n".join(lines))

                    st.caption("Step 2 — calculate P&L for today's trades.")
                    if st.button("💰  Price Trade", type="primary", use_container_width=True):
                        load_prices.clear()
                        prices_fresh = load_prices()
                        updated, missing = 0, []
                        for t in trades:
                            if t["fixing_date"] == date_str and t.get("pnl") is None:
                                r_df = prices_fresh[
                                    (prices_fresh["delivery_date"] == delivery_date) &
                                    (prices_fresh["H"] == t["hour"])
                                ]
                                if r_df.empty or pd.isna(r_df.iloc[0]["spread_f1_sdac"]):
                                    missing.append(f"H{t['hour']:02d}")
                                    continue
                                r = r_df.iloc[0]
                                t["pnl"]        = round(calc_pnl(t["direction"], t["volume_mw"], r["spread_f1_sdac"]), 2)
                                t["f1_price"]   = round(float(r["f1_price_PLN"]), 4)
                                t["sdac_price"] = round(float(r["sdac_price_PLN"]), 4)
                                t["spread"]     = round(float(r["spread_f1_sdac"]), 4)
                                updated += 1
                        save_trades(trades)
                        if updated:
                            st.success(f"Priced {updated} trade(s).")
                        if missing:
                            st.warning(f"SDAC missing for: {', '.join(missing)}")
                        st.rerun()

            # Day summary after pricing
            priced = [t for t in trades
                      if t["fixing_date"] == date_str and t.get("pnl") is not None]
            if priced:
                st.divider()
                st.subheader("Day summary")
                df_p = pd.DataFrame(priced).sort_values("hour")
                df_p["Hour"] = df_p["hour"].apply(lambda h: f"H{h:02d}")
                df_p = df_p.rename(columns={
                    "direction": "Dir", "volume_mw": "MW",
                    "f1_price": "F1", "sdac_price": "SDAC",
                    "spread": "Spread", "pnl": "P&L",
                })[["Hour", "Dir", "MW", "F1", "SDAC", "Spread", "P&L"]]

                def _pnl_col(row):
                    styles = [""] * len(row)
                    idx = row.index.get_loc("P&L")
                    styles[idx] = ("background-color:#c8f7c5;color:#155724"
                                   if row["P&L"] >= 0
                                   else "background-color:#fcd5d5;color:#7b0000")
                    return styles

                st.dataframe(df_p.style.apply(_pnl_col, axis=1),
                             use_container_width=True, hide_index=True)
                total = sum(t["pnl"] for t in priced)
                win   = sum(1 for t in priced if t["pnl"] > 0)
                c1, c2, c3 = st.columns(3)
                c1.metric("Day P&L (PLN)", f"{total:,.2f}")
                c2.metric("Trades", len(priced))
                c3.metric("Win rate", f"{win/len(priced)*100:.0f}%")

        else:
            st.info("No trades entered for this date yet.")

    # ── VAR Check ─────────────────────────────────────────────────────────────
    from page_modules import var_trading as _var
    _var.render_var_widget("SPOT", entry_date)

    # ══════════════════════════════════════════════════════════════════════════
    # FIX TRADES VIEWER
    # ══════════════════════════════════════════════════════════════════════════
    st.divider()
    st.subheader("TradesConcluded")

    if not trades:
        st.info("No Fix trades recorded yet.")
    else:
        if "_fix_viewer_date_val" not in st.session_state:
            st.session_state._fix_viewer_date_val = date.today() - timedelta(days=1)

        _all_fix_dates_fv = sorted({
            date.fromisoformat(t["fixing_date"])
            for t in trades if "fixing_date" in t
        })
        _min_date_fv = _all_fix_dates_fv[0] if _all_fix_dates_fv else date.today() - timedelta(days=30)

        _fv1, _fv2, _fv3, _fv4, _ = st.columns([0.25, 1.4, 0.25, 4, 1])

        with _fv1:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("◀", key="fix_viewer_prev", use_container_width=True):
                st.session_state._fix_viewer_date_val -= timedelta(days=1)
                st.rerun()

        with _fv2:
            _fv_date = st.date_input(
                "Date",
                value=st.session_state._fix_viewer_date_val,
                min_value=_min_date_fv,
                max_value=date.today(),
            )
            st.session_state._fix_viewer_date_val = _fv_date

        with _fv3:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("▶", key="fix_viewer_next", use_container_width=True):
                if st.session_state._fix_viewer_date_val < date.today():
                    st.session_state._fix_viewer_date_val += timedelta(days=1)
                st.rerun()

        _fv_from = _fv_to = _fv_date

        _filtered_fv = [
            t for t in trades
            if "fixing_date" in t
            and _fv_from <= date.fromisoformat(t["fixing_date"]) <= _fv_to
        ]

        if not _filtered_fv:
            st.info("No Fix trades in selected range.")
        else:
            _rows_fv = []
            for _i, _t in enumerate(
                    sorted(_filtered_fv, key=lambda x: (x["fixing_date"], x["hour"])), 1):
                _pnl = _t.get("pnl")
                _fv_deliv = (date.fromisoformat(_t["fixing_date"]) + timedelta(days=1)
                             if _t.get("fixing_date") else "")
                _rows_fv.append({
                    "#":            _i,
                    "TradeDate":    _t.get("fixing_date", ""),
                    "DeliveryDate": str(_fv_deliv),
                    "Hour":         f"H{int(_t.get('hour', 0)):02d}",
                    "MW":           _t.get("volume_mw", ""),
                    "Direction":    str(_t.get("direction", "")).capitalize(),
                    "Status":       "Priced" if _pnl is not None else "Open",
                    "P&L":          round(_pnl, 2) if _pnl is not None else None,
                })

            _df_fv = pd.DataFrame(_rows_fv)

            _th_s = ("background:#f0f2f6;font-weight:600;font-size:12px;"
                     "padding:5px 10px;text-align:left;white-space:nowrap;"
                     "border-bottom:2px solid #ddd;")
            _td_s = "padding:4px 10px;font-size:12px;white-space:nowrap;border-bottom:1px solid #eee;"

            _fv_header = "".join(f'<th style="{_th_s}">{c}</th>' for c in _df_fv.columns)
            _fv_body   = ""
            for _, _row in _df_fv.iterrows():
                _cells = ""
                for _col in _df_fv.columns:
                    _val   = _row[_col]
                    _extra = ""
                    if _col == "Direction":
                        if str(_val).lower() == "long":
                            _extra = "background:#d4edda;color:#155724;"
                        elif str(_val).lower() == "short":
                            _extra = "background:#fcd5d5;color:#7b0000;"
                    elif _col == "Status":
                        if _val == "Priced":
                            _extra = "color:#155724;font-weight:600;"
                        elif _val == "Open":
                            _extra = "color:#856404;font-weight:600;"
                    elif _col == "P&L" and _val is not None and _val == _val:
                        try:
                            _extra = ("background:#c8f7c5;color:#155724;"
                                      if float(_val) >= 0
                                      else "background:#fcd5d5;color:#7b0000;")
                        except (TypeError, ValueError):
                            pass
                    if _col in ("MW", "P&L") and _val is not None and _val == _val:
                        try:
                            _disp = f"{float(_val):.2f}"
                        except (TypeError, ValueError):
                            _disp = "" if str(_val) == "nan" else str(_val)
                    else:
                        _disp = "" if str(_val) == "nan" else str(_val)
                    _cells += f'<td style="{_td_s}{_extra}">{_disp}</td>'
                _fv_body += f"<tr>{_cells}</tr>"

            st.markdown(f"""
            <div style="overflow-x:auto;">
              <table style="border-collapse:collapse;border:1px solid #ddd;font-family:sans-serif;">
                <thead><tr>{_fv_header}</tr></thead>
                <tbody>{_fv_body}</tbody>
              </table>
            </div>
            """, unsafe_allow_html=True)
            st.caption(f"{len(_rows_fv)} row(s) · {_fv_from} to {_fv_to}")

            _open_fv = [t for t in trades
                        if t.get("fixing_date") == str(_fv_date) and t.get("pnl") is None]
            if _open_fv:
                if st.button(f"💰 Price Trades ({len(_open_fv)} open)",
                             type="primary", key="fix_viewer_price_btn"):
                    load_prices.clear()
                    _fp = load_prices()
                    _fv_deliv_d = _fv_date + timedelta(days=1)
                    _upd, _miss = 0, []
                    for _t in trades:
                        if _t.get("fixing_date") == str(_fv_date) and _t.get("pnl") is None:
                            _r = _fp[(_fp["delivery_date"] == _fv_deliv_d) & (_fp["H"] == _t["hour"])]
                            if _r.empty or pd.isna(_r.iloc[0]["spread_f1_sdac"]):
                                _miss.append(f"H{_t['hour']:02d}")
                                continue
                            _rr = _t
                            _row = _r.iloc[0]
                            _t["pnl"]        = round(calc_pnl(_t["direction"], _t["volume_mw"], _row["spread_f1_sdac"]), 2)
                            _t["f1_price"]   = round(float(_row["f1_price_PLN"]), 4)
                            _t["sdac_price"] = round(float(_row["sdac_price_PLN"]), 4)
                            _t["spread"]     = round(float(_row["spread_f1_sdac"]), 4)
                            _upd += 1
                    save_trades(trades)
                    if _upd:  st.success(f"Priced {_upd} trade(s).")
                    if _miss: st.warning(f"SDAC missing for: {', '.join(_miss)}")
                    st.rerun()





def render_tsotrade():
    prices = load_prices()
    trades = load_trades()
    tso_trades = load_tso_trades()
    st.title("TSOTrade")
    st.caption("Open at F2 (SDAC) · Close at CEN · 15-min granularity")

    # ── Date header ───────────────────────────────────────────────────────────
    if "_tso_date_val" not in st.session_state:
        st.session_state._tso_date_val = date.today()

    _ta, _tb, _tc, _td, _ = st.columns([0.28, 1.6, 0.28, 1.4, 2.4])
    with _ta:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("◀", key="tso_prev", use_container_width=True):
            st.session_state._tso_date_val -= timedelta(days=1)
            st.rerun()
    with _tb:
        entry_date = st.date_input("Fixing date", value=st.session_state._tso_date_val)
        st.session_state._tso_date_val = entry_date
    with _tc:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("▶", key="tso_next", use_container_width=True):
            if st.session_state._tso_date_val < date.today():
                st.session_state._tso_date_val += timedelta(days=1)
            st.rerun()
    with _td:
        delivery_date = entry_date + timedelta(days=1)
        st.markdown(
            '<p style="font-size:0.875rem;color:#555;margin-bottom:0">Delivery date</p>'
            f'<p style="font-size:1rem;font-weight:500;margin-top:8px">{delivery_date}</p>',
            unsafe_allow_html=True,
        )

    date_str  = str(entry_date)
    date_tso  = [t for t in tso_trades if t["fixing_date"] == date_str]
    is_locked = any(t.get("locked", False) for t in date_tso)

    # Session state keys for this date
    _expand_key = f"tso_expanded_{date_str}"
    _import_key = f"tso_import_data_{date_str}"
    _impkv_key  = f"tso_import_kv_{date_str}"    # incrementing key to reset data_editor
    _hourdat_key = f"tso_hour_data_{date_str}"

    if _expand_key not in st.session_state:
        st.session_state[_expand_key] = False
    if _impkv_key not in st.session_state:
        st.session_state[_impkv_key] = 0

    fix_trades_today = [t for t in trades if t["fixing_date"] == date_str]

    st.divider()
    left, right = st.columns([1, 1])

    with left:
        st.subheader("Positions")

        if not st.session_state[_expand_key]:
            # ── STEP 1: Hour grid ────────────────────────────────────────────
            st.caption("Step 1 — enter positions by hour")

            # Seed from import if available, else from saved TSO trades (collapse to hours)
            if _import_key in st.session_state:
                _init_rows = st.session_state.pop(_import_key)
            elif date_tso:
                _hour_map = {}
                for t in date_tso:
                    h = t["hour"]
                    if h not in _hour_map:
                        _hour_map[h] = {"MW": t["volume_mw"], "Direction": t["direction"]}
                _init_rows = [
                    {"H": f"H{h:02d}",
                     "MW": float(_hour_map[h]["MW"]) if h in _hour_map else 0.0,
                     "Direction": _hour_map[h]["Direction"] if h in _hour_map else "—"}
                    for h in range(1, 25)
                ]
            else:
                _init_rows = [{"H": f"H{h:02d}", "MW": 0.0, "Direction": "—"}
                               for h in range(1, 25)]

            df_hour = pd.DataFrame(_init_rows)

            _var_key = f"tso_var_{date_str}"

            if not is_locked:
                # ── Step 1 grid (same style as FixTrade) ─────────────────────
                edited_hour = st.data_editor(
                    df_hour,
                    column_config={
                        "H":         st.column_config.TextColumn("H",   disabled=True, width=55),
                        "MW":        st.column_config.NumberColumn("MW", min_value=0.0,
                                         max_value=500.0, step=0.5, width=80),
                        "Direction": st.column_config.SelectboxColumn(
                                         "Direction",
                                         options=["—", "Short", "Long"],
                                         width=110),
                    },
                    hide_index=True,
                    use_container_width=False,
                    height=882,
                    key=f"tso_hour_grid_{date_str}_{st.session_state[_impkv_key]}",
                )

                _btn_a, _btn_b = st.columns(2)
                with _btn_a:
                    if fix_trades_today:
                        if st.button("Import from FixTrade", use_container_width=True,
                                     key=f"tso_import_{date_str}"):
                            _fix_by_hour = {t["hour"]: t for t in fix_trades_today}
                            st.session_state[_import_key] = [
                                {"H": f"H{h:02d}",
                                 "MW": float(_fix_by_hour[h]["volume_mw"]) if h in _fix_by_hour else 0.0,
                                 "Direction": _fix_by_hour[h]["direction"] if h in _fix_by_hour else "—"}
                                for h in range(1, 25)
                            ]
                            st.session_state[_impkv_key] += 1
                            st.rerun()
                with _btn_b:
                    if st.button("Save Hourly", type="primary",
                                 use_container_width=True, key=f"tso_save_h_{date_str}"):
                        _hour_records = edited_hour.to_dict("records")
                        st.session_state[_hourdat_key] = _hour_records
                        # Calculate RB VAR from hourly positions
                        from page_modules import var_trading as _vm
                        _active_rb = _vm._get_active_params("RB")
                        if _active_rb is not None:
                            _pos = {}
                            for _r in _hour_records:
                                _h = int(_r["H"][1:])
                                _mw = float(_r["MW"])
                                if _r["Direction"] == "Long":
                                    _pos[_h] = _mw
                                elif _r["Direction"] == "Short":
                                    _pos[_h] = -_mw
                            st.session_state[_var_key] = _vm._calc_var(_pos, _active_rb)
                        else:
                            st.session_state.pop(_var_key, None)
                        st.rerun()

                # ── VAR result + Expand button (shown after hourly save) ──────
                if _hourdat_key in st.session_state:
                    from page_modules import var_trading as _vm
                    if _var_key in st.session_state:
                        _res = st.session_state[_var_key]
                        st.markdown(
                            _vm._badge_html(
                                _res["pct_of_limit"], _res["daily_var"],
                                _res["accepted_limit"], "RB"
                            ),
                            unsafe_allow_html=True,
                        )
                        with st.expander("Hour breakdown"):
                            _df_bd  = pd.DataFrame(_res["breakdown"])
                            _act_bd = _df_bd[_df_bd["Risk (PLN)"] > 0]
                            if _act_bd.empty:
                                st.info("No open positions.")
                            else:
                                st.dataframe(_act_bd, hide_index=True,
                                             use_container_width=True,
                                             height=len(_act_bd) * 35 + 38)
                    else:
                        st.caption("RB VAR not calibrated — go to Trading → VAR.")

                    if st.button("Expand to quarters →", type="primary",
                                 use_container_width=True, key=f"tso_expand_{date_str}"):
                        st.session_state[_expand_key] = True
                        st.rerun()
            else:
                st.dataframe(df_hour, hide_index=True, use_container_width=False, height=882)
                st.info("Locked — use Quarter view to see all 96 slots.")
                if st.button("View quarters →", key=f"tso_view_qt_{date_str}"):
                    st.session_state[_expand_key] = True
                    st.rerun()
                # Auto-recalculate VAR if session_state was lost (e.g. page reload)
                if _var_key not in st.session_state and date_tso:
                    from page_modules import var_trading as _vm
                    _active_rb = _vm._get_active_params("RB")
                    if _active_rb is not None:
                        _pos = _vm._get_rb_position(entry_date)
                        if _pos:
                            st.session_state[_var_key] = _vm._calc_var(_pos, _active_rb)
                if _var_key in st.session_state:
                    from page_modules import var_trading as _vm
                    _res = st.session_state[_var_key]
                    st.markdown(
                        _vm._badge_html(_res["pct_of_limit"], _res["daily_var"],
                                        _res["accepted_limit"], "RB"),
                        unsafe_allow_html=True,
                    )
                    with st.expander("Hour breakdown"):
                        _df_bd  = pd.DataFrame(_res["breakdown"])
                        _act_bd = _df_bd[_df_bd["Risk (PLN)"] > 0]
                        if _act_bd.empty:
                            st.info("No open positions.")
                        else:
                            st.dataframe(_act_bd, hide_index=True,
                                         use_container_width=True,
                                         height=len(_act_bd) * 35 + 38)
                elif date_tso:
                    st.caption("RB VAR not calibrated — go to Trading → VAR.")

        else:
            # ── STEP 2: Quarter grid (96 rows) ───────────────────────────────
            st.caption("Step 2 — fine-tune by quarter (15 min)")

            # Build quarter grid
            if date_tso and all("quarter" in t for t in date_tso):
                # Already saved at quarter level
                _qt_map = {(t["hour"], t["quarter"]): t for t in date_tso}
            else:
                # Expand from hour data
                _hour_rows = st.session_state.get(_hourdat_key, [])
                _qt_map = {}
                for _row in _hour_rows:
                    _h = int(_row["H"][1:])
                    if _row["Direction"] != "—" and float(_row["MW"]) > 0:
                        for _q in range(1, 5):
                            _qt_map[(_h, _q)] = {"volume_mw": _row["MW"],
                                                  "direction": _row["Direction"]}

            _qt_rows = []
            for _h in range(1, 25):
                for _q in range(1, 5):
                    _ex = _qt_map.get((_h, _q))
                    _qt_rows.append({
                        "H":    f"H{_h:02d}",
                        "Q":    _q,
                        "Time": f"{(_h-1):02d}:{(_q-1)*15:02d}",
                        "MW":   float(_ex["volume_mw"]) if _ex else 0.0,
                        "Direction": _ex["direction"] if _ex else "—",
                    })
            df_qt = pd.DataFrame(_qt_rows)

            if not is_locked:
                edited_qt = st.data_editor(
                    df_qt,
                    column_config={
                        "H":    st.column_config.TextColumn("H",    disabled=True, width=50),
                        "Q":    st.column_config.NumberColumn("Q",  disabled=True, width=40),
                        "Time": st.column_config.TextColumn("Time", disabled=True, width=60),
                        "MW":   st.column_config.NumberColumn("MW", min_value=0.0,
                                    max_value=500.0, step=0.5, width=80),
                        "Direction": st.column_config.SelectboxColumn(
                                         "Direction", options=["—", "Short", "Long"], width=110),
                    },
                    hide_index=True,
                    use_container_width=False,
                    height=882,
                    key=f"tso_qt_grid_{date_str}",
                )

                cb1, cb2 = st.columns(2)
                with cb1:
                    if st.button("← Back to hours", use_container_width=True,
                                 key=f"tso_back_{date_str}"):
                        st.session_state[_expand_key] = False
                        st.rerun()
                with cb2:
                    if st.button("Save TSO Trades", type="primary",
                                 use_container_width=True, key=f"tso_save_{date_str}"):
                        tso_trades[:] = [t for t in tso_trades
                                          if t["fixing_date"] != date_str]
                        _added = 0
                        for _, _row in edited_qt.iterrows():
                            _h   = int(_row["H"][1:])
                            _q   = int(_row["Q"])
                            _vol = float(_row["MW"])
                            _dir = _row["Direction"]
                            if _dir != "—" and _vol > 0:
                                tso_trades.append({
                                    "id":            int(time.time() * 1000) + (_h-1)*4 + _q,
                                    "fixing_date":   date_str,
                                    "delivery_date": str(delivery_date),
                                    "hour":          _h,
                                    "quarter":       _q,
                                    "direction":     _dir,
                                    "volume_mw":     _vol,
                                    "pnl":           None,
                                    "f2_price":      None,
                                    "cen_price":     None,
                                    "spread":        None,
                                    "locked":        False,
                                })
                                _added += 1
                        save_tso_trades(tso_trades)
                        st.success(f"Saved {_added} TSO trade(s) for {entry_date}.")
                        st.rerun()
            else:
                st.dataframe(df_qt, hide_index=True, use_container_width=False, height=882)
                st.info("Locked — no further edits allowed.")
                if st.button("← Back to hour view", key=f"tso_back_lk_{date_str}"):
                    st.session_state[_expand_key] = False
                    st.rerun()

    # ── RIGHT: summary + lock + price ────────────────────────────────────────
    with right:
        date_tso = [t for t in tso_trades if t["fixing_date"] == date_str]

        if date_tso:
            total_slots = len(date_tso)
            priced_count_tso = sum(1 for t in date_tso if t.get("pnl") is not None)
            st.subheader(f"Open TSO trades — delivery {delivery_date}")
            st.caption(f"{total_slots} quarter(s)  ·  {priced_count_tso} priced")

            _df_dt = pd.DataFrame(date_tso).sort_values(["hour", "quarter"])
            _df_dt["Slot"] = _df_dt.apply(
                lambda r: f"H{int(r['hour']):02d}Q{int(r['quarter'])}", axis=1)
            _df_show = _df_dt[["Slot", "direction", "volume_mw"]].rename(
                columns={"direction": "Dir", "volume_mw": "MW"})

            def _tso_row_color(row):
                if row["Dir"] == "Long":
                    return ["background-color:#c8f7c5;color:#155724"] * len(row)
                if row["Dir"] == "Short":
                    return ["background-color:#fcd5d5;color:#7b0000"] * len(row)
                return [""] * len(row)

            st.dataframe(_df_show.style.apply(_tso_row_color, axis=1),
                         use_container_width=True, hide_index=True)

            st.divider()

            if not is_locked:
                if st.button("🔒  Lock TSO trades", type="secondary",
                             use_container_width=True, key="tso_lock"):
                    for t in tso_trades:
                        if t["fixing_date"] == date_str:
                            t["locked"] = True
                    save_tso_trades(tso_trades)
                    st.rerun()
            else:
                st.success("TSO trades are locked.")

                _unpriced = [t for t in date_tso if t.get("pnl") is None]
                if _unpriced:
                    st.caption(
                        f"Price {len(_unpriced)} trade(s) using F2 (SDAC) as open "
                        f"and CEN as close price.")
                    if st.button("💰  Price TSO Trades", type="primary",
                                 use_container_width=True, key="tso_price"):
                        load_prices.clear()
                        load_rb_h_cached.clear()
                        _prices_fresh = load_prices()
                        _rb_fresh     = load_rb_h_cached()
                        _updated, _missing = 0, []

                        for t in tso_trades:
                            if t["fixing_date"] == date_str and t.get("pnl") is None:
                                _h = t["hour"]
                                _q = t["quarter"]

                                # F2 = SDAC for this hour on fixing_date
                                _r_fix = _prices_fresh[
                                    (_prices_fresh["fixing_date"] == entry_date) &
                                    (_prices_fresh["H"] == _h)
                                ]
                                # CEN = hourly RB price on delivery_date
                                # (same price for all 4 quarters of the hour)
                                _r_cen = _rb_fresh[
                                    (_rb_fresh["delivery_date"] == delivery_date) &
                                    (_rb_fresh["H"] == _h)
                                ]

                                if _r_fix.empty or pd.isna(_r_fix.iloc[0]["sdac_price_PLN"]):
                                    _missing.append(f"H{_h:02d}Q{_q}(no F2)")
                                    continue
                                if _r_cen.empty or pd.isna(_r_cen.iloc[0]["cen_cost"]):
                                    _missing.append(f"H{_h:02d}Q{_q}(no CEN)")
                                    continue

                                _f2  = float(_r_fix.iloc[0]["sdac_price_PLN"])
                                _cen = float(_r_cen.iloc[0]["cen_cost"])
                                _spd = _f2 - _cen
                                _sign = 1 if t["direction"] == "Short" else -1
                                t["pnl"]       = round(_sign * _spd * t["volume_mw"] * 0.25, 2)
                                t["f2_price"]  = round(_f2,  4)
                                t["cen_price"] = round(_cen, 4)
                                t["spread"]    = round(_spd, 4)
                                _updated += 1

                        save_tso_trades(tso_trades)
                        if _updated:
                            st.success(f"Priced {_updated} TSO trade(s).")
                        if _missing:
                            st.warning(f"Missing: {', '.join(_missing[:10])}")
                        st.rerun()

            # Day summary after pricing
            _priced_tso = [t for t in tso_trades
                           if t["fixing_date"] == date_str and t.get("pnl") is not None]
            if _priced_tso:
                st.divider()
                st.subheader("Day summary")
                _df_p = pd.DataFrame(_priced_tso).sort_values(["hour", "quarter"])
                _df_p["Slot"] = _df_p.apply(
                    lambda r: f"H{int(r['hour']):02d}Q{int(r['quarter'])}", axis=1)
                _df_p = _df_p.rename(columns={
                    "direction": "Dir", "volume_mw": "MW",
                    "f2_price": "F2", "cen_price": "CEN",
                    "spread": "Spread", "pnl": "P&L",
                })[["Slot", "Dir", "MW", "F2", "CEN", "Spread", "P&L"]]

                def _tso_pnl_col(row):
                    styles = [""] * len(row)
                    idx = row.index.get_loc("P&L")
                    styles[idx] = ("background-color:#c8f7c5;color:#155724"
                                   if row["P&L"] >= 0
                                   else "background-color:#fcd5d5;color:#7b0000")
                    return styles

                st.dataframe(_df_p.style.apply(_tso_pnl_col, axis=1),
                             use_container_width=True, hide_index=True)
                _total = sum(t["pnl"] for t in _priced_tso)
                _win   = sum(1 for t in _priced_tso if t["pnl"] > 0)
                _c1, _c2, _c3 = st.columns(3)
                _c1.metric("Day P&L (PLN)", f"{_total:,.2f}")
                _c2.metric("Quarters", len(_priced_tso))
                _c3.metric("Win rate", f"{_win/len(_priced_tso)*100:.0f}%")
        else:
            st.info("No TSO trades for this date. Enter positions in the grid on the left.")

    # ══════════════════════════════════════════════════════════════════════════
    # TSO TRADES VIEWER
    # ══════════════════════════════════════════════════════════════════════════
    st.divider()
    st.subheader("TradesConcluded")

    _all_tso = load_tso_trades()

    if not _all_tso:
        st.info("No TSO trades recorded yet.")
    else:
        # ── Controls ─────────────────────────────────────────────────────────
        if "_tso_viewer_date_val" not in st.session_state:
            st.session_state._tso_viewer_date_val = date.today() - timedelta(days=1)

        _vc1, _vc2, _vc3, _vc4, _ = st.columns([1, 0.25, 1.4, 0.25, 3])

        with _vc1:
            _gran = st.segmented_control(
                "Granularity",
                options=["Hour", "15 min"],
                default="Hour",
                key="tso_viewer_gran",
            )

        _use_15min = (_gran == "15 min")

        # ── Date (single day, with arrows) ────────────────────────────────────
        _all_fix_dates = sorted({
            date.fromisoformat(t["fixing_date"])
            for t in _all_tso
            if "fixing_date" in t
        })
        _min_date = _all_fix_dates[0] if _all_fix_dates else date.today() - timedelta(days=30)

        with _vc2:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("◀", key="tso_viewer_prev", use_container_width=True):
                st.session_state._tso_viewer_date_val -= timedelta(days=1)
                st.rerun()

        with _vc3:
            _viewer_date = st.date_input(
                "Date",
                value=st.session_state._tso_viewer_date_val,
                min_value=_min_date,
                max_value=date.today(),
            )
            st.session_state._tso_viewer_date_val = _viewer_date

        with _vc4:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("▶", key="tso_viewer_next", use_container_width=True):
                if st.session_state._tso_viewer_date_val < date.today():
                    st.session_state._tso_viewer_date_val += timedelta(days=1)
                st.rerun()

        _date_from = _date_to = _viewer_date

        # ── Filter trades ─────────────────────────────────────────────────────
        _filtered = [
            t for t in _all_tso
            if "fixing_date" in t
            and _date_from <= date.fromisoformat(t["fixing_date"]) <= _date_to
        ]

        if not _filtered:
            st.info("No TSO trades in selected range.")
        else:
            if _use_15min:
                # Quarter-level rows
                _rows = []
                for _i, _t in enumerate(_filtered, 1):
                    _h    = int(_t.get("hour",    0))
                    _q    = int(_t.get("quarter", 1))
                    _slot = f"H{_h:02d}Q{_q}"
                    _pnl  = _t.get("pnl")
                    _tso_deliv = (date.fromisoformat(_t["fixing_date"]) + timedelta(days=1)
                                  if _t.get("fixing_date") else "")
                    _rows.append({
                        "#":            _i,
                        "TradeDate":    _t.get("fixing_date", ""),
                        "DeliveryDate": str(_tso_deliv),
                        "Slot":         _slot,
                        "MW":           _t.get("volume_mw", ""),
                        "Direction":    _t.get("direction", "").capitalize(),
                        "Status":       "Priced" if _pnl is not None else "Open",
                        "P&L":          round(_pnl, 2) if _pnl is not None else None,
                    })
            else:
                # Hour-level: aggregate quarters within same date+hour
                from collections import defaultdict
                _hour_map = defaultdict(lambda: {"volume_mw": [], "priced": 0, "total": 0,
                                                  "direction": "", "fixing_date": "",
                                                  "pnl": 0.0, "pnl_partial": False})
                for _t in _filtered:
                    _key = (_t.get("fixing_date", ""), int(_t.get("hour", 0)))
                    _hour_map[_key]["fixing_date"] = _t.get("fixing_date", "")
                    _hour_map[_key]["direction"]   = _t.get("direction", "")
                    _hour_map[_key]["volume_mw"].append(float(_t.get("volume_mw", 0)))
                    _hour_map[_key]["total"]       += 1
                    _p = _t.get("pnl")
                    if _p is not None:
                        _hour_map[_key]["priced"] += 1
                        _hour_map[_key]["pnl"]    += float(_p)
                    else:
                        _hour_map[_key]["pnl_partial"] = True

                _rows = []
                for _i, ((_fd, _h), _agg) in enumerate(
                        sorted(_hour_map.items()), 1):
                    _priced_q = _agg["priced"]
                    _total_q  = _agg["total"]
                    if _priced_q == _total_q:
                        _status  = "Priced"
                        _pnl_val = round(_agg["pnl"], 2)
                    elif _priced_q > 0:
                        _status  = f"Partial ({_priced_q}/{_total_q})"
                        _pnl_val = round(_agg["pnl"], 2)
                    else:
                        _status  = "Open"
                        _pnl_val = None
                    _tso_deliv_h = date.fromisoformat(_fd) + timedelta(days=1) if _fd else ""
                    _rows.append({
                        "#":            _i,
                        "TradeDate":    _fd,
                        "DeliveryDate": str(_tso_deliv_h),
                        "Hour":         f"H{_h:02d}",
                        "MW":           round(sum(_agg["volume_mw"]) / len(_agg["volume_mw"]), 2),
                        "Direction":    _agg["direction"].capitalize(),
                        "Status":       _status,
                        "P&L":          _pnl_val,
                    })

            _df_view = pd.DataFrame(_rows)

            # Render as HTML table so column widths fit content
            _th_style = ("background:#f0f2f6;font-weight:600;font-size:12px;"
                         "padding:5px 10px;text-align:left;white-space:nowrap;"
                         "border-bottom:2px solid #ddd;")
            _td_style = "padding:4px 10px;font-size:12px;white-space:nowrap;border-bottom:1px solid #eee;"

            _cols = list(_df_view.columns)
            _header = "".join(f'<th style="{_th_style}">{c}</th>' for c in _cols)

            _body = ""
            for _, _row in _df_view.iterrows():
                _cells = ""
                for _col in _cols:
                    _val = _row[_col]
                    _extra = ""
                    if _col == "Direction":
                        if str(_val).lower() == "long":
                            _extra = "background:#d4edda;color:#155724;"
                        elif str(_val).lower() == "short":
                            _extra = "background:#fcd5d5;color:#7b0000;"
                    elif _col == "Status":
                        if _val == "Priced":
                            _extra = "color:#155724;font-weight:600;"
                        elif _val == "Open":
                            _extra = "color:#856404;font-weight:600;"
                    elif _col == "P&L" and _val is not None and _val == _val:
                        try:
                            _extra = ("background:#c8f7c5;color:#155724;"
                                      if float(_val) >= 0
                                      else "background:#fcd5d5;color:#7b0000;")
                        except (TypeError, ValueError):
                            pass
                    # Format numbers
                    if _col in ("MW", "P&L") and _val is not None and _val == _val:
                        try:
                            _disp = f"{float(_val):.2f}"
                        except (TypeError, ValueError):
                            _disp = "" if str(_val) == "nan" else str(_val)
                    else:
                        _disp = "" if str(_val) == "nan" else str(_val)
                    _cells += f'<td style="{_td_style}{_extra}">{_disp}</td>'
                _body += f"<tr>{_cells}</tr>"

            _html_tbl = f"""
            <div style="overflow-x:auto;">
              <table style="border-collapse:collapse;border:1px solid #ddd;font-family:sans-serif;">
                <thead><tr>{_header}</tr></thead>
                <tbody>{_body}</tbody>
              </table>
            </div>
            """
            st.markdown(_html_tbl, unsafe_allow_html=True)
            st.caption(f"{len(_rows)} row(s) · {_date_from} to {_date_to}")

            _open_tso_v = [t for t in _all_tso
                           if t.get("fixing_date") == str(_viewer_date) and t.get("pnl") is None]
            if _open_tso_v:
                if st.button(f"💰 Price Trades ({len(_open_tso_v)} open)",
                             type="primary", key="tso_viewer_price_btn"):
                    load_prices.clear()
                    load_rb_h_cached.clear()
                    _vp   = load_prices()
                    _vrb  = load_rb_h_cached()
                    _v_deliv = _viewer_date + timedelta(days=1)
                    _vupd, _vmiss = 0, []
                    for _t in _all_tso:
                        if _t.get("fixing_date") == str(_viewer_date) and _t.get("pnl") is None:
                            _h = _t["hour"]
                            _r_fix = _vp[(_vp["fixing_date"] == _viewer_date) & (_vp["H"] == _h)]
                            _r_cen = _vrb[(_vrb["delivery_date"] == _v_deliv) & (_vrb["H"] == _h)]
                            if _r_fix.empty or pd.isna(_r_fix.iloc[0]["sdac_price_PLN"]):
                                _vmiss.append(f"H{_h:02d}(no F2)")
                                continue
                            if _r_cen.empty or pd.isna(_r_cen.iloc[0]["cen_cost"]):
                                _vmiss.append(f"H{_h:02d}(no CEN)")
                                continue
                            _f2  = float(_r_fix.iloc[0]["sdac_price_PLN"])
                            _cen = float(_r_cen.iloc[0]["cen_cost"])
                            _spd = _f2 - _cen
                            _sign = 1 if _t["direction"] == "Short" else -1
                            _t["pnl"]       = round(_sign * _spd * _t["volume_mw"] * 0.25, 2)
                            _t["f2_price"]  = round(_f2,  4)
                            _t["cen_price"] = round(_cen, 4)
                            _t["spread"]    = round(_spd, 4)
                            _vupd += 1
                    save_tso_trades(_all_tso)
                    if _vupd:  st.success(f"Priced {_vupd} TSO trade(s).")
                    if _vmiss: st.warning(f"Missing: {', '.join(_vmiss[:10])}")
                    st.rerun()





def render_pnl():
    import io, calendar as _cal
    prices     = load_prices()
    trades     = load_trades()
    tso_trades = load_tso_trades()

    _otf_path = os.path.join(APP_DIR, "otf_trades.json")
    try:
        _otf_all = json.load(open(_otf_path, encoding="utf-8")) if os.path.exists(_otf_path) else []
    except Exception:
        _otf_all = []

    st.title("P&L Dashboard")

    closed_fix = [t for t in trades     if t.get("pnl") is not None]
    closed_tso = [t for t in tso_trades if t.get("pnl") is not None]
    _today     = date.today()

    df_fix = pd.DataFrame(closed_fix) if closed_fix else pd.DataFrame(
        columns=["fixing_date","delivery_date","hour","direction","volume_mw","pnl"])
    df_tso = pd.DataFrame(closed_tso) if closed_tso else pd.DataFrame(
        columns=["fixing_date","delivery_date","hour","quarter","direction","volume_mw","pnl"])

    for _d in [df_fix, df_tso]:
        if not _d.empty:
            _d["fixing_date"]   = pd.to_datetime(_d["fixing_date"]).dt.date
            _d["delivery_date"] = pd.to_datetime(_d["delivery_date"]).dt.date

    # Settled OTF weekly trades: delivery_end < today, P&L from avg F1 over delivery window
    _weekly_rows = []
    for _t in _otf_all:
        try:
            _de_d = date.fromisoformat(str(_t["delivery_end"]))
            _ds_d = date.fromisoformat(str(_t["delivery_start"]))
        except Exception:
            continue
        if _de_d >= _today:
            continue
        _hours = int(_t.get("hours", 168))
        _dir   = str(_t.get("direction", "LONG"))
        _vol   = float(_t.get("volume_mw", 0))
        _tp    = float(_t.get("trade_price", 0))
        _mask  = (prices["delivery_date"] >= _ds_d) & (prices["delivery_date"] <= _de_d)
        _f1avg = float(prices[_mask]["f1_price_PLN"].mean()) if not prices[_mask].empty else _tp
        _sign  = 1.0 if _dir == "LONG" else -1.0
        _weekly_rows.append({
            "tx_date":        _t.get("tx_date"),
            "product":        _t.get("product"),
            "delivery_start": _ds_d,
            "delivery_end":   _de_d,
            "delivery_date":  _de_d,
            "direction":      _dir,
            "volume_mw":      _vol,
            "hours":          _hours,
            "trade_price":    _tp,
            "avg_f1":         round(_f1avg, 2),
            "pnl":            round(_sign * (_f1avg - _tp) * _vol * _hours, 2),
        })

    df_weekly = pd.DataFrame(_weekly_rows) if _weekly_rows else pd.DataFrame(
        columns=["tx_date","product","delivery_start","delivery_end","delivery_date",
                 "direction","volume_mw","hours","trade_price","avg_f1","pnl"])

    # ── Aggregates ─────────────────────────────────────────────────────────────
    fix_total  = float(df_fix["pnl"].sum())    if not df_fix.empty    else 0.0
    tso_total  = float(df_tso["pnl"].sum())    if not df_tso.empty    else 0.0
    wkly_total = float(df_weekly["pnl"].sum()) if not df_weekly.empty else 0.0
    combined   = fix_total + tso_total + wkly_total

    fix_vol  = float(df_fix["volume_mw"].sum())                              if not df_fix.empty    else 0.0
    tso_vol  = float(df_tso["volume_mw"].sum() * 0.25)                       if not df_tso.empty    else 0.0
    wkly_vol = float((df_weekly["volume_mw"] * df_weekly["hours"]).sum())    if not df_weekly.empty else 0.0
    total_vol = fix_vol + tso_vol + wkly_vol

    _all_mw  = (list(df_fix["volume_mw"])    if not df_fix.empty    else []) + \
               (list(df_tso["volume_mw"])    if not df_tso.empty    else []) + \
               (list(df_weekly["volume_mw"]) if not df_weekly.empty else [])
    avg_size = sum(_all_mw) / len(_all_mw) if _all_mw else 0.0

    _all_pnl = (list(df_fix["pnl"])    if not df_fix.empty    else []) + \
               (list(df_tso["pnl"])    if not df_tso.empty    else []) + \
               (list(df_weekly["pnl"]) if not df_weekly.empty else [])
    n_trades = len(_all_pnl)
    n_wins   = sum(1 for p in _all_pnl if p > 0)
    win_rate = n_wins / n_trades * 100 if n_trades else 0.0

    if not _all_pnl:
        st.info("No closed trades yet.")
        st.stop()

    # ── Summary table ──────────────────────────────────────────────────────────
    fix_n    = len(df_fix)
    tso_n    = len(df_tso)
    wkly_n   = len(df_weekly)

    fix_wr   = sum(1 for p in df_fix["pnl"]    if p > 0) / fix_n    * 100 if fix_n    else 0.0
    tso_wr   = sum(1 for p in df_tso["pnl"]    if p > 0) / tso_n    * 100 if tso_n    else 0.0
    wkly_wr  = sum(1 for p in df_weekly["pnl"] if p > 0) / wkly_n   * 100 if wkly_n   else 0.0

    def _pnl_cell(val):
        c = "#2dc653" if val >= 0 else "#e63946"
        return f"<td style='color:{c};font-weight:700;text-align:right'>{val:,.0f}</td>"

    def _num_cell(val, fmt="{:,.0f}"):
        return f"<td style='text-align:right'>{fmt.format(val)}</td>"

    def _hdr_cell(label, sub=""):
        sub_html = f"<br><span style='font-size:0.72rem;color:#888'>{sub}</span>" if sub else ""
        return f"<th style='text-align:center;padding:6px 14px'>{label}{sub_html}</th>"

    st.markdown(f"""
    <style>
    .pnl-summary {{
        border-collapse: collapse;
        width: auto;
        font-size: 0.92rem;
        margin-bottom: 0.5rem;
    }}
    .pnl-summary th {{
        background: #1e2130;
        color: #aaa;
        font-weight: 600;
        border-bottom: 1px solid #333;
        padding: 6px 14px;
    }}
    .pnl-summary td {{
        padding: 5px 14px;
        border-bottom: 1px solid #2a2a3a;
        color: #ddd;
    }}
    .pnl-summary tr:last-child td {{ border-bottom: none; }}
    .pnl-summary .row-label {{
        color: #888;
        font-size: 0.82rem;
        text-align: left;
        white-space: nowrap;
    }}
    .pnl-summary .total-col {{
        background: #1a1f30;
        border-left: 1px solid #333;
    }}
    </style>
    <table class="pnl-summary">
      <thead>
        <tr>
          <th style='text-align:left;padding:6px 14px'></th>
          {_hdr_cell("FIX", "FixTrade")}
          {_hdr_cell("TSO", "TSOTrade")}
          {_hdr_cell("WEEKLY", "settled OTF")}
          {_hdr_cell("TOTAL", "")}
        </tr>
      </thead>
      <tbody>
        <tr>
          <td class="row-label">P&amp;L (PLN)</td>
          {_pnl_cell(fix_total)}
          {_pnl_cell(tso_total)}
          {_pnl_cell(wkly_total)}
          <td class="total-col" style='color:{"#2dc653" if combined>=0 else "#e63946"};font-weight:700;text-align:right;font-size:1.05rem'>{combined:,.0f}</td>
        </tr>
        <tr>
          <td class="row-label">Volume (MWh)</td>
          {_num_cell(fix_vol)}
          {_num_cell(tso_vol)}
          {_num_cell(wkly_vol)}
          <td class="total-col" style='text-align:right'>{total_vol:,.0f}</td>
        </tr>
        <tr>
          <td class="row-label">Trades</td>
          {_num_cell(fix_n)}
          {_num_cell(tso_n)}
          {_num_cell(wkly_n)}
          <td class="total-col" style='text-align:right'>{n_trades}</td>
        </tr>
        <tr>
          <td class="row-label">Win Rate</td>
          {_num_cell(fix_wr,  "{:.0f}%")}
          {_num_cell(tso_wr,  "{:.0f}%")}
          {_num_cell(wkly_wr, "{:.0f}%")}
          <td class="total-col" style='text-align:right'>{win_rate:.0f}%&ensp;<span style='font-size:0.78rem;color:#888'>({n_wins}/{n_trades})</span></td>
        </tr>
        <tr>
          <td class="row-label">Avg Size (MW)</td>
          {_num_cell(df_fix["volume_mw"].mean()    if fix_n    else 0.0, "{:.1f}")}
          {_num_cell(df_tso["volume_mw"].mean()    if tso_n    else 0.0, "{:.1f}")}
          {_num_cell(df_weekly["volume_mw"].mean() if wkly_n   else 0.0, "{:.1f}")}
          <td class="total-col" style='text-align:right'>{avg_size:.1f}</td>
        </tr>
      </tbody>
    </table>
    """, unsafe_allow_html=True)

    st.caption("WEEKLY = settled OTF contracts only (delivery end < today)")
    st.divider()

    MONTH_NAMES = {1:"Jan",2:"Feb",3:"Mar",4:"Apr",5:"May",6:"Jun",
                   7:"Jul",8:"Aug",9:"Sep",10:"Oct",11:"Nov",12:"Dec"}
    MONTH_FULL  = {1:"January",2:"February",3:"March",4:"April",5:"May",6:"June",
                   7:"July",8:"August",9:"September",10:"October",11:"November",12:"December"}

    # ── CSS nav buttons ────────────────────────────────────────────────────────
    st.markdown("""
    <style>
    div.pnl-nav-btn button,
    div.pnl-nav-btn > div > button,
    div.pnl-nav-btn [data-testid="stButton"] > button {
        background-color: #1565c0 !important;
        color: #e63946 !important;
        border: none !important;
        font-weight: bold !important;
        font-size: 1rem !important;
    }
    div.pnl-nav-btn button:hover,
    div.pnl-nav-btn > div > button:hover {
        background-color: #0d47a1 !important;
        color: #e63946 !important;
    }
    </style>
    """, unsafe_allow_html=True)

    # ── Chart filters: FIX / TSO / WEEKLY / ALL ───────────────────────────────
    _cf1, _cf2, _cf3, _cf4, _ = st.columns([0.4, 0.4, 0.75, 0.4, 8.05])
    _show_fix    = _cf1.checkbox("FIX",    value=True,  key="pnl_show_fix")
    _show_tso    = _cf2.checkbox("TSO",    value=False, key="pnl_show_tso")
    _show_weekly = _cf3.checkbox("WEEKLY", value=False, key="pnl_show_weekly")
    _show_all    = _cf4.checkbox("ALL",    value=False, key="pnl_show_all")
    if _show_all:
        _show_fix = _show_tso = _show_weekly = True

    _frames = []
    if not df_fix.empty and _show_fix:
        _frames.append(df_fix[["fixing_date","hour","delivery_date","direction","pnl"]].assign(segment="FIX"))
    if not df_tso.empty and _show_tso:
        _frames.append(df_tso[["fixing_date","hour","delivery_date","direction","pnl"]].assign(segment="TSO"))
    if not df_weekly.empty and _show_weekly:
        _wf = df_weekly[["delivery_date","direction","pnl"]].copy()
        _wf["fixing_date"] = _wf["delivery_date"]
        _wf["hour"] = 0
        _frames.append(_wf[["fixing_date","hour","delivery_date","direction","pnl"]].assign(segment="WEEKLY"))

    df = pd.concat(_frames, ignore_index=True) if _frames else pd.DataFrame(
        columns=["fixing_date","hour","delivery_date","direction","pnl","segment"])

    if not df.empty:
        daily_pnl = df.groupby("delivery_date")["pnl"].sum().reset_index()
        daily_pnl["delivery_date"] = pd.to_datetime(daily_pnl["delivery_date"])
        daily_pnl["year"]  = daily_pnl["delivery_date"].dt.year
        daily_pnl["month"] = daily_pnl["delivery_date"].dt.month
        daily_pnl["day"]   = daily_pnl["delivery_date"].dt.day

        monthly_pnl = daily_pnl.groupby(["year","month"])["pnl"].sum().reset_index()

        available_months = sorted(
            daily_pnl[["year","month"]].drop_duplicates()
            .apply(lambda r: (int(r["year"]), int(r["month"])), axis=1).tolist()
        )
        available_years = sorted(daily_pnl["year"].unique().tolist())

        if "pnl_month_idx" not in st.session_state or \
           st.session_state.pnl_month_idx >= len(available_months):
            st.session_state.pnl_month_idx = len(available_months) - 1
        if "pnl_year_idx" not in st.session_state or \
           st.session_state.pnl_year_idx >= len(available_years):
            st.session_state.pnl_year_idx = len(available_years) - 1

        def pnl_month_prev():
            if st.session_state.pnl_month_idx > 0:
                st.session_state.pnl_month_idx -= 1
        def pnl_month_next():
            if st.session_state.pnl_month_idx < len(available_months) - 1:
                st.session_state.pnl_month_idx += 1
        def pnl_year_prev():
            if st.session_state.pnl_year_idx > 0:
                st.session_state.pnl_year_idx -= 1
        def pnl_year_next():
            if st.session_state.pnl_year_idx < len(available_years) - 1:
                st.session_state.pnl_year_idx += 1

        sel_ym = available_months[st.session_state.pnl_month_idx]
        sel_yr = available_years[st.session_state.pnl_year_idx]

        max_day = _cal.monthrange(sel_ym[0], sel_ym[1])[1]
        all_days = pd.DataFrame({"day": range(1, max_day + 1)})
        m_data = all_days.merge(
            daily_pnl[(daily_pnl["year"] == sel_ym[0]) & (daily_pnl["month"] == sel_ym[1])][["day","pnl"]],
            on="day", how="left"
        )
        m_total = m_data["pnl"].sum(skipna=True)

        all_months_df = pd.DataFrame({"month": range(1, 13)})
        y_data = all_months_df.merge(
            monthly_pnl[monthly_pnl["year"] == sel_yr][["month","pnl"]],
            on="month", how="left"
        )
        y_total = y_data["pnl"].sum(skipna=True)

        st.subheader("P&L by Delivery Date")
        chart_l, chart_r = st.columns(2)

        with chart_l:
            na, nb, nc = st.columns([0.08, 0.84, 0.08])
            with na:
                st.markdown('<div class="pnl-nav-btn">', unsafe_allow_html=True)
                st.button("◀", on_click=pnl_month_prev, key="pnl_m_prev", use_container_width=True)
                st.markdown('</div>', unsafe_allow_html=True)
            with nb:
                st.markdown(
                    f"<div style='text-align:center;font-size:1.25rem;font-weight:700;"
                    f"line-height:2rem'>{MONTH_FULL[sel_ym[1]]} {sel_ym[0]}</div>",
                    unsafe_allow_html=True)
            with nc:
                st.markdown('<div class="pnl-nav-btn">', unsafe_allow_html=True)
                st.button("▶", on_click=pnl_month_next, key="pnl_m_next", use_container_width=True)
                st.markdown('</div>', unsafe_allow_html=True)
            mc = "#2dc653" if m_total >= 0 else "#e63946"
            st.markdown(
                f"<p style='color:{mc};font-weight:600;margin:2px 0 6px 0;font-size:2rem'>"
                f"P&L: {m_total:,.0f} PLN</p>",
                unsafe_allow_html=True)
            bar_colors_d = ["#2dc653" if (v is not None and not pd.isna(v) and v >= 0)
                            else "#e63946" if (v is not None and not pd.isna(v))
                            else "rgba(0,0,0,0)" for v in m_data["pnl"]]
            fig_d = go.Figure(go.Bar(
                x=m_data["day"], y=m_data["pnl"],
                marker_color=bar_colors_d,
                hovertemplate="Day %{x}<br>P&L: %{y:,.0f} PLN<extra></extra>",
            ))
            fig_d.add_hline(y=0, line_dash="dash", line_color="#aaa")
            fig_d.update_layout(**CHART_THEME,
                xaxis=dict(title="Day", tickmode="linear", dtick=1,
                           range=[0.5, max_day + 0.5], gridcolor="#eee"),
                yaxis=dict(title="PLN", gridcolor="#eee"),
                height=300, margin=dict(t=10, b=40),
            )
            st.plotly_chart(fig_d, use_container_width=True)

        with chart_r:
            ya, yb, yc_col = st.columns([0.08, 0.84, 0.08])
            with ya:
                st.markdown('<div class="pnl-nav-btn">', unsafe_allow_html=True)
                st.button("◀", on_click=pnl_year_prev, key="pnl_y_prev", use_container_width=True)
                st.markdown('</div>', unsafe_allow_html=True)
            with yb:
                st.markdown(
                    f"<div style='text-align:center;font-size:1.25rem;font-weight:700;"
                    f"line-height:2rem'>{sel_yr}</div>",
                    unsafe_allow_html=True)
            with yc_col:
                st.markdown('<div class="pnl-nav-btn">', unsafe_allow_html=True)
                st.button("▶", on_click=pnl_year_next, key="pnl_y_next", use_container_width=True)
                st.markdown('</div>', unsafe_allow_html=True)
            yc = "#2dc653" if y_total >= 0 else "#e63946"
            st.markdown(
                f"<p style='color:{yc};font-weight:600;margin:2px 0 6px 0;font-size:2rem'>"
                f"P&L: {y_total:,.0f} PLN</p>",
                unsafe_allow_html=True)
            bar_colors_m = ["#2dc653" if (v is not None and not pd.isna(v) and v >= 0)
                            else "#e63946" if (v is not None and not pd.isna(v))
                            else "rgba(0,0,0,0)" for v in y_data["pnl"]]
            fig_m = go.Figure(go.Bar(
                x=y_data["month"], y=y_data["pnl"],
                marker_color=bar_colors_m,
                hovertemplate="%{customdata}<br>P&L: %{y:,.0f} PLN<extra></extra>",
                customdata=[MONTH_NAMES[m] for m in y_data["month"]],
            ))
            fig_m.add_hline(y=0, line_dash="dash", line_color="#aaa")
            fig_m.update_layout(**CHART_THEME,
                xaxis=dict(title="Month", tickmode="array",
                           tickvals=list(range(1, 13)),
                           ticktext=[MONTH_NAMES[m] for m in range(1, 13)],
                           gridcolor="#eee"),
                yaxis=dict(title="PLN", gridcolor="#eee"),
                height=300, margin=dict(t=10, b=40),
            )
            st.plotly_chart(fig_m, use_container_width=True)
    else:
        st.info("No data to display — select at least one segment above.")

    # ── Export Trades ─────────────────────────────────────────────────────────
    st.divider()
    with st.expander("Export Trades"):
        _ec1, _ec2, _ec3, _ = st.columns([0.4, 0.4, 0.75, 8.45])
        _xfix  = _ec1.checkbox("FIX",    value=True,  key="xp_fix")
        _xtso  = _ec2.checkbox("TSO",    value=True,  key="xp_tso")
        _xwkly = _ec3.checkbox("WEEKLY", value=True,  key="xp_weekly")

        _xdates = []
        if _xfix  and not df_fix.empty:    _xdates += list(df_fix["delivery_date"])
        if _xtso  and not df_tso.empty:    _xdates += list(df_tso["delivery_date"])
        if _xwkly and not df_weekly.empty: _xdates += list(df_weekly["delivery_end"])
        _xmin = min(_xdates) if _xdates else date.today()
        _xmax = max(_xdates) if _xdates else date.today()

        _xd1, _xd2 = st.columns(2)
        _x_from = _xd1.date_input("Delivery date from", value=_xmin, key="xp_from")
        _x_to   = _xd2.date_input("Delivery date to",   value=_xmax, key="xp_to")

        _xcount = 0
        if _xfix  and not df_fix.empty:
            _xcount += len(df_fix[(df_fix["delivery_date"] >= _x_from) & (df_fix["delivery_date"] <= _x_to)])
        if _xtso  and not df_tso.empty:
            _xcount += len(df_tso[(df_tso["delivery_date"] >= _x_from) & (df_tso["delivery_date"] <= _x_to)])
        if _xwkly and not df_weekly.empty:
            _xcount += len(df_weekly[(df_weekly["delivery_end"] >= _x_from) & (df_weekly["delivery_end"] <= _x_to)])
        st.caption(f"{_xcount} trade(s) in selection")

        _segs  = (["FIX"] if _xfix else []) + (["TSO"] if _xtso else []) + (["WKL"] if _xwkly else [])
        _fname = f"Trades_{date.today().strftime('%Y%m%d')}_{'_'.join(_segs) if _segs else 'ALL'}.xlsx"
        _buf   = io.BytesIO()
        try:
            with pd.ExcelWriter(_buf, engine="openpyxl") as _xw:
                _sum_rows = []

                if _xfix and not df_fix.empty:
                    _xdf = df_fix[(df_fix["delivery_date"] >= _x_from) & (df_fix["delivery_date"] <= _x_to)].copy()
                    _sum_rows.append({"Segment":"FIX","Trades":len(_xdf),
                                      "P&L PLN":round(float(_xdf["pnl"].sum()),2),
                                      "Volume MWh":round(float(_xdf["volume_mw"].sum()),2)})
                    _xdf["Hour"] = _xdf["hour"].apply(lambda h: f"H{int(h):02d}")
                    _xdf = _xdf.rename(columns={"fixing_date":"Fixing Date","delivery_date":"Delivery Date",
                        "direction":"Direction","volume_mw":"Volume MW","f1_price":"F1 PLN",
                        "sdac_price":"SDAC PLN","spread":"Spread","pnl":"P&L PLN"})
                    _fix_cols = [c for c in ["Fixing Date","Delivery Date","Hour","Direction",
                                             "Volume MW","F1 PLN","SDAC PLN","Spread","P&L PLN"]
                                 if c in _xdf.columns]
                    _xdf[_fix_cols].sort_values(["Fixing Date","Hour"]).to_excel(
                        _xw, sheet_name="FIX Trades", index=False)

                if _xtso and not df_tso.empty:
                    _xdf = df_tso[(df_tso["delivery_date"] >= _x_from) & (df_tso["delivery_date"] <= _x_to)].copy()
                    _sum_rows.append({"Segment":"TSO","Trades":len(_xdf),
                                      "P&L PLN":round(float(_xdf["pnl"].sum()),2),
                                      "Volume MWh":round(float(_xdf["volume_mw"].sum()*0.25),2)})
                    _xdf["Slot"] = _xdf.apply(lambda r: f"H{int(r['hour']):02d}Q{int(r['quarter'])}", axis=1)
                    _xdf = _xdf.rename(columns={"fixing_date":"Fixing Date","delivery_date":"Delivery Date",
                        "direction":"Direction","volume_mw":"Volume MW","f2_price":"F2 PLN",
                        "cen_price":"CEN PLN","spread":"Spread","pnl":"P&L PLN"})
                    _tso_cols = [c for c in ["Fixing Date","Delivery Date","Slot","Direction",
                                             "Volume MW","F2 PLN","CEN PLN","Spread","P&L PLN"]
                                 if c in _xdf.columns]
                    _xdf[_tso_cols].sort_values(["Fixing Date","Slot"]).to_excel(
                        _xw, sheet_name="TSO Trades", index=False)

                if _xwkly and not df_weekly.empty:
                    _xdf = df_weekly[(df_weekly["delivery_end"] >= _x_from) & (df_weekly["delivery_end"] <= _x_to)].copy()
                    _sum_rows.append({"Segment":"WEEKLY","Trades":len(_xdf),
                                      "P&L PLN":round(float(_xdf["pnl"].sum()),2),
                                      "Volume MWh":round(float((_xdf["volume_mw"]*_xdf["hours"]).sum()),2)})
                    _xdf = _xdf.rename(columns={"tx_date":"Tx Date","product":"Product",
                        "delivery_start":"Delivery Start","delivery_end":"Delivery End",
                        "direction":"Direction","volume_mw":"Volume MW","hours":"Hours",
                        "trade_price":"Trade Price PLN","avg_f1":"Avg F1 PLN","pnl":"P&L PLN"})
                    _wk_cols = [c for c in ["Tx Date","Product","Delivery Start","Delivery End",
                                            "Direction","Volume MW","Hours","Trade Price PLN",
                                            "Avg F1 PLN","P&L PLN"] if c in _xdf.columns]
                    _xdf[_wk_cols].sort_values("Delivery Start").to_excel(
                        _xw, sheet_name="WEEKLY Trades", index=False)

                pd.DataFrame(_sum_rows).to_excel(_xw, sheet_name="Summary", index=False)

            _buf.seek(0)
            st.download_button(
                label=f"Download  {_fname}",
                data=_buf.getvalue(),
                file_name=_fname,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="xp_dl",
                type="primary",
            )
        except ImportError:
            st.warning("openpyxl not installed — run: pip install openpyxl")





def render_fix_heatmap():
    prices = load_prices()
    st.markdown("""
    <div style="
        position: sticky;
        top: 0;
        z-index: 999;
        background: white;
        padding: 10px 0 12px 0;
        border-bottom: 1px solid #e0e0e0;
        margin-bottom: 12px;
    ">
        <div style="display:flex; align-items:center; gap:16px;">
            <h1 style="margin:0; font-size:2rem; flex:2; white-space:nowrap;">
                FixHeatmap — F1 vs SDAC
            </h1>
            <div style="flex:1; background:#e63946; padding:8px 14px; border-radius:6px;
                        text-align:center; color:#fff; font-weight:600;">
                &#9632; F1 &gt; SDAC — Sell F1
            </div>
            <div style="flex:1; background:#2dc653; padding:8px 14px; border-radius:6px;
                        text-align:center; color:#000; font-weight:600;">
                &#9632; F1 &lt; SDAC — Buy F1
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Staleness indicator + Update button ──────────────────────────────────
    _last_delivery = prices[prices["H"] >= 1]["delivery_date"].max()
    _today         = date.today()
    _days_old      = (_today - _last_delivery).days
    _freshness_color = "#2dc653" if _days_old == 0 else ("#e65100" if _days_old == 1 else "#e63946")
    _freshness_label = (
        "up to date" if _days_old == 0
        else f"{_days_old} day(s) behind — today's delivery missing"
    )

    ctrl1, ctrl1b, ctrl2, ctrl3 = st.columns([1, 0.7, 1, 2])
    with ctrl1:
        n_days = st.selectbox("Show last N days", [7, 14, 30, 60, 90, 999], index=0,
                              format_func=lambda x: "All" if x == 999 else f"{x} days")
    with ctrl1b:
        st.markdown("<br>", unsafe_allow_html=True)
        show_spread = st.checkbox("Spread", value=False, key="hm_spread")
    with ctrl2:
        st.markdown(
            f"<div style='padding-top:8px;font-size:0.9rem;'>"
            f"Last delivery: <b>{_last_delivery}</b><br>"
            f"<span style='color:{_freshness_color};font-weight:600;'>{_freshness_label}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
    with ctrl3:
        if st.button("Update Prices", key="hm_update"):
            import importlib.util as _ilu, sys as _sys
            _root = APP_DIR
            _sys.path.insert(0, os.path.join(_root, "procedures"))
            _spec = _ilu.spec_from_file_location(
                "tge_fixing", os.path.join(_root, "procedures", "tge_fixing.py"))
            _mod = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            _lines = []
            with st.spinner("Downloading from TGE..."):
                _result = _mod.run_pipeline(
                    app_dir=_root, log=lambda m: _lines.append(m))
            load_prices.clear()
            if _result["status"] == "ok":
                st.success(_result["message"])
            else:
                st.error(_result["message"])
            with st.expander("Pipeline log"):
                st.text("\n".join(_lines))
            st.rerun()

    hm = prices[prices["H"] >= 1].copy().dropna(subset=["spread_f1_sdac"])
    all_deliv = sorted(hm["delivery_date"].unique())
    if n_days != 999:
        all_deliv = all_deliv[-n_days:]
    hm = hm[hm["delivery_date"].isin(all_deliv)]

    hours = list(range(1, 25))
    dates = sorted(hm["delivery_date"].unique())
    z_color, z_spread = [], []

    for d in dates:
        row_c, row_s = [], []
        for h in hours:
            cell = hm[(hm["delivery_date"] == d) & (hm["H"] == h)]
            if cell.empty or pd.isna(cell.iloc[0]["spread_f1_sdac"]):
                row_c.append(0); row_s.append(None)
            else:
                s = cell.iloc[0]["spread_f1_sdac"]
                row_c.append(1 if s > 0 else (-1 if s < 0 else 0))
                row_s.append(round(s, 2))
        z_color.append(row_c); z_spread.append(row_s)

    date_labels = [d.strftime("%d.%m") for d in dates]
    _cell = 38
    _lm, _rm, _tm, _bm = 75, 20, 30, 60
    _fig_w = len(hours) * _cell + _lm + _rm   # 24*38 + 95 ≈ 1007
    _fig_h = len(dates) * _cell + _tm + _bm
    fig = go.Figure(go.Heatmap(
        z=z_color, x=hours, y=date_labels,
        customdata=z_spread,
        colorscale=[[0.0,"#2dc653"],[0.5,"#cccccc"],[1.0,"#e63946"]],
        zmin=-1, zmax=1, showscale=False,
        hovertemplate="<b>%{y}  H%{x:02d}</b><br>Spread: %{customdata:.2f} PLN/MWh<extra></extra>",
        xgap=2, ygap=2,
    ))
    fig.update_layout(
        **CHART_THEME,
        xaxis=dict(title="Hour", tickmode="linear", dtick=1, side="bottom"),
        yaxis=dict(title="", type="category", autorange="reversed",
                   tickfont=dict(size=12, family="monospace")),
        width=_fig_w, height=_fig_h,
        margin=dict(t=_tm, b=_bm, l=_lm, r=_rm),
    )
    if show_spread:
        x_black, y_black, t_black = [], [], []
        x_white, y_white, t_white = [], [], []
        for i, dl in enumerate(date_labels):
            for j, h in enumerate(hours):
                s = z_spread[i][j]
                if s is not None:
                    if z_color[i][j] < 0:
                        x_white.append(h); y_white.append(dl); t_white.append(f"{s:.0f}")
                    elif z_color[i][j] > 0:
                        x_black.append(h); y_black.append(dl); t_black.append(f"{s:.0f}")
        if x_black:
            fig.add_trace(go.Scatter(x=x_black, y=y_black, text=t_black,
                mode="text", textfont=dict(size=11, color="black"),
                showlegend=False, hoverinfo="skip"))
        if x_white:
            fig.add_trace(go.Scatter(x=x_white, y=y_white, text=t_white,
                mode="text", textfont=dict(size=11, color="white"),
                showlegend=False, hoverinfo="skip"))
    st.plotly_chart(fig, use_container_width=False)

    # ── Probability of success per hour ──────────────────────────────────────
    st.divider()
    st.subheader(f"Signal probability — last {n_days if n_days != 999 else 'all'} day(s)")
    st.caption(
        "For each hour: probability of the **dominant** signal (whichever side — Buy F1 long "
        "or Sell F1 short — is more likely). Bar height = strength of that edge, so the tallest "
        "bars (green or red) mark the hours with the best odds. "
        "Green = Buy F1 (long F1) dominant · Red = Sell F1 (short F1) dominant · 50% = no edge."
    )

    # Count Buy F1 days (spread < 0) and total priced days per hour
    prob_buy  = []   # % of days where spread < 0  (Buy F1)
    prob_sell = []   # % of days where spread > 0  (Sell F1)
    total_days_h = []
    for h in hours:
        col_h = hm[hm["H"] == h]["spread_f1_sdac"].dropna()
        n_total = len(col_h)
        n_buy   = (col_h < 0).sum()
        n_sell  = (col_h > 0).sum()
        pct_buy  = round(n_buy  / n_total * 100, 1) if n_total else 0
        pct_sell = round(n_sell / n_total * 100, 1) if n_total else 0
        prob_buy.append(pct_buy)
        prob_sell.append(pct_sell)
        total_days_h.append(n_total)

    # Bar height = probability of the DOMINANT side (whichever is > 50%),
    # so a tall red bar means a strong/likely Sell F1 signal — not a weak Buy F1 one.
    dom_prob   = []
    dom_side   = []
    bar_colors_prob = []
    for b, s in zip(prob_buy, prob_sell):
        if b > 50:
            dom_prob.append(b); dom_side.append("Buy F1 (long)");  bar_colors_prob.append("#2dc653")
        elif s > 50:
            dom_prob.append(s); dom_side.append("Sell F1 (short)"); bar_colors_prob.append("#e63946")
        else:
            dom_prob.append(b); dom_side.append("No edge");        bar_colors_prob.append("#cccccc")

    fig_prob = go.Figure()
    fig_prob.add_hline(y=50, line_dash="dash", line_color="#aaa", line_width=1)
    fig_prob.add_trace(go.Bar(
        x=hours,
        y=dom_prob,
        marker_color=bar_colors_prob,
        customdata=list(zip(dom_side, prob_buy, prob_sell, total_days_h)),
        hovertemplate=(
            "<b>H%{x:02d}</b><br>"
            "Dominant: %{customdata[0]} — %{y:.1f}%<br>"
            "Buy F1:  %{customdata[1]:.1f}%<br>"
            "Sell F1: %{customdata[2]:.1f}%<br>"
            "Days: %{customdata[3]}<extra></extra>"
        ),
        text=[f"{v:.0f}%" for v in dom_prob],
        textposition="outside",
        textfont=dict(size=10),
    ))
    fig_prob.update_layout(
        **CHART_THEME,
        xaxis=dict(title="Hour", tickmode="linear", dtick=1,
                   range=[0.5, 24.5], gridcolor="#eee", linecolor="#ccc"),
        yaxis=dict(title="Dominant signal probability (%)", range=[0, 115],
                   gridcolor="#eee", linecolor="#ccc",
                   tickvals=[0, 25, 50, 75, 100],
                   ticktext=["0%", "25%", "50%", "75%", "100%"]),
        height=280, margin=dict(t=20, b=40),
        showlegend=False,
    )
    st.plotly_chart(fig_prob, use_container_width=True)

    # ── Signal with weights ───────────────────────────────────────────────────
    st.divider()
    st.subheader("Signal — with weights")

    _lam_col, _ = st.columns([1, 3])
    with _lam_col:
        lam = st.slider("Decay factor λ", min_value=0.50, max_value=1.00,
                        value=0.80, step=0.05,
                        help="1.0 = all days equal  ·  lower = recent days dominate")

    # Effective weight ratio: newest / oldest  = λ^0 / λ^(N-1) = 1 / λ^(N-1)
    _n_used = len(dates)
    if lam < 1.0 and _n_used > 1:
        _ratio = round(1 / lam ** (_n_used - 1), 1)
        st.caption(f"Yesterday weighs **{_ratio}×** more than the oldest day in the window "
                   f"({_n_used} days, λ = {lam})")
    else:
        st.caption(f"λ = 1.0 — all {_n_used} days carry equal weight (same as chart above)")

    # Build date-ordered list for this window (oldest → newest)
    _dates_ordered = sorted(dates)   # ascending = oldest first

    w_prob_buy  = []
    w_prob_sell = []
    for h in hours:
        _numerator   = 0.0
        _denominator = 0.0
        for _k, _d in enumerate(_dates_ordered):
            # k=0 oldest, k=N-1 newest → weight = λ^(N-1-k)
            _w = lam ** (_n_used - 1 - _k)
            _cell = hm[(hm["delivery_date"] == _d) & (hm["H"] == h)]["spread_f1_sdac"]
            if _cell.empty or pd.isna(_cell.iloc[0]):
                continue
            _is_buy = 1.0 if _cell.iloc[0] < 0 else 0.0
            _numerator   += _w * _is_buy
            _denominator += _w
        _p_buy = round(_numerator / _denominator * 100, 1) if _denominator > 0 else 0.0
        w_prob_buy.append(_p_buy)
        w_prob_sell.append(round(100 - _p_buy, 1) if _denominator > 0 else 0.0)

    # Bar height = weighted probability of the DOMINANT side, same logic as the
    # unweighted chart above — a tall red bar means a strong/likely Sell F1 signal.
    w_dom_prob = []
    w_dom_side = []
    _bar_colors_w = []
    for b, s in zip(w_prob_buy, w_prob_sell):
        if b > 50:
            w_dom_prob.append(b); w_dom_side.append("Buy F1 (long)");   _bar_colors_w.append("#2dc653")
        elif s > 50:
            w_dom_prob.append(s); w_dom_side.append("Sell F1 (short)"); _bar_colors_w.append("#e63946")
        else:
            w_dom_prob.append(b); w_dom_side.append("No edge");         _bar_colors_w.append("#cccccc")

    fig_w = go.Figure()
    fig_w.add_hline(y=50, line_dash="dash", line_color="#aaa", line_width=1)

    # Faint reference bars from unweighted chart (same dominant-probability logic)
    fig_w.add_trace(go.Bar(
        x=hours, y=dom_prob,
        marker_color="rgba(180,180,180,0.35)",
        name="Unweighted (ref)",
        hoverinfo="skip",
    ))
    # Weighted bars
    fig_w.add_trace(go.Bar(
        x=hours, y=w_dom_prob,
        marker_color=_bar_colors_w,
        name="Weighted",
        customdata=list(zip(w_dom_side, w_prob_buy, w_prob_sell)),
        hovertemplate=(
            "<b>H%{x:02d}</b><br>"
            "Dominant: %{customdata[0]} — %{y:.1f}%<br>"
            "Buy F1:  %{customdata[1]:.1f}%<br>"
            "Sell F1: %{customdata[2]:.1f}%<extra></extra>"
        ),
        text=[f"{v:.0f}%" for v in w_dom_prob],
        textposition="outside",
        textfont=dict(size=10),
    ))
    fig_w.update_layout(
        **CHART_THEME,
        barmode="overlay",
        xaxis=dict(title="Hour", tickmode="linear", dtick=1,
                   range=[0.5, 24.5], gridcolor="#eee", linecolor="#ccc"),
        yaxis=dict(title="Weighted dominant signal probability (%)", range=[0, 115],
                   gridcolor="#eee", linecolor="#ccc",
                   tickvals=[0, 25, 50, 75, 100],
                   ticktext=["0%", "25%", "50%", "75%", "100%"]),
        height=280, margin=dict(t=20, b=40),
        legend=dict(orientation="h", y=1.12, x=0),
    )
    st.plotly_chart(fig_w, use_container_width=True)

    st.markdown(f"""
    **How it is calculated**

    For each hour H01–H24, the algorithm looks at all **{_n_used} days** in the selected window and
    asks: was F1 < SDAC on that day (Buy F1 signal)?

    Each day receives an exponential weight:

    > weight = λ^(N − 1 − k)

    where **k = 0** is the oldest day and **k = N − 1** is yesterday (most recent).
    At λ = {lam}, yesterday's weight is **{round(lam**0, 2)}** and the oldest day's weight is
    **{round(lam**(_n_used-1), 3)}**.

    The weighted probability is then:

    > P(Buy F1) = Σ(weight × is_buy) / Σ(weight)

    The bar shows the **dominant** side's probability — whichever of Buy F1 (long) or
    Sell F1 (short) is above 50% — with recent days counted more heavily. So a tall green
    bar means a strong, likely Buy F1 edge, and a tall red bar means an equally strong,
    likely Sell F1 edge: bar height always reflects how strong the edge is, not which
    direction it points. The faint grey bars show the unweighted result (same logic) for comparison.
    """)

    # ════════════════════════════════════════════════════════════════════════
    # FixHeatmap v2 — Edge Score module
    # ════════════════════════════════════════════════════════════════════════
    st.divider()
    st.markdown("## FixHeatmap v2 — Edge Score")
    st.caption(
        "Combines directional probability and spread magnitude into a single score per hour, "
        "to highlight the hours with the most statistically and economically meaningful edge."
    )

    with st.expander("ℹ️ How the Edge Score is calculated"):
        st.markdown(r"""
**Edge Score** combines two things into one number, for each hour (H01–H24):

1. **Directional probability** — `ProbabilityLONG`: the share of days in the selected window
   where the spread (SDAC − F1) was positive, i.e. F1 traded *below* SDAC
   (a **LONG / Buy F1 / Sell SDAC** day). `ProbabilitySHORT = 1 − ProbabilityLONG`.
2. **Spread magnitude** — `P75(|Spread|)`: the 75ᵗʰ percentile of the *absolute* spread within
   the window. P75 captures economically meaningful moves while staying robust to one-off
   outliers — better than the median (too conservative) and less noisy than the max.

> **Edge = (2 × ProbabilityLONG − 1) × P75(|Spread|)**

- **Edge > 0** → **LONG bias** (Buy F1 / Sell SDAC tends to win in that hour)
- **Edge < 0** → **SHORT bias** (Sell F1 / Buy SDAC tends to win in that hour)
- The further from zero, the stronger **and** more consistent the historical edge —
  a hand-picked combination of "how often" and "how much".

**Signal strength legend** (based on |Edge|, calibrated on ~6 months / ~4,200 hourly observations):

| \|Edge\| | Signal |
|---|---|
| < 3 | No edge / No trade |
| 3 – 7 | Weak signal |
| 7 – 12 | Moderate signal |
| 12 – 18 | Strong signal |
| 18 – 25 | Very strong signal |
| ≥ 25 | Exceptional signal |

*Current version uses historical Fixing1 vs Fixing2 (SDAC) statistics only — a future version will
combine this Edge Score with forecast-model accuracy and PnL performance (XGBoost, Random Forest,
SARIMAX, ARIMA).*
        """)

    _v2_col, _ = st.columns([1, 3])
    with _v2_col:
        v2_window = st.selectbox("Rolling window", [3, 5, 7, 14, 30], index=3,
                                 format_func=lambda x: f"{x} days", key="v2_window")

    # Independent rolling window: most recent N delivery days with valid spread data
    _v2_all_dates = sorted(
        prices[prices["H"] >= 1].dropna(subset=["spread_f1_sdac"])["delivery_date"].unique()
    )
    _v2_dates = _v2_all_dates[-v2_window:]
    _v2_hm = prices[
        (prices["H"] >= 1) & (prices["delivery_date"].isin(_v2_dates))
    ].dropna(subset=["spread_f1_sdac"])

    if len(_v2_dates) < v2_window:
        st.caption(f"⚠️ Only {len(_v2_dates)} day(s) with data available for this window.")

    _v2_rows = []
    for h in hours:
        _col = _v2_hm[_v2_hm["H"] == h]
        # Spec convention: Spread = Fixing2 (SDAC) − Fixing1  ==  −spread_f1_sdac
        _spec_spread = -_col["spread_f1_sdac"]
        _n_total = len(_spec_spread)
        if _n_total == 0:
            continue
        _prob_long  = float((_spec_spread > 0).sum()) / _n_total
        _prob_short = 1.0 - _prob_long
        _p75_abs    = float(_spec_spread.abs().quantile(0.75))
        _edge       = (2 * _prob_long - 1) * _p75_abs
        _v2_rows.append({
            "Hour": h, "ProbLong": _prob_long, "ProbShort": _prob_short,
            "P75Spread": _p75_abs, "Edge": _edge, "N": _n_total,
        })

    _v2_df = pd.DataFrame(_v2_rows)

    if _v2_df.empty:
        st.info("Not enough data to compute the Edge Score for this window.")
    else:
        # ── Probability chart (LONG vs SHORT, stacked to 100%) ───────────────
        st.subheader(f"Probability by hour — last {v2_window} day(s)")
        st.caption(
            "ProbabilityLONG = share of days with positive spread (SDAC > F1 → Buy F1 / Sell SDAC) · "
            "ProbabilitySHORT = 1 − ProbabilityLONG."
        )
        fig_v2p = go.Figure()
        fig_v2p.add_trace(go.Bar(
            x=_v2_df["Hour"], y=_v2_df["ProbLong"] * 100,
            name="LONG", marker_color="#2dc653",
            hovertemplate="<b>H%{x:02d}</b><br>P(LONG): %{y:.0f}%<extra></extra>",
        ))
        fig_v2p.add_trace(go.Bar(
            x=_v2_df["Hour"], y=_v2_df["ProbShort"] * 100,
            name="SHORT", marker_color="#e63946",
            hovertemplate="<b>H%{x:02d}</b><br>P(SHORT): %{y:.0f}%<extra></extra>",
        ))
        fig_v2p.update_layout(
            **CHART_THEME,
            barmode="stack",
            xaxis=dict(title="Hour", tickmode="linear", dtick=1, range=[0.5, 24.5],
                       gridcolor="#eee", linecolor="#ccc"),
            yaxis=dict(title="Probability (%)", range=[0, 100],
                       gridcolor="#eee", linecolor="#ccc"),
            height=260, margin=dict(t=20, b=40),
            legend=dict(orientation="h", y=1.15, x=0),
        )
        st.plotly_chart(fig_v2p, use_container_width=True)

        # ── Edge Score chart ──────────────────────────────────────────────────
        st.subheader("Edge Score by hour")
        _edge_colors = [
            "#2dc653" if e > 0 else ("#e63946" if e < 0 else "#cccccc")
            for e in _v2_df["Edge"]
        ]
        fig_edge = go.Figure()
        fig_edge.add_hline(y=0, line_color="#aaa", line_width=1)
        fig_edge.add_trace(go.Bar(
            x=_v2_df["Hour"], y=_v2_df["Edge"],
            marker_color=_edge_colors,
            customdata=list(zip(_v2_df["ProbLong"] * 100, _v2_df["P75Spread"], _v2_df["Edge"])),
            hovertemplate=(
                "<b>H%{x:02d}</b><br>"
                "ProbabilityLONG: %{customdata[0]:.0f}%<br>"
                "P75 |Spread|: %{customdata[1]:.1f} PLN<br>"
                "Edge Score: %{customdata[2]:.1f}<extra></extra>"
            ),
            text=[f"{e:.1f}" for e in _v2_df["Edge"]],
            textposition="outside",
            textfont=dict(size=10),
        ))
        fig_edge.update_layout(
            **CHART_THEME,
            xaxis=dict(title="Hour", tickmode="linear", dtick=1, range=[0.5, 24.5],
                       gridcolor="#eee", linecolor="#ccc"),
            yaxis=dict(title="Edge Score", gridcolor="#eee", linecolor="#ccc"),
            height=300, margin=dict(t=30, b=40),
            showlegend=False,
        )
        st.plotly_chart(fig_edge, use_container_width=True)

        # ── Trading ranking table ─────────────────────────────────────────────
        st.subheader("Trading ranking")
        st.caption("Sorted by |Edge Score|, descending — the top rows are the hours with the strongest historical edge.")

        def _signal_strength(abs_edge):
            if abs_edge < 3:   return "No edge / No trade"
            if abs_edge < 7:   return "Weak signal"
            if abs_edge < 12:  return "Moderate signal"
            if abs_edge < 18:  return "Strong signal"
            if abs_edge < 25:  return "Very strong signal"
            return "Exceptional signal"

        _rank = _v2_df.copy()
        _rank["Direction"] = _rank["Edge"].apply(
            lambda e: "LONG" if e > 0 else ("SHORT" if e < 0 else "—"))
        _rank["AbsEdge"] = _rank["Edge"].abs()
        _rank["Signal Strength"] = _rank["AbsEdge"].apply(_signal_strength)
        _rank = _rank.sort_values("AbsEdge", ascending=False)

        _rank_disp = pd.DataFrame({
            "Hour":            _rank["Hour"],
            "Direction":       _rank["Direction"],
            "ProbabilityLONG": (_rank["ProbLong"] * 100).round(0).astype(int).astype(str) + "%",
            "P75 |Spread|":    _rank["P75Spread"].round(1),
            "Edge Score":      _rank["Edge"].round(1),
            "Signal Strength": _rank["Signal Strength"],
        })

        def _color_dir(val):
            if val == "LONG":  return "background-color:#c8f7c5;color:#155724"
            if val == "SHORT": return "background-color:#fcd5d5;color:#7b0000"
            return ""

        st.dataframe(
            _rank_disp.style.applymap(_color_dir, subset=["Direction"]),
            use_container_width=True, hide_index=True, height=400,
        )

    # ════════════════════════════════════════════════════════════════════════
    # FixHeatmap v2.2 — Edge Score with Decay
    # ════════════════════════════════════════════════════════════════════════
    st.divider()
    st.markdown("## FixHeatmap v2.2 — Edge Score with Decay")
    st.caption(
        "An enhanced version of the Edge Score that gives more weight to recent observations. "
        "Recent days matter more than distant ones — this module captures that by applying "
        "exponential decay to the probability calculation."
    )

    with st.expander("ℹ️ How the Edge Score with Decay is calculated"):
        st.markdown(r"""
**Edge Score with Decay** is an enhancement of the basic Edge Score (v2). The key difference:
instead of treating all historical days equally, it assigns **exponentially larger weights to more
recent observations** — on the assumption that recent market behaviour is more relevant than what
happened two weeks ago.

**Step 1 — Decay weights**

For each day in the lookback window, a weight is assigned:

> weight = λ^(N − 1 − k)

where:
- **N** = number of days in the lookback window
- **k** = day index (0 = oldest, N−1 = most recent)
- **λ** (Lambda) = decay parameter chosen by the user

The most recent day always receives weight **1.0**. Older days receive exponentially less weight.

Example at λ = 0.8, window = 5 days: weights are 0.41 → 0.51 → 0.64 → 0.80 → 1.00

At λ = 1.0 all days receive equal weight — identical to the unweighted v2.

**Step 2 — Weighted directional probability**

For each hour H01–H24:

> P_buy_weighted = Σ(weight × is_buy) / Σ(weight)

where `is_buy = 1` if SDAC > F1 on that day (Buy F1 / Sell SDAC), 0 otherwise.

**Step 3 — Edge Score**

> weighted_direction = 2 × P_buy_weighted − 1
> Edge = weighted_direction × P75(|Spread|)

*P75 of the absolute spread is unweighted — it captures the economic magnitude of the spread
over the full lookback window, independent of recency.*

**Comparison with v2:**

| | v2 (unweighted) | v2.2 (with decay) |
|---|---|---|
| Probability | Each day counts equally | Recent days count more |
| Spread magnitude | P75 of window | P75 of window (same) |
| Best for | Stable, slowly-changing patterns | Markets reacting to recent conditions |

Recommended settings: **Lookback = 5 days, Lambda = 0.8**

**Signal strength legend** (calibrated on ~6 months of historical data):

| \|Edge\| | Signal |
|---|---|
| 0 – 7 | No edge / No trade |
| 7 – 18 | Moderate signal |
| 18 – 25 | Strong signal |
| ≥ 25 | Exceptional signal |
        """)

    _v22_c1, _v22_c2, _ = st.columns([1, 1, 2])
    with _v22_c1:
        v22_window = st.selectbox("Lookback window", [3, 5, 7, 14, 30], index=1,
                                  format_func=lambda x: f"{x} days", key="v22_window")
    with _v22_c2:
        v22_lambda = st.selectbox("Lambda (λ)", [0.6, 0.7, 0.8, 0.9, 1.0], index=2,
                                  key="v22_lambda")

    _v22_all_dates = sorted(
        prices[prices["H"] >= 1].dropna(subset=["spread_f1_sdac"])["delivery_date"].unique()
    )
    _v22_dates = sorted(_v22_all_dates[-v22_window:])
    _v22_hm = prices[
        (prices["H"] >= 1) & (prices["delivery_date"].isin(_v22_dates))
    ].dropna(subset=["spread_f1_sdac"])

    if len(_v22_dates) < v22_window:
        st.caption(f"⚠️ Only {len(_v22_dates)} day(s) with data available for this window.")

    _v22_n = len(_v22_dates)
    _v22_rows = []
    for h in hours:
        _col22 = _v22_hm[_v22_hm["H"] == h]
        _spec22 = -_col22["spread_f1_sdac"]  # SDAC − F1; positive = Buy F1 / LONG
        _n22 = len(_spec22)
        if _n22 == 0:
            continue
        _prob_long_uw22 = float((_spec22 > 0).sum()) / _n22
        _p75_abs22 = float(_spec22.abs().quantile(0.75))
        _num_w22, _den_w22 = 0.0, 0.0
        for _k22, _d22 in enumerate(_v22_dates):
            _w22 = v22_lambda ** (_v22_n - 1 - _k22)
            _s22 = _v22_hm[(_v22_hm["delivery_date"] == _d22) & (_v22_hm["H"] == h)]["spread_f1_sdac"]
            if _s22.empty or pd.isna(_s22.iloc[0]):
                continue
            _num_w22 += _w22 * (1.0 if -float(_s22.iloc[0]) > 0 else 0.0)
            _den_w22 += _w22
        _prob_long_w22 = _num_w22 / _den_w22 if _den_w22 > 0 else 0.5
        _edge_w22 = (2 * _prob_long_w22 - 1) * _p75_abs22
        _v22_rows.append({
            "Hour": h, "ProbLongW": _prob_long_w22, "ProbShortW": 1.0 - _prob_long_w22,
            "ProbLongUW": _prob_long_uw22, "P75Spread": _p75_abs22, "Edge": _edge_w22, "N": _n22,
        })

    _v22_df = pd.DataFrame(_v22_rows)

    if _v22_df.empty:
        st.info("Not enough data to compute the Edge Score for this window.")
    else:
        st.subheader(f"Weighted probability by hour — last {v22_window} day(s), λ = {v22_lambda}")
        st.caption(
            "Weighted P(LONG) = probability of Buy F1 / Sell SDAC, with recent days having "
            "higher weight. At λ = 1.0 this equals the unweighted v2 result."
        )
        fig_v22p = go.Figure()
        fig_v22p.add_trace(go.Bar(
            x=_v22_df["Hour"], y=_v22_df["ProbLongW"] * 100,
            name="LONG (weighted)", marker_color="#2dc653",
            hovertemplate="<b>H%{x:02d}</b><br>Weighted P(LONG): %{y:.1f}%<extra></extra>",
        ))
        fig_v22p.add_trace(go.Bar(
            x=_v22_df["Hour"], y=_v22_df["ProbShortW"] * 100,
            name="SHORT (weighted)", marker_color="#e63946",
            hovertemplate="<b>H%{x:02d}</b><br>Weighted P(SHORT): %{y:.1f}%<extra></extra>",
        ))
        fig_v22p.update_layout(
            **CHART_THEME, barmode="stack",
            xaxis=dict(title="Hour", tickmode="linear", dtick=1, range=[0.5, 24.5],
                       gridcolor="#eee", linecolor="#ccc"),
            yaxis=dict(title="Weighted probability (%)", range=[0, 100],
                       gridcolor="#eee", linecolor="#ccc"),
            height=260, margin=dict(t=20, b=40),
            legend=dict(orientation="h", y=1.15, x=0),
        )
        st.plotly_chart(fig_v22p, use_container_width=True)

        st.subheader("Edge Score with Decay — by hour")
        _v22_edge_colors = [
            "#2dc653" if e > 0 else ("#e63946" if e < 0 else "#cccccc")
            for e in _v22_df["Edge"]
        ]
        fig_v22e = go.Figure()
        fig_v22e.add_hline(y=0, line_color="#aaa", line_width=1)
        fig_v22e.add_trace(go.Bar(
            x=_v22_df["Hour"], y=_v22_df["Edge"],
            marker_color=_v22_edge_colors,
            customdata=list(zip(
                _v22_df["ProbLongW"] * 100, _v22_df["ProbLongUW"] * 100,
                _v22_df["P75Spread"], _v22_df["Edge"],
            )),
            hovertemplate=(
                "<b>H%{x:02d}</b><br>"
                f"Lookback: {v22_window}d · λ = {v22_lambda}<br>"
                "Weighted P(LONG):   %{customdata[0]:.1f}%<br>"
                "Unweighted P(LONG): %{customdata[1]:.1f}%<br>"
                "P75 |Spread|: %{customdata[2]:.1f} PLN/MWh<br>"
                "Edge Score: %{customdata[3]:.1f}<extra></extra>"
            ),
            text=[f"{e:.1f}" for e in _v22_df["Edge"]],
            textposition="outside",
            textfont=dict(size=10),
        ))
        fig_v22e.update_layout(
            **CHART_THEME,
            xaxis=dict(title="Hour", tickmode="linear", dtick=1, range=[0.5, 24.5],
                       gridcolor="#eee", linecolor="#ccc"),
            yaxis=dict(title="Edge Score (decay-weighted)", gridcolor="#eee", linecolor="#ccc"),
            height=300, margin=dict(t=30, b=40),
            showlegend=False,
        )
        st.plotly_chart(fig_v22e, use_container_width=True)

        st.subheader("Trading ranking")
        st.caption("Sorted by |Edge Score|, descending — hours with the strongest decay-weighted edge appear first.")

        def _signal_strength_v22(abs_edge):
            if abs_edge < 7:   return "No edge / No trade"
            if abs_edge < 18:  return "Moderate signal"
            if abs_edge < 25:  return "Strong signal"
            return "Exceptional signal"

        _rank22 = _v22_df.copy()
        _rank22["Direction"] = _rank22["Edge"].apply(
            lambda e: "LONG" if e > 0 else ("SHORT" if e < 0 else "—"))
        _rank22["AbsEdge"] = _rank22["Edge"].abs()
        _rank22["Signal Strength"] = _rank22["AbsEdge"].apply(_signal_strength_v22)
        _rank22 = _rank22.sort_values("AbsEdge", ascending=False)

        _rank22_disp = pd.DataFrame({
            "Hour":               _rank22["Hour"],
            "Direction":          _rank22["Direction"],
            "Weighted P(LONG)":   (_rank22["ProbLongW"] * 100).round(1).astype(str) + "%",
            "Unweighted P(LONG)": (_rank22["ProbLongUW"] * 100).round(0).astype(int).astype(str) + "%",
            "P75 |Spread|":       _rank22["P75Spread"].round(1),
            "Edge Score":         _rank22["Edge"].round(1),
            "Signal Strength":    _rank22["Signal Strength"],
        })

        def _color_dir22(val):
            if val == "LONG":  return "background-color:#c8f7c5;color:#155724"
            if val == "SHORT": return "background-color:#fcd5d5;color:#7b0000"
            return ""

        st.dataframe(
            _rank22_disp.style.applymap(_color_dir22, subset=["Direction"]),
            use_container_width=True, hide_index=True, height=400,
        )

    # ════════════════════════════════════════════════════════════════════════
    # Suggested next projects
    # ════════════════════════════════════════════════════════════════════════
    st.divider()
    with st.expander("💡 Suggested next projects"):
        st.markdown("""
**Edge Calibration**

Verify whether the Edge Score is actually a reliable predictor of profitability.
The idea: go through all historical (day, hour) pairs, compute the Edge Score signal *before* that
day (using only data up to D−1), then compare the signal direction with what actually happened on
day D.

For each Edge bucket (0–7 / 7–18 / 18–25 / 25+) calculate:
- **Hit Ratio** — how often the signal direction was correct
- **Avg PnL** — average profit per trade (1 MW × actual spread, PLN/MWh)
- **Median PnL** — median profit (more robust to outliers)
- **Total PnL** — cumulative profit across all observations

This answers the fundamental question: *"Does a higher Edge Score actually mean a better trade?"*
If yes — the model is well calibrated. If not — the signal strength thresholds need revision.

---

**Edge Trend**

Compare the Edge Score computed over a short window (e.g. last 3 days) with the Edge Score from a
longer window (e.g. last 7 days), for each hour side by side.

- If Edge_3d > Edge_7d → the signal is **strengthening** (recent market behaviour is more aligned)
- If Edge_3d < Edge_7d → the signal is **weakening** (recent days diverge from the longer pattern)

Useful for deciding whether to act on today's signal or wait for confirmation.
        """)


def render_tso_heatmap():
    prices = load_prices()
    tso_trades = load_tso_trades()
    st.markdown("""
    <div style="
        position: sticky;
        top: 0;
        z-index: 999;
        background: white;
        padding: 10px 0 12px 0;
        border-bottom: 1px solid #e0e0e0;
        margin-bottom: 12px;
    ">
        <div style="display:flex; align-items:center; gap:16px;">
            <h1 style="margin:0; font-size:2rem; flex:2; white-space:nowrap;">
                TSOHeatmap — SDAC vs CEN
            </h1>
            <div style="flex:1; background:#e63946; padding:8px 14px; border-radius:6px;
                        text-align:center; color:#fff; font-weight:600;">
                &#9632; SDAC &gt; CEN — Short SDAC
            </div>
            <div style="flex:1; background:#2dc653; padding:8px 14px; border-radius:6px;
                        text-align:center; color:#000; font-weight:600;">
                &#9632; SDAC &lt; CEN — Long SDAC
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Build heatmap DataFrame from FixingPricesH (SDAC) + RB_prices_H (CEN) ──
    fix_all = load_prices()
    rb_h_df = load_rb_h_cached()

    if fix_all.empty or rb_h_df.empty:
        st.info("No data available.")
        st.stop()

    sdac_h = fix_all[["delivery_date", "H", "sdac_price_PLN"]].dropna(subset=["sdac_price_PLN"])
    cen_h  = rb_h_df[["delivery_date", "H", "cen_cost"]].dropna(subset=["cen_cost"])

    hm_tso = sdac_h.merge(cen_h, on=["delivery_date", "H"], how="inner")
    hm_tso = hm_tso.rename(columns={"sdac_price_PLN": "sdac", "cen_cost": "cen"})
    hm_tso["spread"] = hm_tso["sdac"] - hm_tso["cen"]

    # ── Staleness indicator ───────────────────────────────────────────────────
    _last_tso = hm_tso["delivery_date"].max()
    _tso_days_old = (date.today() - _last_tso).days
    _tso_color = "#2dc653" if _tso_days_old == 0 else ("#e65100" if _tso_days_old == 1 else "#e63946")
    _tso_label = (
        "up to date" if _tso_days_old == 0
        else f"{_tso_days_old} day(s) behind"
    )

    ctrl1, ctrl1b, ctrl2, ctrl3 = st.columns([1, 0.7, 1, 2])
    with ctrl1:
        tso_n_days = st.selectbox("Show last N days", [7, 14, 30, 60, 90, 999], index=0,
                                  format_func=lambda x: "All" if x == 999 else f"{x} days",
                                  key="tso_hm_ndays")
    with ctrl1b:
        st.markdown("<br>", unsafe_allow_html=True)
        tso_show_spread = st.checkbox("Spread", value=False, key="tso_hm_spread")
    with ctrl2:
        st.markdown(
            f"<div style='padding-top:8px;font-size:0.9rem;'>"
            f"Last delivery: <b>{_last_tso}</b><br>"
            f"<span style='color:{_tso_color};font-weight:600;'>{_tso_label}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
    with ctrl3:
        if st.button("Update CEN", key="tso_hm_update"):
            import importlib.util as _ilu
            _root = APP_DIR
            _spec = _ilu.spec_from_file_location(
                "rb_prices", os.path.join(_root, "procedures", "rb_prices.py"))
            _mod = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            _lines = []
            with st.spinner("Downloading CEN forecast..."):
                _result = _mod.fast_load(log=lambda m: _lines.append(m))
            load_rb_h_cached.clear()
            if _result["status"] == "ok":
                st.success(_result["message"])
            else:
                st.error(_result["message"])
            with st.expander("Pipeline log"):
                st.text("\n".join(_lines))
            st.rerun()

    # ── Filter by window ──────────────────────────────────────────────────────
    all_tso_deliv = sorted(hm_tso["delivery_date"].unique())
    if tso_n_days != 999:
        all_tso_deliv = all_tso_deliv[-tso_n_days:]
    hm_tso = hm_tso[hm_tso["delivery_date"].isin(all_tso_deliv)]

    hours = list(range(1, 25))
    tso_dates = sorted(hm_tso["delivery_date"].unique())
    tz_color, tz_spread = [], []

    for d in tso_dates:
        row_c, row_s = [], []
        for h in hours:
            cell = hm_tso[(hm_tso["delivery_date"] == d) & (hm_tso["H"] == h)]
            if cell.empty or pd.isna(cell.iloc[0]["spread"]):
                row_c.append(0); row_s.append(None)
            else:
                s = cell.iloc[0]["spread"]
                row_c.append(1 if s > 0 else (-1 if s < 0 else 0))
                row_s.append(round(s, 2))
        tz_color.append(row_c); tz_spread.append(row_s)

    tso_date_labels = [d.strftime("%d.%m") for d in tso_dates]
    _cell = 38
    _lm, _rm, _tm, _bm = 75, 20, 30, 60
    _fig_w = len(hours) * _cell + _lm + _rm
    _fig_h = len(tso_dates) * _cell + _tm + _bm
    fig_tso = go.Figure(go.Heatmap(
        z=tz_color, x=hours, y=tso_date_labels,
        customdata=tz_spread,
        colorscale=[[0.0,"#2dc653"],[0.5,"#cccccc"],[1.0,"#e63946"]],
        zmin=-1, zmax=1, showscale=False,
        hovertemplate="<b>%{y}  H%{x:02d}</b><br>Spread SDAC-CEN: %{customdata:.2f} PLN/MWh<extra></extra>",
        xgap=2, ygap=2,
    ))
    fig_tso.update_layout(
        **CHART_THEME,
        xaxis=dict(title="Hour", tickmode="linear", dtick=1, side="bottom"),
        yaxis=dict(title="", type="category", autorange="reversed",
                   tickfont=dict(size=12, family="monospace")),
        width=_fig_w, height=_fig_h,
        margin=dict(t=_tm, b=_bm, l=_lm, r=_rm),
    )
    if tso_show_spread:
        _xb, _yb, _tb = [], [], []
        _xw, _yw, _tw = [], [], []
        for i, dl in enumerate(tso_date_labels):
            for j, h in enumerate(hours):
                s = tz_spread[i][j]
                if s is not None:
                    if tz_color[i][j] < 0:
                        _xw.append(h); _yw.append(dl); _tw.append(f"{s:.0f}")
                    elif tz_color[i][j] > 0:
                        _xb.append(h); _yb.append(dl); _tb.append(f"{s:.0f}")
        if _xb:
            fig_tso.add_trace(go.Scatter(x=_xb, y=_yb, text=_tb,
                mode="text", textfont=dict(size=11, color="black"),
                showlegend=False, hoverinfo="skip"))
        if _xw:
            fig_tso.add_trace(go.Scatter(x=_xw, y=_yw, text=_tw,
                mode="text", textfont=dict(size=11, color="white"),
                showlegend=False, hoverinfo="skip"))
    st.plotly_chart(fig_tso, use_container_width=False)

    # ── Probability of Long F2 per hour ──────────────────────────────────────
    st.divider()
    st.subheader(f"Signal probability — last {tso_n_days if tso_n_days != 999 else 'all'} day(s)")
    st.caption(
        "For each hour: probability of the **dominant** signal (whichever side — Long SDAC "
        "or Short SDAC — is more likely). Bar height = strength of that edge, so the tallest "
        "bars (green or red) mark the hours with the best odds. "
        "Green = Long SDAC (SDAC < CEN) dominant · Red = Short SDAC (SDAC > CEN) dominant · 50% = no edge."
    )

    tso_prob_long  = []
    tso_prob_short = []
    tso_total_h    = []
    for h in hours:
        col_h   = hm_tso[hm_tso["H"] == h]["spread"].dropna()
        n_total = len(col_h)
        n_long  = (col_h < 0).sum()
        n_short = (col_h > 0).sum()
        tso_prob_long.append( round(n_long  / n_total * 100, 1) if n_total else 0)
        tso_prob_short.append(round(n_short / n_total * 100, 1) if n_total else 0)
        tso_total_h.append(n_total)

    # Bar height = probability of the DOMINANT side (whichever is > 50%),
    # so a tall red bar means a strong/likely Short SDAC signal — not a weak Long SDAC one.
    tso_dom_prob = []
    tso_dom_side = []
    _bar_colors_tso = []
    for b, s in zip(tso_prob_long, tso_prob_short):
        if b > 50:
            tso_dom_prob.append(b); tso_dom_side.append("Long SDAC");  _bar_colors_tso.append("#2dc653")
        elif s > 50:
            tso_dom_prob.append(s); tso_dom_side.append("Short SDAC"); _bar_colors_tso.append("#e63946")
        else:
            tso_dom_prob.append(b); tso_dom_side.append("No edge");    _bar_colors_tso.append("#cccccc")

    fig_tso_prob = go.Figure()
    fig_tso_prob.add_hline(y=50, line_dash="dash", line_color="#aaa", line_width=1)
    fig_tso_prob.add_trace(go.Bar(
        x=hours,
        y=tso_dom_prob,
        marker_color=_bar_colors_tso,
        customdata=list(zip(tso_dom_side, tso_prob_long, tso_prob_short, tso_total_h)),
        hovertemplate=(
            "<b>H%{x:02d}</b><br>"
            "Dominant: %{customdata[0]} — %{y:.1f}%<br>"
            "Long SDAC:  %{customdata[1]:.1f}%<br>"
            "Short SDAC: %{customdata[2]:.1f}%<br>"
            "Days: %{customdata[3]}<extra></extra>"
        ),
        text=[f"{v:.0f}%" for v in tso_dom_prob],
        textposition="outside",
        textfont=dict(size=10),
    ))
    fig_tso_prob.update_layout(
        **CHART_THEME,
        xaxis=dict(title="Hour", tickmode="linear", dtick=1,
                   range=[0.5, 24.5], gridcolor="#eee", linecolor="#ccc"),
        yaxis=dict(title="Dominant signal probability (%)", range=[0, 115],
                   gridcolor="#eee", linecolor="#ccc",
                   tickvals=[0, 25, 50, 75, 100],
                   ticktext=["0%", "25%", "50%", "75%", "100%"]),
        height=280, margin=dict(t=20, b=40),
        showlegend=False,
    )
    st.plotly_chart(fig_tso_prob, use_container_width=True)

    # ── Signal with weights ───────────────────────────────────────────────────
    st.divider()
    st.subheader("Signal — with weights")

    _tso_lam_col, _ = st.columns([1, 3])
    with _tso_lam_col:
        tso_lam = st.slider("Decay factor λ", min_value=0.50, max_value=1.00,
                            value=0.80, step=0.05, key="tso_hm_lam",
                            help="1.0 = all days equal  ·  lower = recent days dominate")

    _tso_n_used = len(tso_dates)
    if tso_lam < 1.0 and _tso_n_used > 1:
        _tso_ratio = round(1 / tso_lam ** (_tso_n_used - 1), 1)
        st.caption(f"Yesterday weighs **{_tso_ratio}×** more than the oldest day in the window "
                   f"({_tso_n_used} days, λ = {tso_lam})")
    else:
        st.caption(f"λ = 1.0 — all {_tso_n_used} days carry equal weight (same as chart above)")

    _tso_dates_ord = sorted(tso_dates)
    w_prob_long_tso  = []
    w_prob_short_tso = []
    for h in hours:
        _num, _den = 0.0, 0.0
        for _k, _d in enumerate(_tso_dates_ord):
            _w = tso_lam ** (_tso_n_used - 1 - _k)
            _c = hm_tso[(hm_tso["delivery_date"] == _d) & (hm_tso["H"] == h)]["spread"]
            if _c.empty or pd.isna(_c.iloc[0]):
                continue
            _num += _w * (1.0 if _c.iloc[0] < 0 else 0.0)
            _den += _w
        _p_long = round(_num / _den * 100, 1) if _den > 0 else 0.0
        w_prob_long_tso.append(_p_long)
        w_prob_short_tso.append(round(100 - _p_long, 1) if _den > 0 else 0.0)

    # Bar height = weighted probability of the DOMINANT side, same logic as the
    # unweighted chart above — a tall red bar means a strong/likely Short SDAC signal.
    w_dom_prob_tso = []
    w_dom_side_tso = []
    _bar_colors_tw = []
    for b, s in zip(w_prob_long_tso, w_prob_short_tso):
        if b > 50:
            w_dom_prob_tso.append(b); w_dom_side_tso.append("Long SDAC");  _bar_colors_tw.append("#2dc653")
        elif s > 50:
            w_dom_prob_tso.append(s); w_dom_side_tso.append("Short SDAC"); _bar_colors_tw.append("#e63946")
        else:
            w_dom_prob_tso.append(b); w_dom_side_tso.append("No edge");    _bar_colors_tw.append("#cccccc")

    fig_tw = go.Figure()
    fig_tw.add_hline(y=50, line_dash="dash", line_color="#aaa", line_width=1)
    fig_tw.add_trace(go.Bar(
        x=hours, y=tso_dom_prob,
        marker_color="rgba(180,180,180,0.35)",
        name="Unweighted (ref)",
        hoverinfo="skip",
    ))
    fig_tw.add_trace(go.Bar(
        x=hours, y=w_dom_prob_tso,
        marker_color=_bar_colors_tw,
        name="Weighted",
        customdata=list(zip(w_dom_side_tso, w_prob_long_tso, w_prob_short_tso)),
        hovertemplate=(
            "<b>H%{x:02d}</b><br>"
            "Dominant: %{customdata[0]} — %{y:.1f}%<br>"
            "Long SDAC:  %{customdata[1]:.1f}%<br>"
            "Short SDAC: %{customdata[2]:.1f}%<extra></extra>"
        ),
        text=[f"{v:.0f}%" for v in w_dom_prob_tso],
        textposition="outside",
        textfont=dict(size=10),
    ))
    fig_tw.update_layout(
        **CHART_THEME,
        barmode="overlay",
        xaxis=dict(title="Hour", tickmode="linear", dtick=1,
                   range=[0.5, 24.5], gridcolor="#eee", linecolor="#ccc"),
        yaxis=dict(title="Weighted dominant signal probability (%)", range=[0, 115],
                   gridcolor="#eee", linecolor="#ccc",
                   tickvals=[0, 25, 50, 75, 100],
                   ticktext=["0%", "25%", "50%", "75%", "100%"]),
        height=280, margin=dict(t=20, b=40),
        legend=dict(orientation="h", y=1.12, x=0),
    )
    st.plotly_chart(fig_tw, use_container_width=True)

    st.markdown(f"""
    **How it is calculated**

    For each hour H01–H24, the algorithm looks at all **{_tso_n_used} days** in the selected window and
    asks: was SDAC < CEN on that day (Long SDAC signal)?

    Each day receives an exponential weight:

    > weight = λ^(N − 1 − k)

    where **k = 0** is the oldest day and **k = N − 1** is yesterday (most recent).
    At λ = {tso_lam}, yesterday's weight is **{round(tso_lam**0, 2)}** and the oldest day's weight is
    **{round(tso_lam**(_tso_n_used-1), 3)}**.

    The weighted probability is then:

    > P(Long SDAC) = Σ(weight × is_long) / Σ(weight)

    The bar shows the **dominant** side's probability — whichever of Long SDAC or Short SDAC
    is above 50% — with recent days counted more heavily. So a tall green bar means a strong,
    likely Long SDAC edge, and a tall red bar means an equally strong, likely Short SDAC edge:
    bar height always reflects how strong the edge is, not which direction it points.
    The faint grey bars show the unweighted result (same logic) for comparison.
    """)

    # ════════════════════════════════════════════════════════════════════════
    # TSOHeatmap v2 — Edge Score module
    # ════════════════════════════════════════════════════════════════════════
    st.divider()
    st.markdown("## TSOHeatmap v2 — Edge Score")
    st.caption(
        "Combines directional probability and spread magnitude into a single score per hour, "
        "to highlight the hours with the most statistically and economically meaningful edge "
        "between SDAC and CEN."
    )

    with st.expander("ℹ️ How the Edge Score is calculated"):
        st.markdown(r"""
**Edge Score** combines two things into one number, for each hour (H01–H24):

1. **Directional probability** — `ProbabilityLONG`: the share of days in the selected window
   where the spread (CEN − SDAC) was positive, i.e. SDAC traded *below* CEN
   (a **LONG SDAC / Short CEN** day). `ProbabilitySHORT = 1 − ProbabilityLONG`.
2. **Spread magnitude** — `P75(|Spread|)`: the 75ᵗʰ percentile of the *absolute* spread within
   the window. P75 captures economically meaningful moves while staying robust to one-off
   outliers — better than the median (too conservative) and less noisy than the max.

> **Edge = (2 × ProbabilityLONG − 1) × P75(|Spread|)**

- **Edge > 0** → **LONG bias** (Long SDAC / Short CEN tends to win in that hour)
- **Edge < 0** → **SHORT bias** (Short SDAC / Long CEN tends to win in that hour)
- The further from zero, the stronger **and** more consistent the historical edge —
  a hand-picked combination of "how often" and "how much".

**Signal strength legend** (based on |Edge|, calibrated on ~6 months of history):

| \|Edge\| | Signal |
|---|---|
| < 3 | No edge / No trade |
| 3 – 7 | Weak signal |
| 7 – 12 | Moderate signal |
| 12 – 18 | Strong signal |
| 18 – 25 | Very strong signal |
| ≥ 25 | Exceptional signal |

*Current version uses historical SDAC vs CEN statistics only — a future version will combine
this Edge Score with forecast-model accuracy and PnL performance (XGBoost, Random Forest,
SARIMAX, ARIMA).*
        """)

    _tv2_col, _ = st.columns([1, 3])
    with _tv2_col:
        tv2_window = st.selectbox("Rolling window", [3, 5, 7, 14, 30], index=3,
                                  format_func=lambda x: f"{x} days", key="tso_v2_window")

    # Independent rolling window: most recent N delivery days with valid SDAC/CEN spread data
    _tv2_all_dates = sorted(hm_tso["delivery_date"].unique())
    _tv2_dates = _tv2_all_dates[-tv2_window:]
    _tv2_hm = hm_tso[hm_tso["delivery_date"].isin(_tv2_dates)].dropna(subset=["spread"])

    if len(_tv2_dates) < tv2_window:
        st.caption(f"⚠️ Only {len(_tv2_dates)} day(s) with data available for this window.")

    _tv2_rows = []
    for h in hours:
        _col = _tv2_hm[_tv2_hm["H"] == h]
        # Spec convention: Spread = CEN − SDAC  ==  −(sdac − cen) == −spread (existing column)
        _spec_spread = -_col["spread"]
        _n_total = len(_spec_spread)
        if _n_total == 0:
            continue
        _prob_long  = float((_spec_spread > 0).sum()) / _n_total
        _prob_short = 1.0 - _prob_long
        _p75_abs    = float(_spec_spread.abs().quantile(0.75))
        _edge       = (2 * _prob_long - 1) * _p75_abs
        _tv2_rows.append({
            "Hour": h, "ProbLong": _prob_long, "ProbShort": _prob_short,
            "P75Spread": _p75_abs, "Edge": _edge, "N": _n_total,
        })

    _tv2_df = pd.DataFrame(_tv2_rows)

    if _tv2_df.empty:
        st.info("Not enough data to compute the Edge Score for this window.")
    else:
        # ── Probability chart (LONG vs SHORT, stacked to 100%) ───────────────
        st.subheader(f"Probability by hour — last {tv2_window} day(s)")
        st.caption(
            "ProbabilityLONG = share of days with positive spread (CEN > SDAC → Long SDAC / Short CEN) · "
            "ProbabilitySHORT = 1 − ProbabilityLONG."
        )
        fig_tv2p = go.Figure()
        fig_tv2p.add_trace(go.Bar(
            x=_tv2_df["Hour"], y=_tv2_df["ProbLong"] * 100,
            name="LONG", marker_color="#2dc653",
            hovertemplate="<b>H%{x:02d}</b><br>P(LONG): %{y:.0f}%<extra></extra>",
        ))
        fig_tv2p.add_trace(go.Bar(
            x=_tv2_df["Hour"], y=_tv2_df["ProbShort"] * 100,
            name="SHORT", marker_color="#e63946",
            hovertemplate="<b>H%{x:02d}</b><br>P(SHORT): %{y:.0f}%<extra></extra>",
        ))
        fig_tv2p.update_layout(
            **CHART_THEME,
            barmode="stack",
            xaxis=dict(title="Hour", tickmode="linear", dtick=1, range=[0.5, 24.5],
                       gridcolor="#eee", linecolor="#ccc"),
            yaxis=dict(title="Probability (%)", range=[0, 100],
                       gridcolor="#eee", linecolor="#ccc"),
            height=260, margin=dict(t=20, b=40),
            legend=dict(orientation="h", y=1.15, x=0),
        )
        st.plotly_chart(fig_tv2p, use_container_width=True)

        # ── Edge Score chart ──────────────────────────────────────────────────
        st.subheader("Edge Score by hour")
        _tv2_edge_colors = [
            "#2dc653" if e > 0 else ("#e63946" if e < 0 else "#cccccc")
            for e in _tv2_df["Edge"]
        ]
        fig_tedge = go.Figure()
        fig_tedge.add_hline(y=0, line_color="#aaa", line_width=1)
        fig_tedge.add_trace(go.Bar(
            x=_tv2_df["Hour"], y=_tv2_df["Edge"],
            marker_color=_tv2_edge_colors,
            customdata=list(zip(_tv2_df["ProbLong"] * 100, _tv2_df["P75Spread"], _tv2_df["Edge"])),
            hovertemplate=(
                "<b>H%{x:02d}</b><br>"
                "ProbabilityLONG: %{customdata[0]:.0f}%<br>"
                "P75 |Spread|: %{customdata[1]:.1f} PLN<br>"
                "Edge Score: %{customdata[2]:.1f}<extra></extra>"
            ),
            text=[f"{e:.1f}" for e in _tv2_df["Edge"]],
            textposition="outside",
            textfont=dict(size=10),
        ))
        fig_tedge.update_layout(
            **CHART_THEME,
            xaxis=dict(title="Hour", tickmode="linear", dtick=1, range=[0.5, 24.5],
                       gridcolor="#eee", linecolor="#ccc"),
            yaxis=dict(title="Edge Score", gridcolor="#eee", linecolor="#ccc"),
            height=300, margin=dict(t=30, b=40),
            showlegend=False,
        )
        st.plotly_chart(fig_tedge, use_container_width=True)

        # ── Trading ranking table ─────────────────────────────────────────────
        st.subheader("Trading ranking")
        st.caption("Sorted by |Edge Score|, descending — the top rows are the hours with the strongest historical edge.")

        def _tso_signal_strength(abs_edge):
            if abs_edge < 3:   return "No edge / No trade"
            if abs_edge < 7:   return "Weak signal"
            if abs_edge < 12:  return "Moderate signal"
            if abs_edge < 18:  return "Strong signal"
            if abs_edge < 25:  return "Very strong signal"
            return "Exceptional signal"

        _trank = _tv2_df.copy()
        _trank["Direction"] = _trank["Edge"].apply(
            lambda e: "LONG" if e > 0 else ("SHORT" if e < 0 else "—"))
        _trank["AbsEdge"] = _trank["Edge"].abs()
        _trank["Signal Strength"] = _trank["AbsEdge"].apply(_tso_signal_strength)
        _trank = _trank.sort_values("AbsEdge", ascending=False)

        _trank_disp = pd.DataFrame({
            "Hour":            _trank["Hour"],
            "Direction":       _trank["Direction"],
            "ProbabilityLONG": (_trank["ProbLong"] * 100).round(0).astype(int).astype(str) + "%",
            "P75 |Spread|":    _trank["P75Spread"].round(1),
            "Edge Score":      _trank["Edge"].round(1),
            "Signal Strength": _trank["Signal Strength"],
        })

        def _tso_color_dir(val):
            if val == "LONG":  return "background-color:#c8f7c5;color:#155724"
            if val == "SHORT": return "background-color:#fcd5d5;color:#7b0000"
            return ""

        st.dataframe(
            _trank_disp.style.applymap(_tso_color_dir, subset=["Direction"]),
            use_container_width=True, hide_index=True, height=400,
        )

    # ════════════════════════════════════════════════════════════════════════
    # TSOHeatmap v2.2 — Edge Score with Decay
    # ════════════════════════════════════════════════════════════════════════
    st.divider()
    st.markdown("## TSOHeatmap v2.2 — Edge Score with Decay")
    st.caption(
        "An enhanced version of the TSO Edge Score that gives more weight to recent observations. "
        "Recent days matter more than distant ones — this module captures that by applying "
        "exponential decay to the probability calculation."
    )

    with st.expander("ℹ️ How the Edge Score with Decay is calculated"):
        st.markdown(r"""
**Edge Score with Decay** is an enhancement of the basic Edge Score (v2). The key difference:
instead of treating all historical days equally, it assigns **exponentially larger weights to more
recent observations** — on the assumption that recent market behaviour is more relevant than what
happened two weeks ago.

**Step 1 — Decay weights**

For each day in the lookback window, a weight is assigned:

> weight = λ^(N − 1 − k)

where:
- **N** = number of days in the lookback window
- **k** = day index (0 = oldest, N−1 = most recent)
- **λ** (Lambda) = decay parameter chosen by the user

The most recent day always receives weight **1.0**. Older days receive exponentially less weight.

Example at λ = 0.8, window = 5 days: weights are 0.41 → 0.51 → 0.64 → 0.80 → 1.00

At λ = 1.0 all days receive equal weight — identical to the unweighted v2.

**Step 2 — Weighted directional probability**

For each hour H01–H24:

> P_long_weighted = Σ(weight × is_long) / Σ(weight)

where `is_long = 1` if CEN > SDAC on that day (Long SDAC / Short CEN), 0 otherwise.

**Step 3 — Edge Score**

> weighted_direction = 2 × P_long_weighted − 1
> Edge = weighted_direction × P75(|Spread|)

*P75 of the absolute spread is unweighted — it captures the economic magnitude of the spread
over the full lookback window, independent of recency.*

**Comparison with v2:**

| | v2 (unweighted) | v2.2 (with decay) |
|---|---|---|
| Probability | Each day counts equally | Recent days count more |
| Spread magnitude | P75 of window | P75 of window (same) |
| Best for | Stable, slowly-changing patterns | Markets reacting to recent conditions |

Recommended settings: **Lookback = 5 days, Lambda = 0.8**

**Signal strength legend** (calibrated on ~6 months of historical data):

| \|Edge\| | Signal |
|---|---|
| 0 – 7 | No edge / No trade |
| 7 – 18 | Moderate signal |
| 18 – 25 | Strong signal |
| ≥ 25 | Exceptional signal |
        """)

    _tv22_c1, _tv22_c2, _ = st.columns([1, 1, 2])
    with _tv22_c1:
        tv22_window = st.selectbox("Lookback window", [3, 5, 7, 14, 30], index=1,
                                   format_func=lambda x: f"{x} days", key="tso_v22_window")
    with _tv22_c2:
        tv22_lambda = st.selectbox("Lambda (λ)", [0.6, 0.7, 0.8, 0.9, 1.0], index=2,
                                   key="tso_v22_lambda")

    _tv22_all_dates = sorted(hm_tso["delivery_date"].unique())
    _tv22_dates = sorted(_tv22_all_dates[-tv22_window:])
    _tv22_hm = hm_tso[hm_tso["delivery_date"].isin(_tv22_dates)].dropna(subset=["spread"])

    if len(_tv22_dates) < tv22_window:
        st.caption(f"⚠️ Only {len(_tv22_dates)} day(s) with data available for this window.")

    _tv22_n = len(_tv22_dates)
    _tv22_rows = []
    for h in hours:
        _col_tv22 = _tv22_hm[_tv22_hm["H"] == h]
        _spec_tv22 = -_col_tv22["spread"]  # CEN − SDAC; positive = Long SDAC
        _n_tv22 = len(_spec_tv22)
        if _n_tv22 == 0:
            continue
        _prob_long_uw_tv22 = float((_spec_tv22 > 0).sum()) / _n_tv22
        _p75_abs_tv22 = float(_spec_tv22.abs().quantile(0.75))
        _num_wt, _den_wt = 0.0, 0.0
        for _kt, _dt in enumerate(_tv22_dates):
            _wt = tv22_lambda ** (_tv22_n - 1 - _kt)
            _st = _tv22_hm[(_tv22_hm["delivery_date"] == _dt) & (_tv22_hm["H"] == h)]["spread"]
            if _st.empty or pd.isna(_st.iloc[0]):
                continue
            _num_wt += _wt * (1.0 if -float(_st.iloc[0]) > 0 else 0.0)
            _den_wt += _wt
        _prob_long_w_tv22 = _num_wt / _den_wt if _den_wt > 0 else 0.5
        _edge_tv22 = (2 * _prob_long_w_tv22 - 1) * _p75_abs_tv22
        _tv22_rows.append({
            "Hour": h, "ProbLongW": _prob_long_w_tv22, "ProbShortW": 1.0 - _prob_long_w_tv22,
            "ProbLongUW": _prob_long_uw_tv22, "P75Spread": _p75_abs_tv22,
            "Edge": _edge_tv22, "N": _n_tv22,
        })

    _tv22_df = pd.DataFrame(_tv22_rows)

    if _tv22_df.empty:
        st.info("Not enough data to compute the Edge Score for this window.")
    else:
        st.subheader(f"Weighted probability by hour — last {tv22_window} day(s), λ = {tv22_lambda}")
        st.caption(
            "Weighted P(LONG) = probability of Long SDAC / Short CEN, with recent days having "
            "higher weight. At λ = 1.0 this equals the unweighted v2 result."
        )
        fig_tv22p = go.Figure()
        fig_tv22p.add_trace(go.Bar(
            x=_tv22_df["Hour"], y=_tv22_df["ProbLongW"] * 100,
            name="LONG (weighted)", marker_color="#2dc653",
            hovertemplate="<b>H%{x:02d}</b><br>Weighted P(LONG): %{y:.1f}%<extra></extra>",
        ))
        fig_tv22p.add_trace(go.Bar(
            x=_tv22_df["Hour"], y=_tv22_df["ProbShortW"] * 100,
            name="SHORT (weighted)", marker_color="#e63946",
            hovertemplate="<b>H%{x:02d}</b><br>Weighted P(SHORT): %{y:.1f}%<extra></extra>",
        ))
        fig_tv22p.update_layout(
            **CHART_THEME, barmode="stack",
            xaxis=dict(title="Hour", tickmode="linear", dtick=1, range=[0.5, 24.5],
                       gridcolor="#eee", linecolor="#ccc"),
            yaxis=dict(title="Weighted probability (%)", range=[0, 100],
                       gridcolor="#eee", linecolor="#ccc"),
            height=260, margin=dict(t=20, b=40),
            legend=dict(orientation="h", y=1.15, x=0),
        )
        st.plotly_chart(fig_tv22p, use_container_width=True)

        st.subheader("Edge Score with Decay — by hour")
        _tv22_edge_colors = [
            "#2dc653" if e > 0 else ("#e63946" if e < 0 else "#cccccc")
            for e in _tv22_df["Edge"]
        ]
        fig_tv22e = go.Figure()
        fig_tv22e.add_hline(y=0, line_color="#aaa", line_width=1)
        fig_tv22e.add_trace(go.Bar(
            x=_tv22_df["Hour"], y=_tv22_df["Edge"],
            marker_color=_tv22_edge_colors,
            customdata=list(zip(
                _tv22_df["ProbLongW"] * 100, _tv22_df["ProbLongUW"] * 100,
                _tv22_df["P75Spread"], _tv22_df["Edge"],
            )),
            hovertemplate=(
                "<b>H%{x:02d}</b><br>"
                f"Lookback: {tv22_window}d · λ = {tv22_lambda}<br>"
                "Weighted P(LONG):   %{customdata[0]:.1f}%<br>"
                "Unweighted P(LONG): %{customdata[1]:.1f}%<br>"
                "P75 |Spread|: %{customdata[2]:.1f} PLN/MWh<br>"
                "Edge Score: %{customdata[3]:.1f}<extra></extra>"
            ),
            text=[f"{e:.1f}" for e in _tv22_df["Edge"]],
            textposition="outside",
            textfont=dict(size=10),
        ))
        fig_tv22e.update_layout(
            **CHART_THEME,
            xaxis=dict(title="Hour", tickmode="linear", dtick=1, range=[0.5, 24.5],
                       gridcolor="#eee", linecolor="#ccc"),
            yaxis=dict(title="Edge Score (decay-weighted)", gridcolor="#eee", linecolor="#ccc"),
            height=300, margin=dict(t=30, b=40),
            showlegend=False,
        )
        st.plotly_chart(fig_tv22e, use_container_width=True)

        st.subheader("Trading ranking")
        st.caption("Sorted by |Edge Score|, descending — hours with the strongest decay-weighted edge appear first.")

        def _tso_signal_strength_v22(abs_edge):
            if abs_edge < 7:   return "No edge / No trade"
            if abs_edge < 18:  return "Moderate signal"
            if abs_edge < 25:  return "Strong signal"
            return "Exceptional signal"

        _trank22 = _tv22_df.copy()
        _trank22["Direction"] = _trank22["Edge"].apply(
            lambda e: "LONG" if e > 0 else ("SHORT" if e < 0 else "—"))
        _trank22["AbsEdge"] = _trank22["Edge"].abs()
        _trank22["Signal Strength"] = _trank22["AbsEdge"].apply(_tso_signal_strength_v22)
        _trank22 = _trank22.sort_values("AbsEdge", ascending=False)

        _trank22_disp = pd.DataFrame({
            "Hour":               _trank22["Hour"],
            "Direction":          _trank22["Direction"],
            "Weighted P(LONG)":   (_trank22["ProbLongW"] * 100).round(1).astype(str) + "%",
            "Unweighted P(LONG)": (_trank22["ProbLongUW"] * 100).round(0).astype(int).astype(str) + "%",
            "P75 |Spread|":       _trank22["P75Spread"].round(1),
            "Edge Score":         _trank22["Edge"].round(1),
            "Signal Strength":    _trank22["Signal Strength"],
        })

        def _tso_color_dir22(val):
            if val == "LONG":  return "background-color:#c8f7c5;color:#155724"
            if val == "SHORT": return "background-color:#fcd5d5;color:#7b0000"
            return ""

        st.dataframe(
            _trank22_disp.style.applymap(_tso_color_dir22, subset=["Direction"]),
            use_container_width=True, hide_index=True, height=400,
        )

    # ════════════════════════════════════════════════════════════════════════
    # Suggested next projects
    # ════════════════════════════════════════════════════════════════════════
    st.divider()
    with st.expander("💡 Suggested next projects"):
        st.markdown("""
**Edge Calibration**

Verify whether the Edge Score is actually a reliable predictor of profitability.
The idea: go through all historical (day, hour) pairs, compute the Edge Score signal *before* that
day (using only data up to D−1), then compare the signal direction with what actually happened on
day D.

For each Edge bucket (0–7 / 7–18 / 18–25 / 25+) calculate:
- **Hit Ratio** — how often the signal direction was correct
- **Avg PnL** — average profit per trade (1 MW × actual spread, PLN/MWh)
- **Median PnL** — median profit (more robust to outliers)
- **Total PnL** — cumulative profit across all observations

This answers the fundamental question: *"Does a higher Edge Score actually mean a better trade?"*
If yes — the model is well calibrated. If not — the signal strength thresholds need revision.

---

**Edge Trend**

Compare the Edge Score computed over a short window (e.g. last 3 days) with the Edge Score from a
longer window (e.g. last 7 days), for each hour side by side.

- If Edge_3d > Edge_7d → the signal is **strengthening** (recent market behaviour is more aligned)
- If Edge_3d < Edge_7d → the signal is **weakening** (recent days diverge from the longer pattern)

Useful for deciding whether to act on today's signal or wait for confirmation.
        """)


