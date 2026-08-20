"""
Authentication module for Quant Energy Trading App
Handles user login, registration via Supabase REST API
"""

import streamlit as st
import requests
import hashlib
from datetime import datetime
import os
import base64

SUPABASE_URL = st.secrets["supabase"]["url"]
SUPABASE_KEY = st.secrets["supabase"]["key"]

def hash_password(password: str) -> str:
    """Hash password using SHA256"""
    return hashlib.sha256(password.encode()).hexdigest()

def register(email: str, password: str) -> tuple[bool, str]:
    """Register new user via Supabase REST API

    Returns (success, message)
    """
    try:
        password_hash = hash_password(password)

        # Check if user exists
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}"
        }

        check_response = requests.get(
            f"{SUPABASE_URL}/rest/v1/users?email=eq.{email}&select=id",
            headers=headers,
            timeout=10
        )

        if check_response.json():
            return False, "Email już istnieje"

        # Create user
        user_data = {
            "email": email,
            "password_hash": password_hash,
            "created_at": datetime.now().isoformat()
        }

        insert_response = requests.post(
            f"{SUPABASE_URL}/rest/v1/users",
            json=user_data,
            headers=headers,
            timeout=10
        )

        if insert_response.status_code == 201:
            user = insert_response.json()[0]
            user_id = user["id"]

            # Assign default 'viewer' role
            role_data = {
                "user_id": user_id,
                "role": "viewer",
                "created_at": datetime.now().isoformat()
            }

            requests.post(
                f"{SUPABASE_URL}/rest/v1/user_roles",
                json=role_data,
                headers=headers,
                timeout=10
            )

            return True, "Rejestracja udana! Zaloguj się teraz"
        return False, "Błąd podczas rejestracji"
    except Exception as e:
        return False, f"Błąd: {str(e)}"

def login(email: str, password: str) -> tuple[bool, str, str | None]:
    """Authenticate user via Supabase REST API

    Returns (success, message, user_id)
    """
    try:
        password_hash = hash_password(password)

        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}"
        }

        # Query user by email and password
        response = requests.get(
            f"{SUPABASE_URL}/rest/v1/users?email=eq.{email}&password_hash=eq.{password_hash}&select=id,email",
            headers=headers,
            timeout=10
        )

        if response.json():
            user = response.json()[0]
            user_id = user["id"]
            return True, "Login udany!", user_id
        return False, "Email lub hasło niepoprawne", None
    except Exception as e:
        return False, f"Błąd: {str(e)}", None

def get_user_role(user_id: str) -> str:
    """Fetch user role from Supabase REST API

    Returns role name: 'admin', 'trader', or 'viewer'
    """
    try:
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}"
        }

        response = requests.get(
            f"{SUPABASE_URL}/rest/v1/user_roles?user_id=eq.{user_id}&select=role",
            headers=headers,
            timeout=10
        )

        if response.json():
            return response.json()[0]["role"]
        return "viewer"
    except Exception:
        return "viewer"

def render_login_page():
    """Render login/registration page with Supabase REST API"""
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
