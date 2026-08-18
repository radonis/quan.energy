import streamlit as st
import os, base64, hashlib, hmac
from datetime import date, timedelta, datetime

# ── Page config (must be first Streamlit call) ────────────────────────────────
try:
    from PIL import Image as _PIL_Image
    _page_icon = _PIL_Image.open(os.path.join(os.path.dirname(__file__), "pics", "icon2.png"))
except Exception:
    _page_icon = "⚡"

st.set_page_config(page_title="Quan.Energy", page_icon=_page_icon, layout="wide")

# ── Auth constants ────────────────────────────────────────────────────────────
# SHA-256 of the login password — plaintext never stored in code
_PWD_HASH      = "4467232f90e9b4f16495c19608c32611b480cad9a13b2daae14a3565c406628f"
# HMAC-SHA256 cookie token — not guessable without the secret
_COOKIE_SECRET = "2d5953315138a7e1229e70bcb0fb5f46b3b84193744a8ed25f887cb47ca0a437"
_COOKIE_TOKEN  = hmac.new(_COOKIE_SECRET.encode(), b"qe_session_v1", hashlib.sha256).hexdigest()

def _verify_password(pwd: str) -> bool:
    return hmac.compare_digest(
        hashlib.sha256(pwd.encode()).hexdigest(), _PWD_HASH
    )

# ── Cookie manager ────────────────────────────────────────────────────────────
try:
    import extra_streamlit_components as stx
    _cookie_mgr  = stx.CookieManager(key="qe_cookie_mgr")
    _COOKIE_NAME = "qe_auth"
    _COOKIE_VAL  = _COOKIE_TOKEN
    _COOKIES_OK  = True
except Exception:
    _COOKIES_OK  = False

# ── Login page ────────────────────────────────────────────────────────────────
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

def _check_password():
    if st.session_state.get("authenticated"):
        return
    if _COOKIES_OK:
        try:
            if _cookie_mgr.get(_COOKIE_NAME) == _COOKIE_VAL:
                st.session_state.authenticated = True
                return
        except Exception:
            pass
    _render_login_page()
    pwd = st.text_input("Password", type="password", placeholder="Enter password",
                        label_visibility="collapsed")
    if st.button("Login", type="primary", use_container_width=True):
        if _verify_password(pwd):
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

# ── Page imports ──────────────────────────────────────────────────────────────
from page_modules import spot, trading, tso, forward, forecast, admin, otf_trading, spot_analysis, var_trading, ancillary, system_monitor, fc_module, fc_hourly_module, page_stats, spot_update

# ── Sidebar nav ───────────────────────────────────────────────────────────────
st.sidebar.title("Menu")

_SPOT_PAGES    = ["Prices", "German SPOT", "SPOT Daily", "SPOTS History", "Update"]
_TRADING_PAGES = ["FixTrade", "TSOTrade", "VAR", "P&L Dashboard", "FixHeatmap", "TSOHeatmap", "SpreadMap", "OTF Trades", "OTF MtM"]
_TSO_PAGES     = ["PK5", "CEN Price", "PowerDemand", "PSE_Viewer", "PK5_Snapshots", "Ancillary History", "Ancillary Daily", "Power Reserve", "Price-Reserve Tracker"]
_FC_PAGES      = ["Forecast", "WeeklyForecast", "Plotting", "Model Performance", "SpreadForecast", "SpreadPlotting", "DE Forecast"]
_FWD_PAGES     = ["OTF / EE", "OTF / Gas", "ETS1", "CurrentCDS", "CurrentCCS", "Coal", "Liquidity", "Compare", "FC Kalibracja", "FC Raport"]
_FCH_PAGES     = ["FC Ratio", "FC Grafik", "FC Profil", "FC Manual"]
_ADM_PAGES     = ["Parquet", "Logs", "Admin", "CDS", "CCS", "Backup", "Data Files", "Stats"]

_PAGE_LABELS = {
    "Prices":          "Polish SPOT",
    "CurrentCDS":      "CDS",
    "CurrentCCS":      "CCS",
    "WeeklyForecast":  "Weekly",
    "Model Performance": "Performance",
    "PSE_Viewer":      "PSE Viewer",
    "PK5_Snapshots":   "PK5 Snapshots",
    "PowerDemand":     "Power Demand",
}

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

