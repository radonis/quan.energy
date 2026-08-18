import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import json, os, time, base64, calendar, re as _re
from datetime import date, timedelta, datetime

# ── Page config (must be first Streamlit call) ────────────────────────────────
try:
    from PIL import Image as _PIL_Image
    _page_icon = _PIL_Image.open(os.path.join(os.path.dirname(__file__), "pics", "icon2.png"))
except Exception:
    _page_icon = "⚡"

st.set_page_config(page_title="Quan.Energy", page_icon=_page_icon, layout="wide")

# ── Cookie manager ────────────────────────────────────────────────────────────
try:
    import extra_streamlit_components as stx
    _cookie_mgr  = stx.CookieManager(key="qe_cookie_mgr")
    _COOKIE_NAME = "qe_auth"
    _COOKIE_VAL  = "qe_ok_2026"
    _COOKIES_OK  = True
except Exception:
    _COOKIES_OK  = False

# ── Login page style helper ───────────────────────────────────────────────────
def _render_login_page():
    _bg_path = os.path.join(os.path.dirname(__file__), "pics", "NJGT.jpg")
    try:
        with open(_bg_path, "rb") as _bf:
            _bg_b64 = base64.b64encode(_bf.read()).decode()
        _bg_css = f"url('data:image/jpeg;base64,{_bg_b64}')"
    except Exception:
        _bg_css = "none"

    st.markdown(f"""
        <style>
        .stApp {{
            background-color: #ffffff;
            background-image: {_bg_css};
            background-size: auto 60%;
            background-position: center center;
            background-repeat: no-repeat;
            background-attachment: fixed;
        }}
        section[data-testid="stSidebar"] {{ display: none; }}
        header[data-testid="stHeader"] {{ display: none; }}
        .block-container {{
            max-width: 420px !important;
            margin: 0 auto !important;
            padding-top: calc(50vh - 140px) !important;
            padding-bottom: 2rem !important;
        }}
        .login-card {{
            background: rgba(10, 15, 30, 0.82);
            backdrop-filter: blur(8px);
            border-radius: 16px;
            padding: 2rem 2rem 0.5rem 2rem;
            box-shadow: 0 8px 32px rgba(0,0,0,0.5);
        }}
        </style>
        <div class="login-card">
            <div style="text-align:center; margin-bottom:2.2rem;">
                <div style="font-size:1.1rem; font-weight:700; letter-spacing:3px;
                            background: linear-gradient(135deg,#00e5ff,#2979ff);
                            -webkit-background-clip:text; -webkit-text-fill-color:transparent;">
                    QUAN.ENERGY
                </div>
                <div style="color:#aaa; font-size:0.78rem; margin-top:6px; letter-spacing:1px;">
                    TRADING MONITORING SYSTEM
                </div>
            </div>
        </div>
        <div style="margin-top: 1.4rem;"></div>
    """, unsafe_allow_html=True)

# ── Auth ──────────────────────────────────────────────────────────────────────
def _check_password():
    # Already authenticated this session
    if st.session_state.get("authenticated"):
        return

    # Check persistent cookie
    if _COOKIES_OK:
        try:
            if _cookie_mgr.get(_COOKIE_NAME) == _COOKIE_VAL:
                st.session_state.authenticated = True
                return
        except Exception:
            pass

    # Show login form
    _render_login_page()
    pwd = st.text_input("Password", type="password", placeholder="Enter password",
                        label_visibility="collapsed")
    if st.button("Login", type="primary", use_container_width=True):
        if pwd == "qe2026":
            st.session_state.authenticated = True
            if _COOKIES_OK:
                try:
                    _cookie_mgr.set(
                        _COOKIE_NAME, _COOKIE_VAL,
                        expires_at=datetime.now() + timedelta(days=14),
                    )
                except Exception:
                    pass
            st.rerun()
        else:
            st.error("Wrong password")
    st.stop()

_check_password()

# ── Config ────────────────────────────────────────────────────────────────────
PARQUET_PATH    = os.path.join(os.path.dirname(__file__), "FixingPricesH.parquet")
TRADES_PATH     = os.path.join(os.path.dirname(__file__), "trades.json")
DE_PRICES_PATH  = os.path.join(os.path.dirname(__file__), "energy_charts", "de_prices.parquet")
EURPLN_PATH     = os.path.join(os.path.dirname(__file__), "prices", "EURPLN_Rate.parquet")
PSE_PRICES_PATH  = os.path.join(os.path.dirname(__file__), "prices", "pse_prices.parquet")
RB_H_PATH        = os.path.join(os.path.dirname(__file__), "prices", "RB_prices_H.parquet")
PSCMI_PATH       = os.path.join(os.path.dirname(__file__), "prices", "pscmi.parquet")
CDS_PARAMS_PATH  = os.path.join(os.path.dirname(__file__), "cds_params.json")
CCS_PARAMS_PATH  = os.path.join(os.path.dirname(__file__), "ccs_params.json")
TSO_TRADES_PATH  = os.path.join(os.path.dirname(__file__), "tso_trades.json")
PK5_PATH         = os.path.join(os.path.dirname(__file__), "PK5", "pk5.parquet")
PK5FOR_PATH      = os.path.join(os.path.dirname(__file__), "PK5", "pk5for.parquet")
ETS_CO2_PATH     = os.path.join(os.path.dirname(__file__), "prices", "ets_co2.parquet")
OTF_GAS_PATH     = os.path.join(os.path.dirname(__file__), "prices", "tge_otf_gas.parquet")
OTF_EE_PATH      = os.path.join(os.path.dirname(__file__), "prices", "tge_otf_ee.parquet")
DE_SPOT_PATH      = os.path.join(os.path.dirname(__file__), "prices", "de_spot.parquet")
PSE_DEMAND_PATH   = os.path.join(os.path.dirname(__file__), "prices", "pse_demand.parquet")
FORECAST_DB_PATH  = os.environ.get("FORECAST_DB_PATH", "/home/ubuntu/db/forecast_db.duckdb")
DE_FORE_PATH     = os.environ.get("DE_FORE_PATH",     "/home/ubuntu/data/de/DE_Price_72H_Forecast.parquet")


# ── Chart theme (white background) ───────────────────────────────────────────
CHART_THEME = dict(
    plot_bgcolor="white",
    paper_bgcolor="white",
    font=dict(color="#333"),
)

# ── Helpers ───────────────────────────────────────────────────────────────────
def _otf_delivery_hours(pname: str, ptype: str):
    parts = str(pname).split("-")
    try:
        year = 2000 + int(parts[-1])
    except Exception:
        return None
    try:
        if ptype == "M":
            return calendar.monthrange(year, int(parts[-2]))[1] * 24
        elif ptype == "Q":
            q = int(parts[-2])
            s = (q - 1) * 3 + 1
            return sum(calendar.monthrange(year, m)[1] for m in range(s, s + 3)) * 24
        elif ptype == "Y":
            return (366 if calendar.isleap(year) else 365) * 24
    except Exception:
        return None
    return None

@st.cache_data(ttl=3600)
def load_otf_ee() -> pd.DataFrame:
    if not os.path.exists(OTF_EE_PATH):
        return pd.DataFrame()
    df = pd.read_parquet(OTF_EE_PATH)
    df["date"]      = pd.to_datetime(df["date"])
    df["price"]     = pd.to_numeric(df["dkr"],    errors="coerce")
    df["trades"]    = pd.to_numeric(df["trades"], errors="coerce")
    _hrs = df.apply(lambda r: _otf_delivery_hours(r["product_name"], r["product_type"]), axis=1)
    df["quantity_mw"] = (pd.to_numeric(df["vol_mwh"], errors="coerce") / _hrs).round(1)
    df["is_traded"] = pd.to_numeric(df["vol_mwh"], errors="coerce").fillna(0) > 0
    df = df[df["date"].dt.weekday < 5]
    return df

@st.cache_data(ttl=3600)
def load_otf_gas() -> pd.DataFrame:
    if not os.path.exists(OTF_GAS_PATH):
        return pd.DataFrame()
    df = pd.read_parquet(OTF_GAS_PATH)
    df["date"]        = pd.to_datetime(df["date"])
    df["price"]       = pd.to_numeric(df["DKR (PLN/MWh)"],    errors="coerce")
    df["trades"]      = pd.to_numeric(df["Liczba kontraktów"], errors="coerce")
    df["quantity_mw"] = df["trades"]
    df["is_traded"]   = df["trades"].fillna(0) > 0
    df = df[df["date"].dt.weekday < 5]
    return df

@st.cache_data(ttl=3600)
def load_de_spot() -> pd.DataFrame:
    if not os.path.exists(DE_SPOT_PATH):
        return pd.DataFrame()
    df = pd.read_parquet(DE_SPOT_PATH)
    df["datetime_utc"] = pd.to_datetime(df["datetime_utc"])
    df["date"]         = pd.to_datetime(df["date"]).dt.date
    return df

@st.cache_data(ttl=3600)
def load_ets() -> pd.DataFrame:
    if not os.path.exists(ETS_CO2_PATH):
        return pd.DataFrame()
    df = pd.read_parquet(ETS_CO2_PATH)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["settlement"] = pd.to_numeric(df["settlement"], errors="coerce")
    return df

