"""
var_trading.py — Trading / VAR page
Section A: Risk Parameter Calibration (per-hour volatility, manual accept)
Section B: Daily VAR Monitor (position × volatility × z-score)
"""

import streamlit as st
import pandas as pd
import numpy as np
import os
from datetime import date, datetime, timedelta
from shared import (
    APP_DIR, load_prices, load_trades, load_tso_trades, load_rb_h_cached,
)

Z_SCORE = 1.645  # 95% confidence level

VAR_SPOT_PATH = os.path.join(APP_DIR, "app_data", "var", "var_params_spot.parquet")
VAR_RB_PATH   = os.path.join(APP_DIR, "app_data", "var", "var_params_rb.parquet")

_LOOKBACK_OPTIONS = [30, 60, 90, 180]
_DEFAULT_LOOKBACK = 90

# color thresholds: (upper_bound, hex_color, label)
_BANDS = [
    (50,  "#27ae60", "Green"),
    (75,  "#f0c330", "Yellow"),
    (100, "#e67e22", "Orange"),
]
_COLOR_RED = "#c0392b"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _band_color(pct: float) -> tuple:
    for upper, color, label in _BANDS:
        if pct < upper:
            return color, label
    return _COLOR_RED, "Red"

def _var_path(market: str) -> str:
    return VAR_SPOT_PATH if market == "SPOT" else VAR_RB_PATH

def _df_height(n: int) -> int:
    return n * 35 + 38

def _badge_html(pct: float, daily_var: float, limit: float, market: str) -> str:
    color, label = _band_color(pct)
    return (
        f'<div style="background:{color}18; border-left:4px solid {color}; '
        f'padding:10px 14px; border-radius:6px; margin:8px 0">'
        f'<span style="font-weight:700; font-size:1.2rem; color:{color}">'
        f'{market}: {pct:.1f}% of limit</span><br>'
        f'<span style="color:#555; font-size:0.82rem">'
        f'VaR: {daily_var:,.0f} PLN &nbsp;|&nbsp; Limit: {limit:,.0f} PLN'
        f'</span></div>'
    )


# ── Data layer ─────────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def _load_params(market: str) -> pd.DataFrame:
    path = _var_path(market)
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_parquet(path)
    df["calibration_timestamp"] = pd.to_datetime(df["calibration_timestamp"])
    df["accepted_timestamp"]    = pd.to_datetime(df["accepted_timestamp"])
    return df


def _get_active_params(market: str):
    """Latest accepted 24-row calibration, or None."""
    df = _load_params(market)
    if df.empty:
        return None
    accepted = df[df["status"] == "accepted"]
    if accepted.empty:
        return None
    latest_id = (
        accepted.sort_values("calibration_timestamp")
        .iloc[-1]["calibration_id"]
    )
    return accepted[accepted["calibration_id"] == latest_id].copy()


def _get_pending_proposed(market: str):
    """Returns (cal_id, df_rows) of the latest fully-proposed calibration, or None."""
    df = _load_params(market)
    if df.empty:
        return None
    proposed = df[df["status"] == "proposed"]
    if proposed.empty:
        return None
    latest_id = (
        proposed.sort_values("calibration_timestamp")
        .iloc[-1]["calibration_id"]
    )
    rows = df[df["calibration_id"] == latest_id]
    if (rows["status"] == "proposed").all():
        return latest_id, rows.copy()
    return None


def _get_spot_position(entry_date: date) -> dict:
    date_str = str(entry_date)
    pos = {}
    for t in load_trades():
        if t["fixing_date"] == date_str:
            h   = t["hour"]
            mw  = float(t["volume_mw"])
            sign = 1 if t["direction"] == "Long" else -1
            pos[h] = pos.get(h, 0.0) + sign * mw
    return pos


def _get_rb_position(entry_date: date) -> dict:
    """Net MW per hour. Averages across quarters to avoid 4× inflation."""
    date_str   = str(entry_date)
    hour_mw    = {}
    hour_count = {}
    for t in load_tso_trades():
        if t["fixing_date"] == date_str:
            h    = t["hour"]
            mw   = float(t["volume_mw"])
            sign = 1 if t["direction"] == "Long" else -1
            hour_mw[h]    = hour_mw.get(h, 0.0) + sign * mw
            hour_count[h] = hour_count.get(h, 0) + 1
    return {h: hour_mw[h] / hour_count[h] for h in hour_mw}


# ── Calculation ────────────────────────────────────────────────────────────────

