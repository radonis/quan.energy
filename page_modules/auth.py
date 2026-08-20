"""
Authentication module for Quant Energy Trading App
Mock auth - for development/testing without Supabase dependency
"""

import streamlit as st
import hashlib
from datetime import datetime
import os
import base64

# Mock users database (in-memory - resets on app restart)
if "users_db" not in st.session_state:
    st.session_state.users_db = {
        "admin@example.com": {
            "id": "user_001",
            "password_hash": hashlib.sha256("admin123".encode()).hexdigest(),
            "role": "admin"
        },
        "trader@example.com": {
            "id": "user_002",
            "password_hash": hashlib.sha256("trader123".encode()).hexdigest(),
            "role": "trader"
        },
        "viewer@example.com": {
            "id": "user_003",
            "password_hash": hashlib.sha256("viewer123".encode()).hexdigest(),
            "role": "viewer"
        },
        "rluczak@outlook.com": {
            "id": "user_004",
            "password_hash": hashlib.sha256("MapaEnergii77$".encode()).hexdigest(),
            "role": "admin"
        }
    }

def hash_password(password: str) -> str:
    """Hash password using SHA256"""
    return hashlib.sha256(password.encode()).hexdigest()

def register(email: str, password: str) -> tuple[bool, str]:
    """Register new user in mock database

    Returns (success, message)
    """
    if email in st.session_state.users_db:
        return False, "Email już istnieje"

    if len(password) < 6:
        return False, "Hasło musi mieć co najmniej 6 znaków"

    password_hash = hash_password(password)
    user_id = f"user_{len(st.session_state.users_db) + 1:03d}"

    st.session_state.users_db[email] = {
        "id": user_id,
        "password_hash": password_hash,
        "role": "viewer"
    }

    return True, "Rejestracja udana! Zaloguj się teraz"

def login(email: str, password: str) -> tuple[bool, str, str | None]:
    """Authenticate user from mock database

    Returns (success, message, user_id)
    """
    if email not in st.session_state.users_db:
        return False, "Email lub hasło niepoprawne", None

    user = st.session_state.users_db[email]
    password_hash = hash_password(password)

    if user["password_hash"] != password_hash:
        return False, "Email lub hasło niepoprawne", None

    return True, "Login udany!", user["id"]

def get_user_role(user_id: str) -> str:
    """Get user role from mock database

    Returns role name: 'admin', 'trader', or 'viewer'
    """
    for email, user_data in st.session_state.users_db.items():
        if user_data["id"] == user_id:
            return user_data["role"]
    return "viewer"

def render_login_page():
    """Render login/registration page"""
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
        st.info("Test users: admin@example.com / admin123, trader@example.com / trader123, viewer@example.com / viewer123")
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
                    st.info("Teraz zaloguj się w tab 'Logowanie'")
                else:
                    st.error(message)

    st.stop()