@st.cache_data(ttl=3600)
def load_pk5() -> pd.DataFrame:
    if not os.path.exists(PK5_PATH):
        return pd.DataFrame()
    df = pd.read_parquet(PK5_PATH)
    df["plan_dtime"]    = pd.to_datetime(df["plan_dtime"])
    df["business_date"] = pd.to_datetime(df["business_date"]).dt.date
    for col in ["fcst_wi_tot_gen", "fcst_pv_tot_gen", "grid_demand_fcst", "pred_gen_res_not_cov"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df

@st.cache_data(ttl=3600)
def load_pk5for() -> pd.DataFrame:
    if not os.path.exists(PK5FOR_PATH):
        return pd.DataFrame()
    df = pd.read_parquet(PK5FOR_PATH)
    df["business_date"]  = pd.to_datetime(df["business_date"]).dt.date
    df["snapshot_date"]  = pd.to_datetime(df["snapshot_date"]).dt.date
    for col in ["grid_demand_fcst", "fcst_wi_tot_gen", "fcst_pv_tot_gen",
                "planned_exchange", "fcst_unav_energy"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["H"] = df["period"].str[:2].astype(int) + 1
    return df

@st.cache_data(ttl=3600)
def load_pse_demand() -> pd.DataFrame:
    if not os.path.exists(PSE_DEMAND_PATH):
        return pd.DataFrame()
    df = pd.read_parquet(PSE_DEMAND_PATH)
    df["business_date"] = pd.to_datetime(df["business_date"]).dt.date
    df["dtime"]         = pd.to_datetime(df["dtime"])
    for col in ["load_actual", "load_fcst"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df

@st.cache_data(ttl=3600)
def load_pse() -> pd.DataFrame:
    if not os.path.exists(PSE_PRICES_PATH):
        return pd.DataFrame()
    df = pd.read_parquet(PSE_PRICES_PATH)
    df["dtime"]         = pd.to_datetime(df["dtime"])
    df["business_date"] = pd.to_datetime(df["business_date"]).dt.date
    return df

@st.cache_data(ttl=3600)
def load_rb_h_cached() -> pd.DataFrame:
    if not os.path.exists(RB_H_PATH):
        return pd.DataFrame()
    df = pd.read_parquet(RB_H_PATH)
    df["delivery_date"] = pd.to_datetime(df["delivery_date"]).dt.date
    return df

@st.cache_data(ttl=3600)
def load_pscmi() -> pd.DataFrame:
    if not os.path.exists(PSCMI_PATH):
        return pd.DataFrame()
    df = pd.read_parquet(PSCMI_PATH)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df

@st.cache_data(ttl=3600)
def load_de_prices() -> pd.DataFrame:
    if not os.path.exists(DE_PRICES_PATH):
        return pd.DataFrame()
    df = pd.read_parquet(DE_PRICES_PATH)
    df["business_date"] = pd.to_datetime(df["business_date"]).dt.date
    return df

@st.cache_data(ttl=3600)
def load_eurpln() -> pd.DataFrame:
    if not os.path.exists(EURPLN_PATH):
        return pd.DataFrame()
    df = pd.read_parquet(EURPLN_PATH)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df

@st.cache_data(ttl=3600)
def load_prices() -> pd.DataFrame:
    df = pd.read_parquet(PARQUET_PATH)
    df["fixing_date"]   = pd.to_datetime(df["fixing_date"]).dt.date
    df["delivery_date"] = pd.to_datetime(df["delivery_date"]).dt.date
    return df

def load_trades() -> list:
    if os.path.exists(TRADES_PATH):
        with open(TRADES_PATH, "r") as f:
            return json.load(f)
    return []

def save_trades(trades: list):
    with open(TRADES_PATH, "w") as f:
        json.dump(trades, f, indent=2, default=str)

def load_tso_trades() -> list:
    if os.path.exists(TSO_TRADES_PATH):
        with open(TSO_TRADES_PATH, "r") as f:
            return json.load(f)
    return []

def save_tso_trades(tso_trades: list):
    with open(TSO_TRADES_PATH, "w") as f:
        json.dump(tso_trades, f, indent=2, default=str)

def calc_pnl(direction: str, volume_mw: float, spread: float) -> float:
    """Short = sell F1, buy SDAC → profit when F1 > SDAC (spread > 0)
       Long  = buy F1, sell SDAC → profit when SDAC > F1 (spread < 0)"""
    sign = 1 if direction == "Short" else -1
    return sign * spread * volume_mw

# ── Load data ─────────────────────────────────────────────────────────────────
prices = load_prices()
trades     = load_trades()
tso_trades = load_tso_trades()

available_dates = sorted(prices[prices["H"] >= 1]["fixing_date"].unique())
last_date       = available_dates[-1]

# ── Sidebar nav ───────────────────────────────────────────────────────────────
st.sidebar.title("Menu")

_SPOT_PAGES    = ["Prices", "German SPOT"]
_TRADING_PAGES = ["FixTrade", "TSOTrade", "P&L Dashboard", "FixHeatmap", "TSOHeatmap"]
_TSO_PAGES     = ["PK5", "PSE", "PowerDemand", "PSE_Viewer", "PK5_Snapshots"]
_FC_PAGES      = ["Forecast", "WeeklyForecast", "Plotting", "Model Performance"]
_FWD_PAGES     = ["OTF / EE", "OTF / Gas", "ETS1", "CurrentCDS", "CurrentCCS", "Coal", "Liquidity", "Compare"]
_ADM_PAGES     = ["Parquet", "Logs", "Admin", "CDS", "CCS"]

# Display label overrides (internal page key → sidebar label)
_PAGE_LABELS = {
    "CurrentCDS": "CDS",
    "CurrentCCS": "CCS",
    "WeeklyForecast": "Weekly",
    "Model Performance": "Performance",
    "PSE_Viewer": "PSE Viewer",
    "PK5_Snapshots": "PK5 Snapshots",
    "PowerDemand": "Power Demand",
    "German SPOT": "German SPOT",
    "P&L Dashboard": "P&L Dashboard",
}

if "page" not in st.session_state:
    st.session_state.page = "Prices"

st.markdown("""
<style>
section[data-testid="stSidebar"] .stButton > button {
    width: 100%;
    text-align: left;
    padding: 4px 12px;
    margin: 1px 0;
    font-size: 14px;
}
</style>
""", unsafe_allow_html=True)

def _nav_btn(page_key):
    label     = _PAGE_LABELS.get(page_key, page_key)
    is_active = (st.session_state.page == page_key)
    if st.sidebar.button(label, key=f"nav_{page_key}",
                         use_container_width=True,
                         type="primary" if is_active else "secondary"):
        st.session_state.page = page_key
        st.rerun()

def _nav_section(title, pages):
    st.sidebar.markdown(f"<small style='color:#888;padding-left:4px'>{title}</small>",
                        unsafe_allow_html=True)
    for p in pages:
        _nav_btn(p)

_nav_section("SPOT",    _SPOT_PAGES)
st.sidebar.markdown("---")
_nav_section("Trading", _TRADING_PAGES)
st.sidebar.markdown("---")
_nav_section("TSO",     _TSO_PAGES)
st.sidebar.markdown("---")
_nav_section("Forecast",_FC_PAGES)
st.sidebar.markdown("---")
_nav_section("Forward", _FWD_PAGES)
st.sidebar.markdown("---")
_nav_section("Admin",   _ADM_PAGES)

page = st.session_state.page

# ══════════════════════════════════════════════════════════════════════════════
# PAGE 1 — PRICES
# ══════════════════════════════════════════════════════════════════════════════
if page == "Prices":
    st.title("Prices")

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

    # ── Load CEN data (PSE) for selected delivery date ────────────────────
    cen_by_hour = {}
    if show_cen:
        pse_df_p = load_pse()
        if not pse_df_p.empty:
            pse_day = pse_df_p[pse_df_p["business_date"] == sel_delivery].copy()
            if not pse_day.empty:
                pse_day["hour_num"] = (
                    (pse_day["dtime"].dt.hour * 60 + pse_day["dtime"].dt.minute - 1) // 60 + 1
                )
                cen_hourly = (
                    pse_day.groupby("hour_num")["cen_cost"].mean()
                )
                cen_by_hour = {int(h): round(float(v), 2)
                               for h, v in cen_hourly.items()
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
            line=dict(color="#1b5e20", width=2, dash="dash"),
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
    m1, m2, m3, m4 = st.columns(4)
    spread_clean = [s for s in spread if s is not None and not pd.isna(s)]
    m1.metric("F1 avg", f"{avg_f1:.1f} PLN/MWh")
    m2.metric("SDAC avg", f"{avg_sdac:.1f} PLN/MWh")
    m3.metric("Max spread", f"{max(spread_clean):.1f} PLN/MWh")
    m4.metric("Min spread", f"{min(spread_clean):.1f} PLN/MWh")

    # ── Update German SPOT button ─────────────────────────────────────────
    st.divider()
    if st.button("Update German SPOT", use_container_width=False):
        import importlib.util as _ilu
        def _load_mod(path, name):
            spec = _ilu.spec_from_file_location(name, path)
            mod  = _ilu.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
        _root     = os.path.dirname(__file__)
        _de_prices = _load_mod(os.path.join(_root, "energy_charts", "de_prices.py"), "de_prices")
        _nbp       = _load_mod(os.path.join(_root, "prices",        "nbp_eurpln.py"), "nbp_eurpln")
        lines = []
        with st.spinner("Updating DE prices and EUR/PLN rate..."):
            r1 = _de_prices.run_pipeline(app_dir=_root, log=lambda m: lines.append(m))
            r2 = _nbp.run_pipeline(app_dir=_root, log=lambda m: lines.append(m))
        load_de_prices.clear()
        load_eurpln.clear()
        st.success(
            f"DE prices: {r1.get('new_rows', 0)} new rows.  "
            f"EUR/PLN: {r2.get('new_rows', 0)} new rows."
        )
        with st.expander("Pipeline log"):
            st.text("\n".join(lines))
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — FIXTRADE
# ══════════════════════════════════════════════════════════════════════════════
elif page == "FixTrade":
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
                        import sys, os as _os
                        sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), "procedures"))
                        from tge_fixing import run_pipeline
                        lines = []
                        with st.spinner("Downloading from TGE..."):
                            result = run_pipeline(
                                app_dir=_os.path.dirname(__file__),
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
                _rows_fv.append({
                    "#":         _i,
                    "Date":      _t.get("fixing_date", ""),
                    "Hour":      f"H{int(_t.get('hour', 0)):02d}",
                    "MW":        _t.get("volume_mw", ""),
                    "Direction": str(_t.get("direction", "")).capitalize(),
                    "Status":    "Priced" if _pnl is not None else "Open",
                    "P&L":       round(_pnl, 2) if _pnl is not None else None,
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


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 3 — TSOTRADE
# ══════════════════════════════════════════════════════════════════════════════
elif page == "TSOTrade":
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

            if not is_locked:
                edited_hour = st.data_editor(
                    df_hour,
                    column_config={
                        "H":         st.column_config.TextColumn("H",   disabled=True, width=55),
                        "MW":        st.column_config.NumberColumn("MW", min_value=0.0,
                                         max_value=500.0, step=0.5, width=80),
                        "Direction": st.column_config.SelectboxColumn(
                                         "Direction", options=["—", "Short", "Long"], width=110),
                    },
                    hide_index=True,
                    use_container_width=False,
                    height=882,
                    key=f"tso_hour_grid_{date_str}_{st.session_state[_impkv_key]}",
                )

                btn_a, btn_b = st.columns(2)
                with btn_a:
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
                with btn_b:
                    if st.button("Expand to quarters →", type="primary",
                                 use_container_width=True, key=f"tso_expand_{date_str}"):
                        st.session_state[_hourdat_key] = edited_hour.to_dict("records")
                        st.session_state[_expand_key]  = True
                        st.rerun()
            else:
                st.dataframe(df_hour, hide_index=True, use_container_width=False, height=882)
                st.info("Locked — use Quarter view to see all 96 slots.")
                if st.button("View quarters →", key=f"tso_view_qt_{date_str}"):
                    st.session_state[_expand_key] = True
                    st.rerun()

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
                        _prices_fresh = load_prices()
                        _pse_fresh    = load_pse()
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
                                # CEN = 15-min slot on delivery_date
                                # hour index 0-based, minute from quarter
                                _tgt_h = _h - 1
                                _tgt_m = (_q - 1) * 15
                                _r_pse = _pse_fresh[
                                    (_pse_fresh["business_date"] == delivery_date) &
                                    (_pse_fresh["dtime"].dt.hour   == _tgt_h) &
                                    (_pse_fresh["dtime"].dt.minute == _tgt_m)
                                ]

                                if _r_fix.empty or pd.isna(_r_fix.iloc[0]["sdac_price_PLN"]):
                                    _missing.append(f"H{_h:02d}Q{_q}(no F2)")
                                    continue
                                if _r_pse.empty or pd.isna(_r_pse.iloc[0]["cen_cost"]):
                                    _missing.append(f"H{_h:02d}Q{_q}(no CEN)")
                                    continue

                                _f2  = float(_r_fix.iloc[0]["sdac_price_PLN"])
                                _cen = float(_r_pse.iloc[0]["cen_cost"])
                                _spd = _f2 - _cen
                                _sign = 1 if t["direction"] == "Short" else -1
                                t["pnl"]       = round(_sign * _spd * t["volume_mw"], 2)
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
                    _rows.append({
                        "#":         _i,
                        "Date":      _t.get("fixing_date", ""),
                        "Slot":      _slot,
                        "MW":        _t.get("volume_mw", ""),
                        "Direction": _t.get("direction", "").capitalize(),
                        "Status":    "Priced" if _pnl is not None else "Open",
                        "P&L":       round(_pnl, 2) if _pnl is not None else None,
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
                    _rows.append({
                        "#":         _i,
                        "Date":      _fd,
                        "Hour":      f"H{_h:02d}",
                        "MW":        round(sum(_agg["volume_mw"]) / len(_agg["volume_mw"]), 2),
                        "Direction": _agg["direction"].capitalize(),
                        "Status":    _status,
                        "P&L":       _pnl_val,
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


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 4 — P&L DASHBOARD (FixTrade + TSOTrade combined)
# ══════════════════════════════════════════════════════════════════════════════
elif page == "P&L Dashboard":
    st.title("P&L Dashboard")

    closed_fix = [t for t in trades     if t.get("pnl") is not None]
    closed_tso = [t for t in tso_trades if t.get("pnl") is not None]

    if not closed_fix and not closed_tso:
        st.info("No closed trades yet.")
        st.stop()

    df_fix = pd.DataFrame(closed_fix) if closed_fix else pd.DataFrame(
        columns=["fixing_date","delivery_date","hour","direction","volume_mw","pnl"])
    df_tso = pd.DataFrame(closed_tso) if closed_tso else pd.DataFrame(
        columns=["fixing_date","delivery_date","hour","quarter","direction","volume_mw","pnl"])

    for _d in [df_fix, df_tso]:
        if not _d.empty:
            _d["fixing_date"]   = pd.to_datetime(_d["fixing_date"]).dt.date
            _d["delivery_date"] = pd.to_datetime(_d["delivery_date"]).dt.date

    fix_total = df_fix["pnl"].sum() if not df_fix.empty else 0.0
    tso_total = df_tso["pnl"].sum() if not df_tso.empty else 0.0
    combined  = fix_total + tso_total

    # All trades combined for win-rate calculation
    all_pnl = list(df_fix["pnl"]) + list(df_tso["pnl"])
    win_rate = sum(1 for p in all_pnl if p > 0) / len(all_pnl) * 100 if all_pnl else 0

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Total P&L (PLN)", f"{combined:,.0f}")
    k2.metric("FixTrade P&L",    f"{fix_total:,.0f}")
    k3.metric("TSOTrade P&L",    f"{tso_total:,.0f}")
    k4.metric("Trades", len(all_pnl))
    k5.metric("Win rate", f"{win_rate:.0f}%")

    st.caption("Fixing date = trading date (auction day) · Delivery date = next day (energy flows)")
    st.divider()

    # ── Daily and Monthly P&L bar charts ─────────────────────────────────
    import calendar as _cal

    MONTH_NAMES = {1:"Jan",2:"Feb",3:"Mar",4:"Apr",5:"May",6:"Jun",
                   7:"Jul",8:"Aug",9:"Sep",10:"Oct",11:"Nov",12:"Dec"}
    MONTH_FULL  = {1:"January",2:"February",3:"March",4:"April",5:"May",6:"June",
                   7:"July",8:"August",9:"September",10:"October",11:"November",12:"December"}

    # CSS: blue nav buttons with red triangle
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

    # ── Chart filters ─────────────────────────────────────────────────────────
    _cb1, _cb2, _ = st.columns([0.6, 0.6, 8.8])
    with _cb1:
        _show_fix = st.checkbox("Fix", value=True, key="pnl_show_fix")
    with _cb2:
        _show_tso = st.checkbox("TSO", value=True, key="pnl_show_tso")

    # Combined dataframe for the bar charts (filtered by checkboxes)
    _frames = []
    if not df_fix.empty and _show_fix:
        _frames.append(df_fix[["fixing_date","hour","delivery_date","direction","pnl"]].assign(segment="FixTrade"))
    if not df_tso.empty and _show_tso:
        _frames.append(df_tso[["fixing_date","hour","delivery_date","direction","pnl"]].assign(segment="TSOTrade"))
    df = pd.concat(_frames, ignore_index=True) if _frames else pd.DataFrame(
        columns=["fixing_date","hour","delivery_date","direction","pnl","segment"])

    if df.empty:
        st.info("No data to display — select at least one segment.")
        st.stop()

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

    # Full day range for selected month
    max_day = _cal.monthrange(sel_ym[0], sel_ym[1])[1]
    all_days = pd.DataFrame({"day": range(1, max_day + 1)})
    m_data = all_days.merge(
        daily_pnl[(daily_pnl["year"] == sel_ym[0]) & (daily_pnl["month"] == sel_ym[1])][["day","pnl"]],
        on="day", how="left"
    )
    m_total = m_data["pnl"].sum(skipna=True)

    # Full 12-month range for selected year
    all_months_df = pd.DataFrame({"month": range(1, 13)})
    y_data = all_months_df.merge(
        monthly_pnl[monthly_pnl["year"] == sel_yr][["month","pnl"]],
        on="month", how="left"
    )
    y_total = y_data["pnl"].sum(skipna=True)

    st.subheader("P&L by Delivery Date")
    chart_l, chart_r = st.columns(2)

    with chart_l:
        # Nav row: ◀  [April 2026]  ▶
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
        # P&L left-aligned below nav
        mc = "#2dc653" if m_total >= 0 else "#e63946"
        st.markdown(
            f"<p style='color:{mc};font-weight:600;font-size:1rem;margin:2px 0 6px 0;font-size:2rem'>"
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
        # Nav row: ◀  [2026]  ▶
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
        # P&L left-aligned below nav
        yc = "#2dc653" if y_total >= 0 else "#e63946"
        st.markdown(
            f"<p style='color:{yc};font-weight:600;font-size:1rem;margin:2px 0 6px 0;font-size:2rem'>"
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

    # ── By day (bottom) ───────────────────────────────────────────────────────
    st.divider()
    st.subheader("By day")
    _fix_by_date = df_fix.groupby("fixing_date")["pnl"].sum().to_dict() \
                   if not df_fix.empty else {}
    _tso_by_date = df_tso.groupby("fixing_date")["pnl"].sum().to_dict() \
                   if not df_tso.empty else {}
    _all_dates = sorted(
        set(_fix_by_date.keys()) | set(_tso_by_date.keys()), reverse=True)
    _daily_by_day = pd.DataFrame([
        {
            "Fixing date":   d,
            "Delivery date": (pd.Timestamp(d) + pd.Timedelta(days=1)).date(),
            "FixTrade":      round(_fix_by_date.get(d, 0), 0),
            "TSOTrade":      round(_tso_by_date.get(d, 0), 0),
            "Total":         round(_fix_by_date.get(d, 0) + _tso_by_date.get(d, 0), 0),
        }
        for d in _all_dates
    ])
    st.dataframe(_daily_by_day, use_container_width=True, hide_index=True)

    # ── List of Trades ────────────────────────────────────────────────────────
    st.divider()
    st.subheader("List of Trades")
    _lt_fix, _lt_tso = st.tabs(["FixTrade", "TSOTrade"])
    with _lt_fix:
        if not df_fix.empty:
            df_d = df_fix.copy()
            df_d["Hour"] = df_d["hour"].apply(lambda h: f"H{h:02d}")
            df_d = df_d.rename(columns={
                "fixing_date": "Fixing date", "delivery_date": "Delivery date",
                "direction": "Dir", "volume_mw": "MW",
                "f1_price": "F1", "sdac_price": "SDAC", "spread": "Spread", "pnl": "P&L"
            })
            cols = [c for c in ["Fixing date","Delivery date","Hour","Dir","MW","F1","SDAC","Spread","P&L"]
                    if c in df_d.columns]
            st.dataframe(df_d[cols].sort_values(["Fixing date","Hour"], ascending=False),
                         use_container_width=True, hide_index=True)
        else:
            st.info("No FixTrade history.")
    with _lt_tso:
        if not df_tso.empty:
            df_t = df_tso.copy()
            df_t["Slot"] = df_t.apply(
                lambda r: f"H{int(r['hour']):02d}Q{int(r['quarter'])}", axis=1)
            df_t = df_t.rename(columns={
                "fixing_date": "Fixing date", "delivery_date": "Delivery date",
                "direction": "Dir", "volume_mw": "MW",
                "f2_price": "F2", "cen_price": "CEN", "spread": "Spread", "pnl": "P&L"
            })
            cols = [c for c in ["Fixing date","Delivery date","Slot","Dir","MW","F2","CEN","Spread","P&L"]
                    if c in df_t.columns]
            st.dataframe(df_t[cols].sort_values(["Fixing date","Slot"], ascending=False),
                         use_container_width=True, hide_index=True)
        else:
            st.info("No TSOTrade history.")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 5 — HEATMAP
# ══════════════════════════════════════════════════════════════════════════════
elif page == "FixHeatmap":
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
            _root = os.path.dirname(__file__)
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
        "For each hour: % of days in the selected window where Buy F1 (F1 < SDAC) was the signal. "
        "Green = Buy F1 dominant · Red = Sell F1 dominant · 50% = no edge."
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

    bar_colors_prob = [
        "#2dc653" if b > 50 else ("#e63946" if b < 50 else "#cccccc")
        for b in prob_buy
    ]

    fig_prob = go.Figure()
    fig_prob.add_hline(y=50, line_dash="dash", line_color="#aaa", line_width=1)
    fig_prob.add_trace(go.Bar(
        x=hours,
        y=prob_buy,
        marker_color=bar_colors_prob,
        customdata=list(zip(prob_buy, prob_sell, total_days_h)),
        hovertemplate=(
            "<b>H%{x:02d}</b><br>"
            "Buy F1:  %{customdata[0]:.1f}%<br>"
            "Sell F1: %{customdata[1]:.1f}%<br>"
            "Days: %{customdata[2]}<extra></extra>"
        ),
        text=[f"{v:.0f}%" for v in prob_buy],
        textposition="outside",
        textfont=dict(size=10),
    ))
    fig_prob.update_layout(
        **CHART_THEME,
        xaxis=dict(title="Hour", tickmode="linear", dtick=1,
                   range=[0.5, 24.5], gridcolor="#eee", linecolor="#ccc"),
        yaxis=dict(title="Buy F1 probability (%)", range=[0, 115],
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

    w_prob_buy = []
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
        w_prob_buy.append(round(_numerator / _denominator * 100, 1)
                          if _denominator > 0 else 0.0)

    _bar_colors_w = [
        "#2dc653" if p > 50 else ("#e63946" if p < 50 else "#cccccc")
        for p in w_prob_buy
    ]

    fig_w = go.Figure()
    fig_w.add_hline(y=50, line_dash="dash", line_color="#aaa", line_width=1)

    # Faint reference bars from unweighted chart
    fig_w.add_trace(go.Bar(
        x=hours, y=prob_buy,
        marker_color="rgba(180,180,180,0.35)",
        name="Unweighted (ref)",
        hoverinfo="skip",
    ))
    # Weighted bars
    fig_w.add_trace(go.Bar(
        x=hours, y=w_prob_buy,
        marker_color=_bar_colors_w,
        name="Weighted",
        customdata=w_prob_buy,
        hovertemplate="<b>H%{x:02d}</b><br>Weighted Buy F1: %{customdata:.1f}%<extra></extra>",
        text=[f"{v:.0f}%" for v in w_prob_buy],
        textposition="outside",
        textfont=dict(size=10),
    ))
    fig_w.update_layout(
        **CHART_THEME,
        barmode="overlay",
        xaxis=dict(title="Hour", tickmode="linear", dtick=1,
                   range=[0.5, 24.5], gridcolor="#eee", linecolor="#ccc"),
        yaxis=dict(title="Weighted Buy F1 probability (%)", range=[0, 115],
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

A bar above 50% (green) means Buy F1 has been the dominant signal in the window,
with recent days counted more heavily. A bar below 50% (red) means Sell F1 dominates.
The faint grey bars show the unweighted result for comparison.
""")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 5b — TSO HEATMAP
# ══════════════════════════════════════════════════════════════════════════════
elif page == "TSOHeatmap":
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
    cen_h  = rb_h_df[["delivery_date", "H", "cen_price_PLN"]].dropna(subset=["cen_price_PLN"])

    hm_tso = sdac_h.merge(cen_h, on=["delivery_date", "H"], how="inner")
    hm_tso = hm_tso.rename(columns={"sdac_price_PLN": "sdac", "cen_price_PLN": "cen"})
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
            _root = os.path.dirname(__file__)
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
        "For each hour: % of days where Long SDAC (SDAC < CEN) was the signal. "
        "Green = Long SDAC dominant · Red = Short SDAC dominant · 50% = no edge."
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

    _bar_colors_tso = [
        "#2dc653" if p > 50 else ("#e63946" if p < 50 else "#cccccc")
        for p in tso_prob_long
    ]

    fig_tso_prob = go.Figure()
    fig_tso_prob.add_hline(y=50, line_dash="dash", line_color="#aaa", line_width=1)
    fig_tso_prob.add_trace(go.Bar(
        x=hours,
        y=tso_prob_long,
        marker_color=_bar_colors_tso,
        customdata=list(zip(tso_prob_long, tso_prob_short, tso_total_h)),
        hovertemplate=(
            "<b>H%{x:02d}</b><br>"
            "Long SDAC:  %{customdata[0]:.1f}%<br>"
            "Short SDAC: %{customdata[1]:.1f}%<br>"
            "Days: %{customdata[2]}<extra></extra>"
        ),
        text=[f"{v:.0f}%" for v in tso_prob_long],
        textposition="outside",
        textfont=dict(size=10),
    ))
    fig_tso_prob.update_layout(
        **CHART_THEME,
        xaxis=dict(title="Hour", tickmode="linear", dtick=1,
                   range=[0.5, 24.5], gridcolor="#eee", linecolor="#ccc"),
        yaxis=dict(title="Long SDAC probability (%)", range=[0, 115],
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
    w_prob_long_tso = []
    for h in hours:
        _num, _den = 0.0, 0.0
        for _k, _d in enumerate(_tso_dates_ord):
            _w = tso_lam ** (_tso_n_used - 1 - _k)
            _c = hm_tso[(hm_tso["delivery_date"] == _d) & (hm_tso["H"] == h)]["spread"]
            if _c.empty or pd.isna(_c.iloc[0]):
                continue
            _num += _w * (1.0 if _c.iloc[0] < 0 else 0.0)
            _den += _w
        w_prob_long_tso.append(round(_num / _den * 100, 1) if _den > 0 else 0.0)

    _bar_colors_tw = [
        "#2dc653" if p > 50 else ("#e63946" if p < 50 else "#cccccc")
        for p in w_prob_long_tso
    ]

    fig_tw = go.Figure()
    fig_tw.add_hline(y=50, line_dash="dash", line_color="#aaa", line_width=1)
    fig_tw.add_trace(go.Bar(
        x=hours, y=tso_prob_long,
        marker_color="rgba(180,180,180,0.35)",
        name="Unweighted (ref)",
        hoverinfo="skip",
    ))
    fig_tw.add_trace(go.Bar(
        x=hours, y=w_prob_long_tso,
        marker_color=_bar_colors_tw,
        name="Weighted",
        customdata=w_prob_long_tso,
        hovertemplate="<b>H%{x:02d}</b><br>Weighted Long SDAC: %{customdata:.1f}%<extra></extra>",
        text=[f"{v:.0f}%" for v in w_prob_long_tso],
        textposition="outside",
        textfont=dict(size=10),
    ))
    fig_tw.update_layout(
        **CHART_THEME,
        barmode="overlay",
        xaxis=dict(title="Hour", tickmode="linear", dtick=1,
                   range=[0.5, 24.5], gridcolor="#eee", linecolor="#ccc"),
        yaxis=dict(title="Weighted Long SDAC probability (%)", range=[0, 115],
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

A bar above 50% (green) means Long SDAC has been the dominant signal in the window,
with recent days counted more heavily. A bar below 50% (red) means Short SDAC dominates.
The faint grey bars show the unweighted result for comparison.
""")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 5 — PARQUET
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Parquet":
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


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 6 — PSE
# ══════════════════════════════════════════════════════════════════════════════
elif page == "PSE":
    st.title("PSE Market Data")

    pse_df = load_pse()

    # ── Monthly CEN coverage calendar ─────────────────────────────────────────
    import calendar as _cal
    _today   = date.today()
    _yr, _mo = _today.year, _today.month
    _days_in_month = _cal.monthrange(_yr, _mo)[1]
    _MONTHS_PL = ["Styczeń","Luty","Marzec","Kwiecień","Maj","Czerwiec",
                  "Lipiec","Sierpień","Wrzesień","Październik","Listopad","Grudzień"]
    _month_name = _MONTHS_PL[_mo - 1]

    # Days that have at least one row with non-null CEN price
    if not pse_df.empty and "cen_cost" in pse_df.columns:
        _cen_df = pse_df[
            (pse_df["cen_cost"].notna()) &
            (pd.to_datetime(pse_df["business_date"]).dt.year  == _yr) &
            (pd.to_datetime(pse_df["business_date"]).dt.month == _mo)
        ]
        _days_with_data = set(pd.to_datetime(_cen_df["business_date"]).dt.day.unique())
    else:
        _days_with_data = set()

    _cells = ""
    for _d in range(1, _days_in_month + 1):
        _bg    = "#e63946" if _d in _days_with_data else "#f0f0f0"
        _color = "#ffffff" if _d in _days_with_data else "#aaaaaa"
        _cells += (
            f'<td style="background:{_bg};color:{_color};'
            f'width:28px;height:28px;text-align:center;vertical-align:middle;'
            f'font-size:11px;font-weight:600;border-radius:4px;border:1px solid #ddd;">'
            f'{_d}</td>'
        )

    _html_cal = f"""
    <div style="margin-bottom:16px;">
      <div style="font-size:13px;font-weight:600;color:#555;margin-bottom:6px;">
        {_month_name} {_yr} &nbsp;–&nbsp; CEN coverage
        &nbsp;<span style="font-size:11px;font-weight:400;color:#888;">
        ({len(_days_with_data)}/{_days_in_month} days)</span>
      </div>
      <table style="border-collapse:separate;border-spacing:3px;"><tr>{_cells}</tr></table>
    </div>
    """
    st.markdown(_html_cal, unsafe_allow_html=True)

    if pse_df.empty:
        st.warning("No PSE data available. Run the PSE prices pipeline first.")
        st.stop()

    # ── Controls ──────────────────────────────────────────────────────────────
    available_pse_dates = sorted(pse_df["business_date"].unique())   # ascending

    if "pse_date" not in st.session_state:
        st.session_state.pse_date = available_pse_dates[-1]
    if st.session_state.pse_date not in available_pse_dates:
        st.session_state.pse_date = available_pse_dates[-1]

    def pse_prev():
        idx = available_pse_dates.index(st.session_state.pse_date)
        if idx > 0:
            st.session_state.pse_date = available_pse_dates[idx - 1]

    def pse_next():
        idx = available_pse_dates.index(st.session_state.pse_date)
        if idx < len(available_pse_dates) - 1:
            st.session_state.pse_date = available_pse_dates[idx + 1]

    nav = st.columns([0.07, 0.22, 0.07, 0.64, 0.30, 0.30])
    with nav[0]:
        st.button("◀", on_click=pse_prev, use_container_width=True, key="pse_prev")
    with nav[1]:
        picked_pse = st.date_input(
            "Date",
            value=st.session_state.pse_date,
            min_value=available_pse_dates[0],
            max_value=available_pse_dates[-1],
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
        use_bars     = st.checkbox("Bars",    value=True)

    sel_pse_date = st.session_state.pse_date

    # ── Filter ────────────────────────────────────────────────────────────────
    day_pse = pse_df[pse_df["business_date"] == sel_pse_date].copy()
    day_pse = day_pse.sort_values("dtime")

    if day_pse.empty:
        st.warning("No data for selected date.")
        st.stop()

    # ── Granularity aggregation ───────────────────────────────────────────────
    if granularity == "Hourly":
        day_pse["hour_num"] = (
            (day_pse["dtime"].dt.hour * 60 + day_pse["dtime"].dt.minute - 1) // 60 + 1
        )
        day_agg = (
            day_pse.groupby("hour_num")
            .agg(
                cen_cost    =("cen_cost",     "mean"),
                ceb_pp_cost =("ceb_pp_cost",  "mean"),
                cor_cost    =("cor_cost",     "mean"),
                sk_cost     =("sk_cost",      "mean"),
                balance     =("balance",      "mean"),
            )
            .reset_index()
            .sort_values("hour_num")
        )
        x_vals  = day_agg["hour_num"].tolist()
        x_axis  = dict(title="Hour", tickmode="linear", dtick=1,
                       range=[0.5, 24.5], gridcolor="#eee", linecolor="#ccc")
        cen  = day_agg["cen_cost"].tolist()
        ceb  = day_agg["ceb_pp_cost"].tolist()
        cor  = day_agg["cor_cost"].tolist()
        sk   = day_agg["sk_cost"].tolist()
        bal  = day_agg["balance"].tolist()
        hover_x  = [f"H{h:02d}" for h in x_vals]
        tbl_time = [f"H{h:02d}" for h in x_vals]
        tbl_date = [str(sel_pse_date)] * len(x_vals)
    else:
        x_vals  = day_pse["dtime"].tolist()
        x_axis  = dict(title="Time (Warsaw)", gridcolor="#eee", linecolor="#ccc",
                       tickformat="%H:%M")
        cen  = day_pse["cen_cost"].tolist()
        ceb  = day_pse["ceb_pp_cost"].tolist()
        cor  = day_pse["cor_cost"].tolist()
        sk   = day_pse["sk_cost"].tolist()
        bal  = day_pse["balance"].tolist()
        hover_x  = day_pse["dtime"].dt.strftime("%H:%M").tolist()
        tbl_time = day_pse["period"].tolist()
        tbl_date = [str(sel_pse_date)] * len(x_vals)

    # ── Build chart ───────────────────────────────────────────────────────────
    fig = go.Figure()

    if show_balance:
        bal_colors = [
            "rgba(30,100,200,0.35)" if b >= 0 else "rgba(200,50,50,0.35)"
            for b in bal
        ]
        fig.add_trace(go.Bar(
            x=x_vals, y=bal, name="Balance (MW)",
            marker_color=bal_colors, yaxis="y2",
            hovertemplate="%{customdata}  Balance: %{y:.1f} MW<extra></extra>",
            customdata=hover_x,
        ))

    def _trace(x, y, name, color, hover_x):
        kw = dict(x=x, y=y, name=name, customdata=hover_x,
                  hovertemplate=f"%{{customdata}}  {name}: %{{y:.2f}} PLN/MWh<extra></extra>")
        if use_bars:
            return go.Bar(**kw, marker_color=color)
        else:
            return go.Scatter(**kw, mode="lines+markers",
                              line=dict(color=color, width=2),
                              marker=dict(size=4, color=color))

    fig.add_trace(_trace(x_vals, cen, "CEN",   "#1565c0", hover_x))
    # CKOEB and COR hidden by default — click legend to enable
    t_ceb = _trace(x_vals, ceb, "CKOEB", "#2dc653", hover_x)
    t_ceb.visible = "legendonly"
    fig.add_trace(t_ceb)
    t_cor = _trace(x_vals, cor, "COR", "#29b6f6", hover_x)
    t_cor.visible = "legendonly"
    fig.add_trace(t_cor)

    layout = dict(
        **CHART_THEME,
        title=f"PSE Market Data — {sel_pse_date}",
        xaxis=x_axis,
        yaxis=dict(title="Price (PLN/MWh)", gridcolor="#eee", linecolor="#ccc"),
        legend=dict(
            orientation="v", x=1.02, y=1, xanchor="left",
            bgcolor="white", bordercolor="#ddd", borderwidth=1,
            font=dict(size=12),
        ),
        height=500, margin=dict(t=60, b=60, r=160),
        hovermode="x unified",
        barmode="group",
    )
    if show_balance:
        layout["yaxis2"] = dict(
            title="Balance (MW)", overlaying="y", side="right",
            showgrid=False, zeroline=True, zerolinecolor="#aaa",
        )
    fig.update_layout(**layout)
    st.plotly_chart(fig, use_container_width=True)

    # ── Metrics ───────────────────────────────────────────────────────────────
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("CEN avg",  f"{pd.Series(cen).mean():.2f}")
    m2.metric("CEN max",  f"{pd.Series(cen).max():.2f}")
    m3.metric("CKOEB avg",f"{pd.Series(ceb).mean():.2f}")
    m4.metric("CKOEB max",f"{pd.Series(ceb).max():.2f}")
    m5.metric("Bal avg",  f"{pd.Series(bal).mean():.1f} MW")
    m6.metric("Quarters", str(len(day_pse)))

    # ── Price table ───────────────────────────────────────────────────────────
    st.divider()
    st.subheader("Price Table")

    df_tbl = pd.DataFrame({
        "Date":  tbl_date,
        "Time":  tbl_time,
        "CEN":   [round(v, 2) for v in cen],
        "CKOEB": [round(v, 2) for v in ceb],
        "SK":    [round(v, 2) for v in sk],
        "COR":   [round(v, 2) for v in cor],
    })
    tbl_col, _ = st.columns([0.45, 0.55])
    with tbl_col:
        st.dataframe(df_tbl, use_container_width=True, hide_index=True, height=400)

    # ── Update button + PSE link ──────────────────────────────────────────────
    st.divider()
    st.markdown("""
    <style>
    div[data-testid="stButton"].pse-update-btn > button {
        background-color: #2dc653 !important;
        color: white !important;
        border: none !important;
    }
    div[data-testid="stButton"].pse-update-btn > button:hover {
        background-color: #25a244 !important;
    }
    </style>
    """, unsafe_allow_html=True)
    _pse_date_str = sel_pse_date.strftime("%Y-%m-%d")
    _pse_url = (
        f"https://raporty.pse.pl/report/bpci-energy-and-prices"
        f"?chart=true&bpciDataType=FCST&dateFrom={_pse_date_str}&dateTo={_pse_date_str}"
    )
    btn_col, link_col = st.columns([1, 3])
    with btn_col:
        st.markdown('<div class="pse-update-btn">', unsafe_allow_html=True)
        _update_clicked = st.button("Update PSE Prices", use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)
    with link_col:
        st.markdown(
            f'<br><a href="{_pse_url}" target="_blank">'
            f'Open PSE portal for {_pse_date_str} ↗</a>',
            unsafe_allow_html=True,
        )
    if _update_clicked:
        import importlib.util as _ilu
        _spec = _ilu.spec_from_file_location(
            "pse_prices",
            os.path.join(os.path.dirname(__file__), "procedures", "pse_prices.py")
        )
        _pse_mod = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_pse_mod)
        lines = []
        with st.spinner("Downloading PSE prices..."):
            result = _pse_mod.run_pipeline(
                app_dir=os.path.dirname(__file__),
                log=lambda m: lines.append(m),
            )
        load_pse.clear()
        if result.get("status") == "ok":
            st.success(result.get("message", "Done."))
        else:
            st.error(result.get("message", "Something went wrong."))
        with st.expander("Pipeline log"):
            st.text("\n".join(lines))
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# PAGE — German SPOT
# ══════════════════════════════════════════════════════════════════════════════
elif page == "German SPOT":

    st.title("German SPOT — EPEX Day-Ahead")

    _de    = load_de_prices()
    _fx_de = load_eurpln()

    if _de.empty:
        st.warning("No DE Spot data. Run the DE Prices pipeline from the Admin page.")
        st.stop()

    _eurpln_de = float(_fx_de["rate"].iloc[-1]) if not _fx_de.empty else 4.28
    _fx_dt_de  = _fx_de["date"].iloc[-1]        if not _fx_de.empty else "—"

    # ── Controls ──────────────────────────────────────────────────────────────
    _avail_de = sorted(_de["business_date"].unique())

    if "de_date" not in st.session_state:
        st.session_state.de_date = _avail_de[-1]
    if st.session_state.de_date not in _avail_de:
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
            label_visibility="collapsed", key="de_date_input",
        )
        if _picked_de != st.session_state.de_date:
            st.session_state.de_date = _picked_de
    with _nav[2]:
        st.button("▶", on_click=_de_next, use_container_width=True, key="de_next")
    with _nav[3]:
        st.markdown(
            f"<div style='padding-top:8px;font-size:0.85rem;color:#555;'>"
            f"EUR/PLN: <b>{_eurpln_de:.4f}</b></div>",
            unsafe_allow_html=True,
        )
    with _nav[4]:
        _use_pln = st.checkbox("PLN", value=False, key="de_pln")

    _currency    = "PLN/MWh" if _use_pln else "EUR/MWh"
    _mult        = _eurpln_de if _use_pln else 1.0
    _sel_de_date = st.session_state.de_date

    _day_de = _de[_de["business_date"] == _sel_de_date].copy().sort_values("hour")

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
    _bar_colors = ["#2dc653" if p >= 0 else "#e63946" for p in _prices]
    _fig_de.add_trace(go.Bar(
        x=_x_vals, y=_prices,
        marker_color=_bar_colors,
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

    # ── Update button ─────────────────────────────────────────────────────────
    st.divider()
    if st.button("Update DE Prices", key="de_update_btn"):
        import importlib.util as _ilu_de
        def _load_mod_de(path, name):
            spec = _ilu_de.spec_from_file_location(name, path)
            mod  = _ilu_de.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
        _root_de = os.path.dirname(__file__)
        _de_mod  = _load_mod_de(os.path.join(_root_de, "energy_charts", "de_prices.py"), "de_prices")
        _lines_de = []
        with st.spinner("Updating DE prices..."):
            _r_de = _de_mod.run_pipeline(app_dir=_root_de, log=lambda m: _lines_de.append(m))
        load_de_prices.clear()
        st.success(f"Done — {_r_de.get('new_rows', 0)} new rows.")
        with st.expander("Pipeline log"):
            st.text("\n".join(_lines_de))
        st.rerun()

    # ── Footer ────────────────────────────────────────────────────────────────
    st.divider()
    _de_last = _de["business_date"].max()
    st.markdown(
        f"<div style='font-size:0.85rem;color:#666;line-height:1.8'>"
        f"<b>Source:</b> <a href='https://www.electricitymaps.com' target='_blank'>Electricity Maps</a> "
        f"— EPEX SPOT Day-Ahead prices, Germany (DE) bidding zone<br>"
        f"<b>Unit:</b> EUR/MWh &nbsp;·&nbsp; <b>Times:</b> CET (hours 1–24) &nbsp;·&nbsp; "
        f"<b>Granularity:</b> hourly<br>"
        f"<b>Update frequency:</b> Daily at ~04:00 CET (previous day's data)<br>"
        f"<b>Last data point:</b> {_de_last}"
        f"</div>",
        unsafe_allow_html=True,
    )

# ══════════════════════════════════════════════════════════════════════════════
# PAGE 8 — PK5  (5-day coordination plan: load, wind, PV)
# ══════════════════════════════════════════════════════════════════════════════
elif page == "PK5":
    st.title("Daily KSE Situation")

    # ── Update button (top) ────────────────────────────────────────────────────
    _pk5_top_c1, _pk5_top_c2 = st.columns([1, 4])
    with _pk5_top_c1:
        if st.button("Update PK5", key="pk5_update_top"):
            import importlib.util as _ilu_pk5t
            _spec_t = _ilu_pk5t.spec_from_file_location(
                "pk5_pipeline",
                os.path.join(os.path.dirname(__file__), "procedures", "pk5_pipeline.py")
            )
            _mod_t = _ilu_pk5t.module_from_spec(_spec_t)
            _spec_t.loader.exec_module(_mod_t)
            _lines_t = []
            with st.spinner("Downloading PK5 data..."):
                _result_t = _mod_t.run_pipeline(
                    app_dir=os.path.dirname(__file__),
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

        # Default to latest historical date, not last forecast
        _latest_h = max(
            (d for d in available_pk5
             if pk5_df.loc[pk5_df["business_date"] == d, "data_type"].iloc[0] == "H"),
            default=available_pk5[-1]
        )
        if "pk5_date" not in st.session_state:
            st.session_state.pk5_date = _latest_h
        if st.session_state.pk5_date not in available_pk5:
            st.session_state.pk5_date = _latest_h

        def pk5_prev():
            idx = available_pk5.index(st.session_state.pk5_date)
            if idx > 0:
                st.session_state.pk5_date = available_pk5[idx - 1]

        def pk5_next():
            idx = available_pk5.index(st.session_state.pk5_date)
            if idx < len(available_pk5) - 1:
                st.session_state.pk5_date = available_pk5[idx + 1]

        nav = st.columns([0.07, 0.22, 0.07, 0.64])
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

        sel_pk5 = st.session_state.pk5_date
        day_pk5 = pk5_df[pk5_df["business_date"] == sel_pk5].sort_values("plan_dtime")

        # data_type label
        _dtype = day_pk5["data_type"].iloc[0] if "data_type" in day_pk5.columns else "?"
        _dtype_label = "Forecast" if _dtype == "F" else "Historical"
        with nav[3]:
            st.markdown(
                f"<div style='padding-top:10px;color:{'#e65100' if _dtype=='F' else '#1565c0'};"
                f"font-weight:600'>{_dtype_label}</div>",
                unsafe_allow_html=True,
            )

        if day_pk5.empty:
            st.warning("No data for selected date.")
        else:
            hours       = list(range(1, len(day_pk5) + 1))
            total_load  = day_pk5["grid_demand_fcst"].tolist()
            wind        = day_pk5["fcst_wi_tot_gen"].tolist()
            pv          = day_pk5["fcst_pv_tot_gen"].tolist()
            # pred_gen_res_not_cov = PSE's own residual: demand not covered by RES
            # (grid_demand_fcst already excludes prosumer self-consumption, so
            #  computing grid_demand - wind - pv would double-subtract prosumer PV)
            residual    = day_pk5["pred_gen_res_not_cov"].tolist() \
                          if "pred_gen_res_not_cov" in day_pk5.columns else []
            hour_labels = [f"H{h:02d}" for h in hours]

            # ── Metrics ───────────────────────────────────────────────────────
            _wind_clean = [v for v in wind if v is not None and not pd.isna(v)]
            _pv_clean   = [v for v in pv   if v is not None and not pd.isna(v)]
            _load_clean = [v for v in total_load if v is not None and not pd.isna(v)]
            _res_clean  = [v for v in residual   if v is not None and not pd.isna(v)]
            _load_sum   = sum(_load_clean) if _load_clean else 0
            _wind_share = sum(_wind_clean) / _load_sum * 100 if _load_sum else 0
            _pv_share   = sum(_pv_clean)   / _load_sum * 100 if _load_sum else 0

            mc1, mc2, mc3, mc4, mc5 = st.columns(5)
            mc1.metric("Grid Demand",       f"{max(_load_clean):,.0f} MW" if _load_clean else "—")
            mc2.metric("Min Residual",      f"{min(_res_clean):,.0f} MW"  if _res_clean  else "—")
            mc3.metric("Peak Wind",    f"{max(_wind_clean):,.0f} MW" if _wind_clean else "—")
            mc4.metric("Peak PV",      f"{max(_pv_clean):,.0f} MW"   if _pv_clean   else "—")
            mc5.metric("RES / Grid",   f"{_wind_share + _pv_share:.1f}%")

            # ── Chart ─────────────────────────────────────────────────────────
            fig = go.Figure()

            # Stacked bars: Wind (blue) + PV (yellow)
            fig.add_trace(go.Bar(
                x=hours, y=wind, name="Wind",
                marker_color="#1565c0",
                hovertemplate="%{customdata}  Wind: %{y:,.0f} MW<extra></extra>",
                customdata=hour_labels,
            ))
            fig.add_trace(go.Bar(
                x=hours, y=pv, name="PV (incl. prosumers)",
                marker_color="#fdd835",
                hovertemplate="%{customdata}  PV: %{y:,.0f} MW<extra></extra>",
                customdata=hour_labels,
            ))

            # Line: Grid Demand (zapotrzebowanie sieci — net of prosumer self-consumption)
            fig.add_trace(go.Scatter(
                x=hours, y=total_load, name="Grid Demand",
                mode="lines", line=dict(color="#212121", width=2.5),
                hovertemplate="%{customdata}  Grid Demand: %{y:,.0f} MW<extra></extra>",
                customdata=hour_labels,
            ))
            # Line: Residual (pred_gen_res_not_cov — PSE's own calc, what conventional plants cover)
            if residual:
                fig.add_trace(go.Scatter(
                    x=hours, y=residual, name="Residual (conv. units)",
                    mode="lines", line=dict(color="#e63946", width=2, dash="dash"),
                    hovertemplate="%{customdata}  Residual: %{y:,.0f} MW<extra></extra>",
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
                "**Grid Demand** (zapotrzebowanie sieci) = transmission grid demand, already net of "
                "prosumer self-consumption. **PV incl. prosumers** = total national PV generation. "
                "Gross KSE consumption ≈ Grid Demand + prosumer self-consumed PV (~4-8 GW at midday). "
                "**Residual** = PSE's own estimate of demand to be covered by conventional units."
            )

    # ── Last updated info ──────────────────────────────────────────────────────
    if not pk5_df.empty and "snapshot_date" in pk5_df.columns:
        _pk5_last_snap = pd.to_datetime(pk5_df["snapshot_date"]).max().date()
        st.caption(f"The page was updated on: **{_pk5_last_snap}**")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 9 — ETS CO2
# ══════════════════════════════════════════════════════════════════════════════
elif page == "ETS1":
    st.title("ETS CO2")
    st.caption("ICE EU Allowances futures — settlement prices (EUR/tCO₂)")

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
            _tbl = ets_filtered.copy().sort_values(["date", "symbol"], ascending=[False, True])
            _tbl["date"]       = _tbl["date"].astype(str)
            _tbl["settlement"] = _tbl["settlement"].round(2)
            for _col in ["open", "high", "low"]:
                if _col in _tbl.columns:
                    _tbl[_col] = pd.to_numeric(_tbl[_col], errors="coerce").round(2)
            _tbl = _tbl.rename(columns={
                "date": "Date", "symbol": "Symbol", "contract": "Contract",
                "open": "Open", "high": "High", "low": "Low",
                "settlement": "Settlement", "volume": "Volume",
            })
            _show_cols = [c for c in ["Date","Symbol","Contract","Open","High","Low","Settlement","Volume"]
                          if c in _tbl.columns]
            st.dataframe(_tbl[_show_cols], use_container_width=True, hide_index=True)

    else:
        st.info("No ETS data yet. Press **Update ETS** below to fetch today's prices.")

    # ── Update button ─────────────────────────────────────────────────────────
    st.divider()
    if st.button("Update ETS", key="ets_update"):
        import importlib.util as _ilu
        _spec = _ilu.spec_from_file_location(
            "ets_co2",
            os.path.join(os.path.dirname(__file__), "prices", "ets_co2.py")
        )
        _mod = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        _lines = []
        with st.spinner("Fetching ETS prices..."):
            _result = _mod.run_pipeline(
                app_dir=os.path.dirname(__file__),
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

# ══════════════════════════════════════════════════════════════════════════════
# PAGE — Coal (PSCMI 1)
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Coal":
    st.title("PSCMI 1 — Polski Indeks Rynku Węgla")
    st.caption("Miesięczny indeks cen węgla energetycznego na rynku krajowym (PLN/T i PLN/GJ)")

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

        # ── Chart ─────────────────────────────────────────────────────────────
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=_cf["date"].tolist(), y=_cf["pscmi_t"].tolist(),
            mode="lines", name="PSCMI 1/T (PLN/T)",
            line=dict(color="#1565c0", width=2.5),
            hovertemplate="%{x|%m.%Y}  <b>%{y:.2f} PLN/T</b><extra></extra>",
        ))
        fig.update_layout(
            **CHART_THEME,
            title="PSCMI 1 — cena węgla energetycznego",
            xaxis=dict(title="", gridcolor="#eee"),
            yaxis=dict(title="PLN/T", gridcolor="#eee"),
            height=420, margin=dict(t=60, b=40, l=60, r=20),
            hovermode="x unified",
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

    # ── Upload new CSV ────────────────────────────────────────────────────────
    st.divider()
    st.subheader("Aktualizacja danych")
    st.caption("Pobierz CSV z polskirynekwegla.pl (wykres nr 1, miesięczny) i wgraj poniżej.")
    _uploaded = st.file_uploader("Wybierz plik CSV", type=["csv"], key="coal_upload")
    if _uploaded is not None:
        try:
            import io as _io
            _raw = pd.read_csv(_io.BytesIO(_uploaded.read()), sep=None, engine="python")
            _raw = _raw.set_index(_raw.columns[0]).T
            _raw.index.name = "month"
            _raw.columns = ["pscmi_t", "pscmi_q"]

            def _parse_month(s):
                m, y = s.split(".")
                return date(int(y), int(m), 1)

            _raw.index = _raw.index.map(_parse_month)
            _raw = _raw.reset_index().rename(columns={"month": "date"})
            _raw["pscmi_t"] = pd.to_numeric(_raw["pscmi_t"], errors="coerce")
            _raw["pscmi_q"] = pd.to_numeric(_raw["pscmi_q"], errors="coerce")
            _raw = _raw.dropna(subset=["pscmi_t"]).sort_values("date").reset_index(drop=True)

            # Merge with existing
            if not coal_df.empty:
                _merged = (
                    pd.concat([coal_df, _raw], ignore_index=True)
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

# ══════════════════════════════════════════════════════════════════════════════
# PAGE — OTF / EE
# ══════════════════════════════════════════════════════════════════════════════
elif page == "OTF / EE":
    st.title("OTF / EE")
    st.caption("TGE OTF — settlement price (DKR) and volume by contract")

    _ee = load_otf_ee()

    if _ee.empty:
        st.warning("No EE data. Run the TGE OTF EE pipeline first.")
        if st.button("Update EE data", type="primary"):
            import sys as _sys
            _sys.path.insert(0, os.path.join(os.path.dirname(__file__), "procedures"))
            from tge_otf_ee import run_pipeline as _ee_pipeline
            _lines = []
            with st.spinner("Downloading from TGE..."):
                _result = _ee_pipeline(app_dir=os.path.dirname(__file__),
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
        _now = pd.Timestamp.now()
        for _part in str(pname).split("-"):
            _mm = _re2.match(r"M(\d{1,2})$", _part)
            if _mm:
                return int(_mm.group(1)) < _now.month
            _qq = _re2.match(r"Q(\d)$", _part)
            if _qq:
                return int(_qq.group(1)) < ((_now.month - 1) // 3 + 1)
        return False

    _ee["_del_year"] = _ee["product_name"].apply(_ee_parse_year)
    _ee_yr_filt = _ee[_ee["_del_year"] == _ee_del_year]
    if _ee_hide_exp and _ee_del_year == _cur_yr_ee:
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
        _ee_seg_sel  = st.multiselect("Segment", options=_ee_segments,
                                       default=_ee_segments, key="ee_segment")

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
        _sys.path.insert(0, os.path.join(os.path.dirname(__file__), "procedures"))
        from tge_otf_ee import run_pipeline as _ee_pipeline
        _lines = []
        with st.spinner("Downloading from TGE..."):
            _result = _ee_pipeline(app_dir=os.path.dirname(__file__),
                                   log=lambda m: _lines.append(m))
        load_otf_ee.clear()
        if _result["status"] == "ok":
            st.success(_result["message"])
        else:
            st.error(_result["message"])
        with st.expander("Pipeline log"):
            st.text("\n".join(_lines))
        st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# PAGE — CurrentCDS
# ══════════════════════════════════════════════════════════════════════════════
elif page == "CurrentCDS":
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

# ══════════════════════════════════════════════════════════════════════════════
# PAGE — CurrentCCS
# ══════════════════════════════════════════════════════════════════════════════
elif page == "CurrentCCS":
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

# ══════════════════════════════════════════════════════════════════════════════
# PAGE — OTF / Gas
# ══════════════════════════════════════════════════════════════════════════════
elif page == "OTF / Gas":
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

# ══════════════════════════════════════════════════════════════════════════════
# PAGE — Compare
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Compare":
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

# ══════════════════════════════════════════════════════════════════════════════
# PAGE — Liquidity
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Liquidity":
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

# ══════════════════════════════════════════════════════════════════════════════
# PAGE — LOGS
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Logs":
    st.title("Logs")

    _logs_dir = os.path.join(os.path.dirname(__file__), "logs")

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


# ══════════════════════════════════════════════════════════════════════════════
# PAGE — CDS
# ══════════════════════════════════════════════════════════════════════════════
elif page == "CDS":
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

# ══════════════════════════════════════════════════════════════════════════════
# PAGE — CCS
# ══════════════════════════════════════════════════════════════════════════════
elif page == "CCS":
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

# ══════════════════════════════════════════════════════════════════════════════
# ADMIN — PK5 Snapshots
# ══════════════════════════════════════════════════════════════════════════════
elif page == "PK5_Snapshots":
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


# ══════════════════════════════════════════════════════════════════════════════
# TSO — PowerDemand
# ══════════════════════════════════════════════════════════════════════════════
elif page == "PowerDemand":
    st.title("KSE Power Demand")
    st.caption("Actual vs forecast KSE demand — 15-min resolution, aggregated to hourly.")

    _pd_root = os.path.dirname(__file__)
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


# ══════════════════════════════════════════════════════════════════════════════
# PAGE — ADMIN
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Admin":
    st.title("Admin — Data Pipelines")
    st.caption("Run pipelines manually, view last available data date per source.")

    import importlib.util as _ilu_adm

    _root_adm = os.path.dirname(__file__)

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
            _m = _load_mod_adm(os.path.join(_root_adm, "prices", "de_spot.py"), "de_spot")
            _adm_result = _m.run_pipeline(app_dir=_root_adm, log=_adm_log)
            load_de_spot.clear()

        elif _run_key == "ets_co2":
            _m = _load_mod_adm(os.path.join(_root_adm, "prices", "ets_co2.py"), "ets_co2")
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

        if _adm_result:
            if _adm_result.get("status") == "ok":
                st.success(_adm_result.get("message", "Done."))
            else:
                st.error(_adm_result.get("message", "Pipeline returned an error."))


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN — PSE_Viewer
# ══════════════════════════════════════════════════════════════════════════════
elif page == "PSE_Viewer":
    import importlib.util as _ilu_rb, sys as _sys_rb

    _rb_root = os.path.dirname(__file__)
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
        ].sort_values(["delivery_date", "H"], ascending=[False, True])

        st.caption(f"{len(_h_view):,} rows · {_h_view['delivery_date'].nunique()} days")

        def _color_cen(val):
            if pd.isna(val): return ""
            return "background-color:#c8f7c5;color:#155724" if val > 0 \
                   else "background-color:#fcd5d5;color:#7b0000"

        def _color_src(val):
            return "background-color:#fff3cd" if val == "F" else ""

        _h_disp = _h_view.rename(columns={
            "delivery_date": "Delivery date",
            "H": "Hour",
            "cen_price_PLN": "CEN (PLN/MWh)",
            "source": "Source",
        })
        st.dataframe(
            _h_disp.style
                .applymap(_color_cen, subset=["CEN (PLN/MWh)"])
                .applymap(_color_src, subset=["Source"]),
            use_container_width=True, hide_index=True, height=500,
        )

        st.divider()
        st.subheader("Daily averages")
        _daily = (
            _h_view.groupby("delivery_date")
            .agg(
                CEN_avg=("cen_price_PLN", "mean"),
                CEN_max=("cen_price_PLN", "max"),
                CEN_min=("cen_price_PLN", "min"),
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


# ══════════════════════════════════════════════════════════════════════════════
# PAGE — FORECAST
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Forecast":
    import importlib.util as _ilu_fc

    st.title("Price Forecast")
    st.caption("SARIMAX + ML models (DT / RF / XGB) for TGE Fixing prices")

    _fc_root = os.path.dirname(__file__)

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
                    CAST(sdac_last_date AS VARCHAR) AS last_price,
                    CAST(pk5_last_date  AS VARCHAR) AS pk5_last
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

    _today_fc = date.today()

    _ready_sources = [
        ("Fixing prices",  PARQUET_PATH,  "fixing_date",   "Trains price model"),
        ("PK5 plan",       PK5_PATH,      "business_date", "Drives forecast features"),
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

    # GER forecast (separate — uses run_timestamp, not a simple date column)
    _ger_d, _ger_str = _fc_ger_last()
    _ger_ok   = (_ger_d is not None) and (_ger_d >= _today_fc - timedelta(days=1))
    _ger_icon = "✅" if _ger_ok else ("⚠️" if _ger_d else "❌")
    _gc1, _gc2, _gc3, _gc4 = st.columns([2, 1.6, 1, 2.5])
    _gc1.markdown("GER forecast")
    _gc2.markdown(f"`{_ger_str}`")
    _gc3.markdown(_ger_icon)
    _gc4.markdown("<small style='color:#888'>GER comparison plot</small>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE — WEEKLY FORECAST
# ══════════════════════════════════════════════════════════════════════════════
elif page == "WeeklyForecast":
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
    _sm1, _sm2, _sm3, _sm4, _sm5, _sm6 = st.columns(6)

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
        _sm4.metric(f"Max ({_fc_max_day[0].strftime('%a')})", f"{_fc_max_day[1]:.1f}")
        _sm5.metric(f"Min ({_fc_min_day[0].strftime('%a')})", f"{_fc_min_day[1]:.1f}")
    else:
        _sm3.metric("Forecast avg", "—")
        _sm4.metric("Max day", "—")
        _sm5.metric("Min day", "—")

    _wf_res_vals = [_wf_pk5_val(d, "res") for d in _wf_days]
    _wf_res_valid = [v for v in _wf_res_vals if v is not None]
    if _wf_res_valid:
        _sm6.metric("Avg RES", f"{sum(_wf_res_valid)/len(_wf_res_valid):.0f} MW")
    else:
        _sm6.metric("Avg RES", "—")

    _wf_con.close()


# ══════════════════════════════════════════════════════════════════════════════
# PAGE — PLOTTING
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Plotting":
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

# ══════════════════════════════════════════════════════════════════════════════
# PAGE — Model Performance
# ══════════════════════════════════════════════════════════════════════════════
elif page == "Model Performance":
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
