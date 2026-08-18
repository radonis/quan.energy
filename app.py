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

# ── Auth check (Supabase-based) ────────────────────────────────────────────────
from page_modules import auth

def _check_auth():
    """Check authentication status, render login page if needed"""
    if st.session_state.get("authenticated"):
        return
    auth.render_login_page()

_check_auth()

# ── Page imports ──────────────────────────────────────────────────────────────
from page_modules import spot, trading, tso, forward, forecast, admin, otf_trading, spot_analysis, var_trading, ancillary, system_monitor, fc_module, fc_hourly_module, page_stats, spot_update, permissions

# ── Sidebar nav ───────────────────────────────────────────────────────────────
st.sidebar.title("Menu")

# ── User info & logout ────────────────────────────────────────────────────────
st.sidebar.markdown("---")
user_email = st.session_state.get("user_email", "Unknown")
user_role = permissions.get_user_role(st.session_state.get("user_id", 0))
st.sidebar.markdown(f"**👤 {user_email}**")
st.sidebar.markdown(f"<small style='color:#888'>Rola: {user_role}</small>", unsafe_allow_html=True)

if st.sidebar.button("🔓 Wyloguj", use_container_width=True, key="logout_btn"):
    st.session_state.clear()
    st.rerun()
st.sidebar.markdown("---")

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