def _calc_var(positions: dict, params_df: pd.DataFrame) -> dict:
    sigma_map = {
        row["hour"]: float(row["volatility"])
        for _, row in params_df.iterrows()
    }
    accepted_limit = float(params_df.iloc[0]["accepted_limit_pln"])

    breakdown = []
    daily_var  = 0.0

    for h in range(1, 25):
        hour_str = f"H{h:02d}"
        net_mw   = positions.get(h, 0.0)
        sigma    = sigma_map.get(hour_str, 0.0)
        risk     = abs(net_mw) * sigma * Z_SCORE
        daily_var += risk

        if net_mw > 0:
            dir_label = "Long"
        elif net_mw < 0:
            dir_label = "Short"
        else:
            dir_label = "—"

        breakdown.append({
            "Hour":          hour_str,
            "Position (MW)": round(abs(net_mw), 2),
            "Dir":           dir_label,
            "Volatility":    round(sigma, 4),
            "Risk (PLN)":    round(risk, 2),
        })

    pct = (daily_var / accepted_limit * 100) if accepted_limit > 0 else 0.0
    return {
        "daily_var":     round(daily_var, 2),
        "pct_of_limit":  round(pct, 2),
        "accepted_limit": accepted_limit,
        "breakdown":     breakdown,
    }


def _compute_spot_volatility(lookback_days: int) -> pd.DataFrame:
    df     = load_prices()
    cutoff = date.today() - timedelta(days=lookback_days)
    df     = df[df["delivery_date"] >= cutoff].copy()
    df["spread"] = df["f1_price_PLN"] - df["sdac_price_PLN"]

    rows = []
    for h in range(1, 25):
        s   = df[df["H"] == h]["spread"].dropna()
        vol = float(s.std()) if len(s) >= 2 else 0.0
        rows.append({
            "Hour":                 f"H{h:02d}",
            "Volatility (PLN/MWh)": round(vol, 4),
            "N days":               len(s),
        })
    return pd.DataFrame(rows)


def _compute_rb_volatility(lookback_days: int) -> pd.DataFrame:
    df     = load_rb_h_cached()
    cutoff = date.today() - timedelta(days=lookback_days)
    df     = df[df["delivery_date"] >= cutoff].copy()
    df["spread"] = df["csdac_pln"] - df["cen_cost"]

    rows = []
    for h in range(1, 25):
        s   = df[df["H"] == h]["spread"].dropna()
        vol = float(s.std()) if len(s) >= 2 else 0.0
        rows.append({
            "Hour":                 f"H{h:02d}",
            "Volatility (PLN/MWh)": round(vol, 4),
            "N days":               len(s),
        })
    return pd.DataFrame(rows)


# ── Parquet writes ─────────────────────────────────────────────────────────────

def _gen_cal_id() -> str:
    import uuid
    return str(uuid.uuid4())[:8].upper()


def _save_proposed(market: str, vol_df: pd.DataFrame, lookback_days: int) -> str:
    path   = _var_path(market)
    cal_id = _gen_cal_id()
    now    = datetime.now()

    rows = [
        {
            "calibration_id":       cal_id,
            "calibration_timestamp": now,
            "hour":                 row["Hour"],
            "volatility":           row["Volatility (PLN/MWh)"],
            "lookback_window_days": lookback_days,
            "accepted_limit_pln":   0.0,
            "status":               "proposed",
            "accepted_timestamp":   pd.NaT,
        }
        for _, row in vol_df.iterrows()
    ]
    df_new = pd.DataFrame(rows)

    if os.path.exists(path):
        df_ex  = pd.read_parquet(path)
        df_all = pd.concat([df_ex, df_new], ignore_index=True)
    else:
        df_all = df_new

    tmp = path + ".tmp"
    df_all.to_parquet(tmp, index=False)
    os.replace(tmp, path)
    _load_params.clear()
    return cal_id


def _accept_params(market: str, cal_id: str, limit_pln: float):
    path = _var_path(market)
    df   = pd.read_parquet(path)
    mask = (df["calibration_id"] == cal_id) & (df["status"] == "proposed")
    df.loc[mask, "status"]            = "accepted"
    df.loc[mask, "accepted_limit_pln"] = limit_pln
    df.loc[mask, "accepted_timestamp"] = datetime.now()
    tmp = path + ".tmp"
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)
    _load_params.clear()


def _discard_proposed(market: str, cal_id: str):
    path = _var_path(market)
    df   = pd.read_parquet(path)
    df   = df[~((df["calibration_id"] == cal_id) & (df["status"] == "proposed"))]
    tmp  = path + ".tmp"
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)
    _load_params.clear()


