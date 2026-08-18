"""
Admin Panel module for Quant Energy Trading App
Handles user management, role assignment, and module access control
"""

import streamlit as st
import pandas as pd
from supabase import create_client, Client

# TODO: Implement admin functions
# - render_admin_panel()
# - manage_users()
# - manage_roles()
# - manage_module_access()

AVAILABLE_MODULES = [
    "Coal", "Forecast", "Forward Market", "OTF EE", "OTF Gas",
    "ETS", "CDS", "CCS", "Prices", "FixTrade", "TSOTrade"
]

def render_admin_panel():
    """Render admin panel with user management"""
    st.title("⚙️ Panel Admina")
    st.write("Admin panel placeholder - to be implemented on Wednesday")

    tab1, tab2, tab3 = st.tabs(["Użytkownicy", "Dostępy", "Role"])

    with tab1:
        st.subheader("Zarządzaj użytkownikami")
        st.write("TODO: User management - to be implemented")

    with tab2:
        st.subheader("Przydziel dostęp do modułów")
        st.write("TODO: Module access management - to be implemented")

    with tab3:
        st.subheader("Zarządzaj rolami")
        st.write("TODO: Role management - to be implemented")
