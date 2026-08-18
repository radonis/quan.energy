import streamlit as st
import os, base64
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

# ── Page imports ──────────────────────────────────────────────────────────────
from pages import spot, trading, tso, forward, forecast, admin

# ── Sidebar nav ───────────────────────────────────────────────────────────────
st.sidebar.title("Menu")

_SPOT_PAGES    = ["Prices", "German SPOT"]
_TRADING_PAGES = ["FixTrade", "TSOTrade", "P&L Dashboard", "FixHeatmap", "TSOHeatmap"]
_TSO_PAGES     = ["PK5", "PSE", "PowerDemand", "PSE_Viewer", "PK5_Snapshots"]
_FC_PAGES      = ["Forecast", "WeeklyForecast", "Plotting", "Model Performance"]
_FWD_PAGES     = ["OTF / EE", "OTF / Gas", "ETS1", "CurrentCDS", "CurrentCCS", "Coal", "Liquidity", "Compare"]
_ADM_PAGES     = ["Parquet", "Logs", "Admin", "CDS", "CCS"]

_PAGE_LABELS = {
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

# ── Routing ───────────────────────────────────────────────────────────────────
# SPOT
if   page == "Prices":       spot.render_prices()
elif page == "German SPOT":  spot.render_german_spot()

# Trading
elif page == "FixTrade":       trading.render_fixtrade()
elif page == "TSOTrade":       trading.render_tsotrade()
elif page == "P&L Dashboard":  trading.render_pnl()
elif page == "FixHeatmap":     trading.render_fix_heatmap()
elif page == "TSOHeatmap":     trading.render_tso_heatmap()

# TSO
elif page == "PSE":           tso.render_pse()
elif page == "PK5":           tso.render_pk5()
elif page == "PK5_Snapshots": tso.render_pk5_snapshots()
elif page == "PowerDemand":   tso.render_power_demand()
elif page == "PSE_Viewer":    tso.render_pse_viewer()

# Forward
elif page == "ETS1":       forward.render_ets()
elif page == "Coal":       forward.render_coal()
elif page == "OTF / EE":  forward.render_otf_ee()
elif page == "CurrentCDS": forward.render_cds()
elif page == "CurrentCCS": forward.render_ccs()
elif page == "OTF / Gas":  forward.render_otf_gas()
elif page == "Compare":    forward.render_compare()
elif page == "Liquidity":  forward.render_liquidity()

# Forecast
elif page == "Forecast":         forecast.render_forecast()
elif page == "WeeklyForecast":   forecast.render_weekly()
elif page == "Plotting":         forecast.render_plotting()
elif page == "Model Performance":forecast.render_performance()

# Admin
elif page == "Parquet": admin.render_parquet()
elif page == "Logs":    admin.render_logs()
elif page == "CDS":     admin.render_cds_config()
elif page == "CCS":     admin.render_ccs_config()
elif page == "Admin":   admin.render_admin()
