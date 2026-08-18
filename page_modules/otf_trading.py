# page_modules/otf_trading.py
# OTF weekly BASE product trading — blotter + mark-to-market

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import os, json, re, datetime
from shared import APP_DIR, CHART_THEME, load_prices, load_otf_ee

OTF_TRADES_PATH = os.path.join(APP_DIR, "otf_trades.json")

# ── I/O ───────────────────────────────────────────────────────────────────────

def _load_otf() -> list:
    if not os.path.exists(OTF_TRADES_PATH):
        return []
    with open(OTF_TRADES_PATH, "r", encoding="utf-8") as _f:
        return json.load(_f)

def _save_otf(trades: list):
    with open(OTF_TRADES_PATH, "w", encoding="utf-8") as _f:
        json.dump(trades, _f, indent=2, default=str)

# ── Product helpers ───────────────────────────────────────────────────────────

def _parse_product(code: str):
    """
    Parse product code → (delivery_start, delivery_end, hours).
    BASE_W-27-26 → Monday/Sunday of ISO week 27 2026, 168 h.
    Extensible: add BASE_M / BASE_Q patterns here in future.
    Returns (None, None, None) on failure.
    """
    code = code.strip().upper()
    _m = re.match(r"BASE_W-(\d{1,2})-(\d{2})$", code)
    if _m:
        _week = int(_m.group(1))
        _year = 2000 + int(_m.group(2))
        try:
            _ds = datetime.date.fromisocalendar(_year, _week, 1)  # Monday
            _de = datetime.date.fromisocalendar(_year, _week, 7)  # Sunday
            return _ds, _de, 168
        except ValueError:
            pass
    return None, None, None

def _make_id() -> str:
    return f"OTF-{datetime.datetime.now().strftime('%Y%m%d%H%M%S%f')[:17]}"

# ── Synthetic price ───────────────────────────────────────────────────────────

def _calc_synthetic(trade: dict, f1_df: pd.DataFrame, today: datetime.date):
    """
    Returns (synthetic_price, realized_hours, remaining_hours).

    Phase 1 – before delivery:  synthetic = trade_price  → MtM = 0
    Phase 2 – during delivery:  synthetic = (Σ F1_realized + trade_price × remaining) / total
    Phase 3 – after delivery:   synthetic = Avg F1 over all delivery hours

    'Realized hours' = rows present in FixingPricesH for delivery_date within product window.
    F1 for delivery date D is published on D-1, so data for the entire delivery period
    (up to and including today) is available as soon as fixing occurs.
    """
    _ds   = datetime.date.fromisoformat(trade["delivery_start"])
    _de   = datetime.date.fromisoformat(trade["delivery_end"])
    _tot  = trade["hours"]   # 168 for BASE_W
    _tp   = trade["trade_price"]

    if today < _ds:
        return _tp, 0, _tot

    if f1_df.empty or "f1_price_PLN" not in f1_df.columns:
        return _tp, 0, _tot

    _mask     = (f1_df["delivery_date"] >= _ds) & (f1_df["delivery_date"] <= _de)
    _realized = f1_df[_mask].dropna(subset=["f1_price_PLN"])
    _real_h   = len(_realized)

    if _real_h == 0:
        return _tp, 0, _tot

    _real_val = float(_realized["f1_price_PLN"].sum())
    _rem_h    = max(_tot - _real_h, 0)
    _rem_val  = _tp * _rem_h
    _synth    = round((_real_val + _rem_val) / _tot, 2)

    return _synth, _real_h, _rem_h

# ── Product list from OTF/EE parquet ─────────────────────────────────────────

