"""
Authentication module for Quant Energy Trading App
Handles user login, registration, and session management via Supabase
"""

import streamlit as st
import pandas as pd
from supabase import create_client, Client
import hashlib
from datetime import datetime
import os
import base64

def _get_supabase_client() -> Client:
    """Initialize Supabase client from secrets"""
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)

def hash_password(password: str) -> str:
    """Hash password using SHA256"""
    return hashlib.sha256(password.encode()).hexdigest()

def register(email: str, password: str) -> tuple[bool, str]:
    """Register new user in Supabase

    Returns (success, message)
    """
    try:
        client = _get_supabase_client()
        password_hash = hash_password(password)

        # Check if user exists
        response = client.table("users").select("id").eq("email", email).execute()
        if response.data:
            return False, "Email już istnieje"

        # Create user
        response = client.table("users").insert({
            "email": email,
            "password_hash": password_hash,
            "created_at": datetime.now().isoformat()
        }).execute()

        if response.data:
            user_id = response.data[0]["id"]

            # Assign default 'viewer' role
            client.table("user_roles").insert({
                "user_id": user_id,
                "role": "viewer",
                "created_at": datetime.now().isoformat()
            }).execute()

            return True, "Rejestracja udana! Zaloguj się teraz"
        return False, "Błąd podczas rejestracji"
    except Exception as e:
        return False, f"Błąd: {str(e)}"

def login(email: str, password: str) -> tuple[bool, str, int | None]:
    """Authenticate user with Supabase

    Returns (success, message, user_id)
    """
    try:
        client = _get_supabase_client()
        password_hash = hash_password(password)

        # Query user by email and password
        response = client.table("users").select("id, email").eq("email", email).eq("password_hash", password_hash).execute()

        if response.data:
            user_id = response.data[0]["id"]
            return True, "Login udany!", user_id
        return False, "Email lub hasło niepoprawne", None
    except Exception as e:
        return False, f"Błąd: {str(e)}", None

def get_user_role(user_id: int) -> str:
    """Fetch user role from Supabase

    Returns role name: 'admin', 'trader', or 'viewer'
    """
    try:
        client = _get_supabase_client()
        response = client.table("user_roles").select("role").eq("user_id", user_id).execute()

        if response.data:
            return response.data[0]["role"]
        return "viewer"  # Default role
    except Exception:
        return "viewer"

def render_login_page():
    """Render login/registration page with Supabase integration"""
    _bg_path = os.path.join(os.path.dirname(__file__), "..", "pics", "NJGT.jpg")
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
    """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    tab_login, tab_register = st.tabs(["Logowanie", "Rejestracja"])

    with tab_login:
        st.markdown("#### Zaloguj się")
        email = st.text_input("Email", key="login_email", placeholder="your@email.com")
        password = st.text_input("Hasło", type="password", key="login_password")

        if st.button("Login", type="primary", use_container_width=True, key="btn_login"):
            if not email or not password:
                st.error("Podaj email i hasło")
            else:
                success, message, user_id = login(email, password)
                if success:
                    st.session_state.user_id = user_id
                    st.session_state.user_email = email
                    st.session_state.authenticated = True
                    st.success(message)
                    st.rerun()
                else:
                    st.error(message)

    with tab_register:
        st.markdown("#### Załóż konto")
        email = st.text_input("Email", key="register_email", placeholder="your@email.com")
        password = st.text_input("Hasło", type="password", key="register_password")
        password_confirm = st.text_input("Potwierdź hasło", type="password", key="register_password_confirm")

        if st.button("Zarejestruj", type="primary", use_container_width=True, key="btn_register"):
            if not email or not password:
                st.error("Podaj email i hasło")
            elif password != password_confirm:
                st.error("Hasła się nie zgadzają")
            else:
                success, message = register(email, password)
                if success:
                    st.success(message)
                else:
                    st.error(message)

    st.stop()