if "page" not in st.session_state:
    st.session_state.page = "Prices"

import uuid as _uuid
if "_session_id" not in st.session_state:
    st.session_state._session_id = str(_uuid.uuid4())[:8]

def _log_page_view(pg: str):
    import csv
    _pv_path = os.path.join(os.path.dirname(__file__), "app_data", "page_views.csv")
    os.makedirs(os.path.dirname(_pv_path), exist_ok=True)
    with open(_pv_path, "a", newline="", encoding="utf-8") as _f:
        csv.writer(_f).writerow([datetime.now().isoformat(), pg, st.session_state._session_id])

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
_nav_section("FC Hourly", _FCH_PAGES)
st.sidebar.markdown("---")
_nav_section("Admin",   _ADM_PAGES)

page = st.session_state.page

if st.session_state.get("_last_logged_page") != page:
    _log_page_view(page)
    st.session_state["_last_logged_page"] = page

# ── Routing ───────────────────────────────────────────────────────────────────
# SPOT
if   page == "Prices":         spot.render_prices()
elif page == "German SPOT":    spot.render_german_spot()
elif page == "SPOT Daily":     spot_analysis.render_spot_daily()
elif page == "SPOTS History":  spot_analysis.render_spots_history()
elif page == "Update":         spot_update.render_spot_update()

# Trading
elif page == "FixTrade":       trading.render_fixtrade()
elif page == "TSOTrade":       trading.render_tsotrade()
elif page == "VAR":            var_trading.render_var()
elif page == "P&L Dashboard":  trading.render_pnl()
elif page == "FixHeatmap":     trading.render_fix_heatmap()
elif page == "TSOHeatmap":     trading.render_tso_heatmap()
elif page == "SpreadMap":      trading.render_spread_map()
elif page == "OTF Trades":    otf_trading.render_otf_trades()
elif page == "OTF MtM":       otf_trading.render_otf_mtm()

# TSO
elif page == "CEN Price":     tso.render_pse()
elif page == "PK5":           tso.render_pk5()
elif page == "PK5_Snapshots": tso.render_pk5_snapshots()
elif page == "PowerDemand":   tso.render_power_demand()
elif page == "PSE_Viewer":         tso.render_pse_viewer()
elif page == "Ancillary History":  ancillary.render_history()
elif page == "Ancillary Daily":    ancillary.render_daily()
elif page == "Power Reserve":          system_monitor.render_tightness_heatmap()
elif page == "Price-Reserve Tracker":  system_monitor.render_elasticity_tracker()

# Forward
elif page == "ETS1":       forward.render_ets()
elif page == "Coal":       forward.render_coal()
elif page == "OTF / EE":  forward.render_otf_ee()
elif page == "CurrentCDS": forward.render_cds()
elif page == "CurrentCCS": forward.render_ccs()
elif page == "OTF / Gas":  forward.render_otf_gas()
elif page == "Compare":    forward.render_compare()
elif page == "Liquidity":      forward.render_liquidity()
elif page == "FC Kalibracja":  fc_module.render_calibration()
elif page == "FC Raport":      fc_module.render_report()

# FC Hourly
elif page == "FC Ratio":       fc_hourly_module.render_fc_ratio()
elif page == "FC Grafik":      fc_hourly_module.render_fc_grafik()
elif page == "FC Profil":      fc_hourly_module.render_fc_profil()
elif page == "FC Manual":      fc_hourly_module.render_fc_manual()

# Forecast
elif page == "Forecast":         forecast.render_forecast()
elif page == "WeeklyForecast":   forecast.render_weekly()
elif page == "Plotting":         forecast.render_plotting()
elif page == "Model Performance":forecast.render_performance()
elif page == "SpreadForecast":   forecast.render_spread_forecast()
elif page == "SpreadPlotting":   forecast.render_spread_plotting()
elif page == "DE Forecast":      forecast.render_de_forecast()

# Admin
elif page == "Parquet": admin.render_parquet()
elif page == "Logs":    admin.render_logs()
elif page == "CDS":     admin.render_cds_config()
elif page == "CCS":     admin.render_ccs_config()
elif page == "Admin":   admin.render_admin()
elif page == "Backup":     admin.render_backup()
elif page == "Data Files": admin.render_data_files()
elif page == "Stats":      page_stats.render_stats()