def _build_product_opts(today: datetime.date) -> list:
    """
    Return list of (product_code, delivery_start, delivery_end, hours, last_dkr_or_None)
    for weekly BASE products with delivery_start > today, sorted by delivery_start.
    Sourced from tge_otf_ee.parquet.
    """
    _ee = load_otf_ee()
    if _ee.empty or "product_type" not in _ee.columns:
        return []
    _w = _ee[_ee["product_type"] == "W"].copy()
    if _w.empty:
        return []
    _w["_date"] = pd.to_datetime(_w["date"]).dt.date

    _opts = []
    for _pname in sorted(_w["product_name"].dropna().unique()):
        _ds, _de, _h = _parse_product(str(_pname))
        if _ds is None or _ds <= today:   # skip past and current week
            continue
        # last available DKR for this product
        _rows = _w[_w["product_name"] == _pname].dropna(subset=["dkr"])
        _last_dkr = None
        if not _rows.empty:
            _last_dkr = float(_rows.loc[_rows["_date"].idxmax(), "dkr"])
        _opts.append((_pname, _ds, _de, _h, _last_dkr))

    _opts.sort(key=lambda x: x[1])
    return _opts


# ── OTF Trades page ───────────────────────────────────────────────────────────

def render_otf_trades():
    st.title("OTF Trades")
    _trades = _load_otf()
    _today  = datetime.date.today()

    # ── New Trade ─────────────────────────────────────────────────────────────
    with st.expander("New Trade", expanded=not _trades):

        # Build product list from OTF/EE data
        _prod_opts = _build_product_opts(_today)

        if not _prod_opts:
            st.warning("No future weekly products found in OTF/EE data. Run the OTF EE pipeline first.")
        else:
            # Format: "BASE_W-27-26  │  29 Jun – 05 Jul  │  285.50 PLN"
            def _prod_label(i):
                _p, _ds, _de, _h, _lp = _prod_opts[i]
                _price_str = f"  │  last: {_lp:.2f} PLN" if _lp is not None else ""
                return f"{_p}  │  {_ds.strftime('%d %b')} – {_de.strftime('%d %b %Y')}{_price_str}"

            # Initialize default price from first product on first load
            if "otf_price" not in st.session_state:
                _init_lp = _prod_opts[0][4]
                st.session_state["otf_price"] = float(_init_lp) if _init_lp else 300.0

            _nc1, _nc2 = st.columns([1, 1])
            with _nc1:
                _tx_date = st.date_input("Transaction Date", value=_today, key="otf_tx_date")
            with _nc2:
                _pos = st.radio("Position", ["LONG", "SHORT"], horizontal=True, key="otf_pos")

            _sel_idx = st.selectbox(
                "Product",
                range(len(_prod_opts)),
                format_func=_prod_label,
                key="otf_prod_idx",
            )

            # Auto-update Trade Price when product selection changes
            _prev_idx = st.session_state.get("otf_prev_prod_idx")
            if _prev_idx is None:
                st.session_state["otf_prev_prod_idx"] = _sel_idx
            elif _prev_idx != _sel_idx:
                st.session_state["otf_prev_prod_idx"] = _sel_idx
                _new_lp = _prod_opts[_sel_idx][4]
                if _new_lp is not None:
                    st.session_state["otf_price"] = float(_new_lp)
                st.rerun()

            _pcode, _ds, _de, _h, _ = _prod_opts[_sel_idx]

            _nv1, _nv2, _ = st.columns([1, 1.5, 1])
            with _nv1:
                _mw = st.number_input("MW", min_value=0.1, max_value=1000.0,
                                      value=1.0, step=0.5, key="otf_mw")
            with _nv2:
                _price = st.number_input("Trade Price (PLN/MWh)", min_value=0.0, max_value=5000.0,
                                         step=0.5, key="otf_price")

            _vol = _mw * _h
            st.markdown(
                f"**Delivery:** {_ds} → {_de} &nbsp;·&nbsp; "
                f"**Hours:** {_h} &nbsp;·&nbsp; "
                f"**Volume:** {_vol:,.0f} MWh &nbsp;·&nbsp; "
                f"**Notional:** {_vol * _price:,.0f} PLN"
            )

            if st.button("Save Trade", type="primary", key="otf_save"):
                _new = {
                    "id":               _make_id(),
                    "transaction_date": str(_tx_date),
                    "product":          _pcode,
                    "product_type":     "WEEK",
                    "position":         _pos,
                    "mw":               float(_mw),
                    "trade_price":      float(_price),
                    "delivery_start":   str(_ds),
                    "delivery_end":     str(_de),
                    "hours":            _h,
                    "volume_mwh":       round(_vol, 2),
                    "notional_value":   round(_vol * _price, 2),
                }
                _trades.append(_new)
                _save_otf(_trades)
                st.success(f"Saved {_new['id']}")
                st.rerun()

    # ── Trade table ───────────────────────────────────────────────────────────
    if not _trades:
        st.info("No trades recorded yet.")
        return

    _f1 = load_prices()

    def _fmt_pln_mwh(val):
        """Format price as PLN/MWh: 23,89"""
        return f"{val:,.2f}".replace(",", "TEMP").replace(".", ",").replace("TEMP", " ")

    def _fmt_pln_total(val):
        """Format amount as PLN: 239 756,90"""
        return f"{val:,.2f}".replace(",", "TEMP").replace(".", ",").replace("TEMP", " ")

    _rows = []
    for _t in _trades:
        _del_start = datetime.date.fromisoformat(_t["delivery_start"])
        _del_end = datetime.date.fromisoformat(_t["delivery_end"])
        _is_open = _today <= _del_end
        _status = "Open" if _is_open else "Closed"

        # Calculate Close Price: avg F1 for the period (all hours if closed, up to today if open)
        _close_mask = (_f1["delivery_date"] >= _del_start) & (_f1["delivery_date"] <= _del_end)
        if _is_open:
            _close_mask = _close_mask & (_f1["delivery_date"] <= _today)
        _close_data = _f1[_close_mask].dropna(subset=["f1_price_PLN"])
        _close_price = float(_close_data["f1_price_PLN"].mean()) if not _close_data.empty else _t["trade_price"]

        # Calculate Margin (PLN/MWh)
        _trade_price = _t["trade_price"]
        if _t["position"] == "LONG":
            _margin = _close_price - _trade_price
        else:  # SHORT
            _margin = _trade_price - _close_price

        # Total P&L
        _volume = _t["volume_mwh"]
        _pnl = round(_margin * _volume, 2)

        _rows.append({
            "ID":             _t["id"],
            "Tx Date":        _t["transaction_date"],
            "Product":        _t["product"],
            "Position":       _t["position"],
            "MW":             _t["mw"],
            "Del. Start":     _t["delivery_start"],
            "Del. End":       _t["delivery_end"],
            "Volume (MWh)":   _t["volume_mwh"],
            "Trade Price":    _fmt_pln_mwh(_trade_price),
            "Close Price":    _fmt_pln_mwh(_close_price),
            "Margin (PLN/MWh)": _fmt_pln_mwh(_margin),
            "P&L (PLN)":      _fmt_pln_total(_pnl),
            "Status":         _status,
        })

    st.dataframe(pd.DataFrame(_rows), use_container_width=True, hide_index=True)

    # ── Edit / Delete ─────────────────────────────────────────────────────────
    _labels  = [f"{_t['id']} – {_t['product']} {_t['position']} {_t['mw']} MW" for _t in _trades]
    _id_map  = {_t["id"]: _t for _t in _trades}
    _ids     = [_t["id"] for _t in _trades]

    st.divider()

    with st.expander("Edit Trade"):
        _e_sel = st.selectbox("Select trade", ["—"] + _labels, key="otf_edit_sel")
        if _e_sel != "—":
            _eid = _ids[_labels.index(_e_sel)]
            _et  = _id_map[_eid]

            _ec1, _ec2, _ec3 = st.columns([1, 1.3, 1])
            with _ec1:
                _e_txd = st.date_input("Transaction Date",
                                       value=datetime.date.fromisoformat(_et["transaction_date"]),
                                       key="otf_e_txd")
            with _ec2:
                _e_prod = st.text_input("Product", value=_et["product"], key="otf_e_prod")
            with _ec3:
                _e_pos = st.radio("Position", ["LONG", "SHORT"],
                                  index=0 if _et["position"] == "LONG" else 1,
                                  horizontal=True, key="otf_e_pos")

            _ev1, _ev2, _ = st.columns([1, 1.5, 1])
            with _ev1:
                _e_mw = st.number_input("MW", min_value=0.1, max_value=1000.0,
                                        value=float(_et["mw"]), step=0.5, key="otf_e_mw")
            with _ev2:
                _e_price = st.number_input("Trade Price (PLN/MWh)", min_value=0.0, max_value=5000.0,
                                           value=float(_et["trade_price"]), step=0.5, key="otf_e_price")

            _ep = _e_prod.strip().upper()
            _eds, _ede, _eh = _parse_product(_ep) if _ep else (None, None, None)
            if _eds:
                _ev = _e_mw * _eh
                st.markdown(
                    f"**Delivery:** {_eds} → {_ede} &nbsp;·&nbsp; "
                    f"**Volume:** {_ev:,.0f} MWh &nbsp;·&nbsp; "
                    f"**Notional:** {_ev * _e_price:,.0f} PLN"
                )
            elif _ep:
                st.warning("Invalid product code.")

            if st.button("Update", type="primary", key="otf_update"):
                if _eds is None:
                    st.error("Invalid product code.")
                else:
                    _ev = _e_mw * _eh
                    for _t2 in _trades:
                        if _t2["id"] == _eid:
                            _t2.update({
                                "transaction_date": str(_e_txd),
                                "product":          _ep,
                                "position":         _e_pos,
                                "mw":               float(_e_mw),
                                "trade_price":      float(_e_price),
                                "delivery_start":   str(_eds),
                                "delivery_end":     str(_ede),
                                "hours":            _eh,
                                "volume_mwh":       round(_ev, 2),
                                "notional_value":   round(_ev * _e_price, 2),
                            })
                            break
                    _save_otf(_trades)
                    st.success("Updated.")
                    st.rerun()

    with st.expander("Delete Trade"):
        _d_sel = st.selectbox("Select trade", ["—"] + _labels, key="otf_del_sel")
        if _d_sel != "—":
            _did = _ids[_labels.index(_d_sel)]
            _dt  = _id_map[_did]
            st.markdown(
                f"**{_dt['product']}** {_dt['position']} {_dt['mw']} MW "
                f"@ {_dt['trade_price']} PLN/MWh "
                f"({_dt['delivery_start']} → {_dt['delivery_end']})"
            )
            if st.button("Delete", type="secondary", key="otf_del"):
                _trades = [_t for _t in _trades if _t["id"] != _did]
                _save_otf(_trades)
                st.success("Deleted.")
                st.rerun()