# ── UI components ──────────────────────────────────────────────────────────────

def _show_vol_table(df: pd.DataFrame):
    disp = (
        df[["hour", "volatility"]]
        .rename(columns={"hour": "Hour", "volatility": "Volatility (PLN/MWh)"})
        .sort_values("Hour")
        .reset_index(drop=True)
    )
    st.dataframe(disp, hide_index=True, use_container_width=True,
                 height=_df_height(len(disp)))


def _render_calibration_section(market: str):
    # ── Active params ──────────────────────────────────────────────────────────
    active  = _get_active_params(market)
    pending = _get_pending_proposed(market)

    if active is not None:
        cal_ts = pd.to_datetime(
            active.iloc[0]["calibration_timestamp"]
        ).strftime("%Y-%m-%d %H:%M")
        lw    = int(active.iloc[0]["lookback_window_days"])
        limit = float(active.iloc[0]["accepted_limit_pln"])
        with st.expander(
            f"Active parameters — calibrated {cal_ts} · {lw}d window · "
            f"Limit: {limit:,.0f} PLN",
            expanded=False,
        ):
            _show_vol_table(active)
    else:
        st.info("No active parameters yet. Run calibration below.")

    # ── Pending proposed ───────────────────────────────────────────────────────
    if pending is not None:
        cal_id, prop_df = pending
        cal_ts = pd.to_datetime(
            prop_df.iloc[0]["calibration_timestamp"]
        ).strftime("%Y-%m-%d %H:%M")
        lw = int(prop_df.iloc[0]["lookback_window_days"])

        st.warning(
            f"Proposed parameters pending acceptance "
            f"— calculated {cal_ts} · {lw}d lookback"
        )
        _show_vol_table(prop_df)

        default_limit = (
            float(active.iloc[0]["accepted_limit_pln"])
            if active is not None else 10_000.0
        )
        _lc, _ac, _dc = st.columns([2.5, 1, 1])
        limit_val = _lc.number_input(
            f"Accepted Daily VaR Limit — {market} (PLN)",
            min_value=0.0,
            value=default_limit,
            step=500.0,
            format="%.0f",
            key=f"var_limit_{market}_{cal_id}",
        )
        with _ac:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Accept", type="primary",
                         key=f"var_accept_{market}_{cal_id}",
                         use_container_width=True):
                _accept_params(market, cal_id, limit_val)
                st.success(f"Accepted. Limit set to {limit_val:,.0f} PLN.")
                st.rerun()
        with _dc:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Discard", key=f"var_discard_{market}_{cal_id}",
                         use_container_width=True):
                _discard_proposed(market, cal_id)
                st.rerun()

    st.markdown("---")

    # ── Recalculate ────────────────────────────────────────────────────────────
    _r1, _r2 = st.columns([1, 2])
    lookback = _r1.selectbox(
        "Lookback window",
        options=_LOOKBACK_OPTIONS,
        index=_LOOKBACK_OPTIONS.index(_DEFAULT_LOOKBACK),
        format_func=lambda x: f"{x} days",
        key=f"var_lookback_{market}",
    )
    with _r2:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button(
            f"Recalculate {market} Parameters",
            key=f"var_recalc_{market}",
            type="secondary",
            use_container_width=True,
        ):
            with st.spinner(f"Computing {market} volatility ({lookback}d)…"):
                vol_df = (
                    _compute_spot_volatility(lookback)
                    if market == "SPOT"
                    else _compute_rb_volatility(lookback)
                )
                _save_proposed(market, vol_df, lookback)
            st.success("Proposed parameters saved — review and accept above.")
            st.rerun()