# ── OTF MtM page ─────────────────────────────────────────────────────────────

def render_otf_mtm():
    st.title("OTF P&L")
    _trades = _load_otf()
    _today  = datetime.date.today()

    # Filter: only CLOSED positions (delivery_end < today)
    _closed = [_t for _t in _trades
               if _today > datetime.date.fromisoformat(_t["delivery_end"])]

    _f1 = load_prices()

    if not _closed:
        st.info("No closed positions yet. Go to OTF Trades to view open positions.")
        return

    def _fmt_pln(val):
        return f"{val:,.2f}".replace(",", "TEMP").replace(".", ",").replace("TEMP", " ")

    # ── Compute P&L per closed trade ──────────────────────────────────────────
    _pnl_rows = []
    for _t in _closed:
        _del_start = datetime.date.fromisoformat(_t["delivery_start"])
        _del_end = datetime.date.fromisoformat(_t["delivery_end"])

        # Close Price: avg F1 for entire delivery period
        _close_mask = (_f1["delivery_date"] >= _del_start) & (_f1["delivery_date"] <= _del_end)
        _close_data = _f1[_close_mask].dropna(subset=["f1_price_PLN"])
        _close_price = float(_close_data["f1_price_PLN"].mean()) if not _close_data.empty else _t["trade_price"]

        # Calculate P&L
        _trade_price = _t["trade_price"]
        if _t["position"] == "LONG":
            _margin = _close_price - _trade_price
        else:  # SHORT
            _margin = _trade_price - _close_price

        _volume = _t["volume_mwh"]
        _pnl = round(_margin * _volume, 2)

        _pnl_rows.append({
            "ID":               _t["id"],
            "Transaction Date": _t["transaction_date"],
            "Product":          _t["product"],
            "Position":         _t["position"],
            "MW":               _t["mw"],
            "Volume (MWh)":     _t["volume_mwh"],
            "Trade Price":      _fmt_pln(_trade_price),
            "Close Price":      _fmt_pln(_close_price),
            "Margin (PLN/MWh)": _fmt_pln(_margin),
            "P&L (PLN)":        _fmt_pln(_pnl),
            "_tx_date":         datetime.date.fromisoformat(_t["transaction_date"]),
            "_pnl_value":       _pnl,
        })

    _total_pnl = sum(_r["_pnl_value"] for _r in _pnl_rows)

    # ── Summary metrics ───────────────────────────────────────────────────────
    _m1, _m2, _m3 = st.columns(3)
    _m1.metric("Closed Positions", len(_closed))
    _m2.metric("Total P&L", _fmt_pln(_total_pnl),
               delta=_fmt_pln(_total_pnl) if _total_pnl != 0 else None)
    _m3.metric("Winning Trades", len([r for r in _pnl_rows if r["_pnl_value"] > 0]))

    # ── Charts ────────────────────────────────────────────────────────────────
    _pnl_rows_sorted = sorted(_pnl_rows, key=lambda x: x["_tx_date"])

    _c1, _c2 = st.columns([1, 1])

    with _c1:
        # Chart 1: P&L per transaction (timeline)
        _fig1 = go.Figure()
        _fig1.add_trace(go.Scatter(
            x=[_r["_tx_date"] for _r in _pnl_rows_sorted],
            y=[_r["_pnl_value"] for _r in _pnl_rows_sorted],
            mode="markers+lines",
            marker=dict(
                size=10,
                color=[_r["_pnl_value"] for _r in _pnl_rows_sorted],
                colorscale="RdYlGn",
                showscale=False,
                line=dict(width=1, color="white")
            ),
            line=dict(color="#ccc", width=1),
            customdata=[f"{_r['Product']} {_r['Position']}<br>{_r['Margin (PLN/MWh)']}" for _r in _pnl_rows_sorted],
            hovertemplate="<b>%{customdata}</b><br>%{x}<br>P&L: %{y:,.0f} PLN<extra></extra>",
        ))
        _fig1.add_hline(y=0, line_color="#888", line_width=1)
        _fig1.update_layout(
            **CHART_THEME,
            title="P&L per Transaction",
            xaxis_title="Transaction Date",
            yaxis_title="P&L (PLN)",
            height=420,
            hovermode="x unified",
        )
        st.plotly_chart(_fig1, use_container_width=True)

    with _c2:
        # Chart 2: Cumulative P&L (bar chart)
        _cumul_pnl = []
        _cumul_sum = 0.0
        for _r in _pnl_rows_sorted:
            _cumul_sum += _r["_pnl_value"]
            _cumul_pnl.append(_cumul_sum)

        _bar_colors = ["#2dc653" if _v >= 0 else "#e63946" for _v in _cumul_pnl]

        _fig2 = go.Figure()
        _fig2.add_trace(go.Bar(
            x=[_r["_tx_date"] for _r in _pnl_rows_sorted],
            y=_cumul_pnl,
            marker_color=_bar_colors,
            hovertemplate="<b>%{x}</b><br>Cumulative P&L: %{y:,.0f} PLN<extra></extra>",
        ))
        _fig2.add_hline(y=0, line_color="#888", line_width=1)
        _fig2.update_layout(
            **CHART_THEME,
            title="Cumulative P&L",
            xaxis_title="Transaction Date",
            yaxis_title="Cumulative P&L (PLN)",
            height=420,
            hovermode="x unified",
            showlegend=False,
        )
        st.plotly_chart(_fig2, use_container_width=True)

    st.divider()

    # ── Closed positions table (expandable, hidden by default) ────────────────
    with st.expander("Closed Positions — Details"):
        _display_rows = [{k: v for k, v in r.items() if not k.startswith("_")} for r in _pnl_rows]
        st.dataframe(pd.DataFrame(_display_rows), use_container_width=True, hide_index=True)