def _render_daily_monitor():
    _dc, _ = st.columns([1, 2])
    sel_date = _dc.date_input(
        "Fixing date", value=date.today(), key="var_daily_date"
    )

    c_spot, c_rb = st.columns(2)

    for col, market in [(c_spot, "SPOT"), (c_rb, "RB")]:
        with col:
            st.markdown(f"**{market}**")
            active = _get_active_params(market)
            if active is None:
                st.warning("Not calibrated.")
                continue

            cal_ts = pd.to_datetime(
                active.iloc[0]["calibration_timestamp"]
            ).strftime("%Y-%m-%d")
            lw    = int(active.iloc[0]["lookback_window_days"])
            limit = float(active.iloc[0]["accepted_limit_pln"])
            st.caption(f"Params: {cal_ts} · {lw}d · Limit: {limit:,.0f} PLN")

            if st.button(
                f"Calculate {market} VAR",
                key=f"var_daily_btn_{market}",
                type="secondary",
            ):
                pos = (
                    _get_spot_position(sel_date)
                    if market == "SPOT"
                    else _get_rb_position(sel_date)
                )
                result = _calc_var(pos, active)
                st.session_state[f"var_daily_result_{market}"] = result
                st.rerun()

            res_key = f"var_daily_result_{market}"
            if res_key in st.session_state:
                r     = st.session_state[res_key]
                pct   = r["pct_of_limit"]
                color, _ = _band_color(pct)

                st.markdown(
                    _badge_html(pct, r["daily_var"], r["accepted_limit"], market),
                    unsafe_allow_html=True,
                )

                with st.expander("Hour breakdown"):
                    df_bd = pd.DataFrame(r["breakdown"])
                    active_rows = df_bd[df_bd["Risk (PLN)"] > 0]
                    if active_rows.empty:
                        st.info("No open positions.")
                    else:
                        st.dataframe(
                            active_rows,
                            hide_index=True,
                            use_container_width=True,
                            height=_df_height(len(active_rows)),
                        )


# ── Public: widget for embedding in FixTrade / TSOTrade ───────────────────────

def render_var_widget(market: str, entry_date):
    """Compact VAR check for embedding in FixTrade (SPOT) and TSOTrade (RB)."""
    active = _get_active_params(market)

    st.markdown(
        f'<p style="font-size:0.8rem; color:#888; margin-bottom:2px">'
        f'VAR Check — {market}</p>',
        unsafe_allow_html=True,
    )

    if active is None:
        st.caption("Not calibrated — go to **Trading → VAR** to set up parameters.")
        return

    cal_ts = pd.to_datetime(
        active.iloc[0]["calibration_timestamp"]
    ).strftime("%Y-%m-%d")
    lw    = int(active.iloc[0]["lookback_window_days"])
    limit = float(active.iloc[0]["accepted_limit_pln"])
    st.caption(f"Params: {cal_ts} · {lw}d · Limit: {limit:,.0f} PLN")

    btn_key = f"var_widget_btn_{market}_{entry_date}"
    res_key = f"var_widget_result_{market}_{entry_date}"

    if st.button("Calculate VAR", key=btn_key, type="secondary"):
        pos = (
            _get_spot_position(entry_date)
            if market == "SPOT"
            else _get_rb_position(entry_date)
        )
        result = _calc_var(pos, active)
        st.session_state[res_key] = result
        st.rerun()

    if res_key in st.session_state:
        r   = st.session_state[res_key]
        pct = r["pct_of_limit"]

        st.markdown(
            _badge_html(pct, r["daily_var"], r["accepted_limit"], market),
            unsafe_allow_html=True,
        )

        with st.expander("Hour breakdown"):
            df_bd       = pd.DataFrame(r["breakdown"])
            active_rows = df_bd[df_bd["Risk (PLN)"] > 0]
            if active_rows.empty:
                st.info("No open positions.")
            else:
                st.dataframe(
                    active_rows,
                    hide_index=True,
                    use_container_width=True,
                    height=_df_height(len(active_rows)),
                )


# ── Public: main VAR page ──────────────────────────────────────────────────────

def render_var():
    st.title("VAR Monitor")
    st.caption(
        "Value at Risk — SPOT (F1–SDAC spread) and RB (SDAC–CEN spread) "
        "| z = 1.645 (95% confidence)"
    )

    # Active params summary
    c_s, c_r = st.columns(2)
    for col, market in [(c_s, "SPOT"), (c_r, "RB")]:
        with col:
            a = _get_active_params(market)
            if a is not None:
                cal_ts = pd.to_datetime(
                    a.iloc[0]["calibration_timestamp"]
                ).strftime("%Y-%m-%d %H:%M")
                lw    = int(a.iloc[0]["lookback_window_days"])
                limit = float(a.iloc[0]["accepted_limit_pln"])
                st.metric(
                    f"{market} — Active Params",
                    f"{limit:,.0f} PLN limit",
                    f"Calibrated {cal_ts} · {lw}d window",
                )
            else:
                st.metric(f"{market} — Active Params", "Not calibrated", "—")

    st.divider()

    # Section A
    st.subheader("Section A — Risk Parameter Calibration")
    tab_spot, tab_rb = st.tabs(["SPOT  (F1 – SDAC)", "RB  (SDAC – CEN)"])

    with tab_spot:
        _render_calibration_section("SPOT")

    with tab_rb:
        _render_calibration_section("RB")

    st.divider()

    # Section B
    st.subheader("Section B — Daily VAR Monitor")
    _render_daily_monitor()
