"""
Permissions module for Quant Energy Trading App
Handles role-based access control via Supabase REST API
"""

import streamlit as st
import requests

SUPABASE_URL = st.secrets["supabase"]["url"]
SUPABASE_KEY = st.secrets["supabase"]["key"]

def has_access(user_id: str, module_name: str) -> bool:
    """Check if user has access to specific module via REST API"""
    try:
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}"
        }

        response = requests.get(
            f"{SUPABASE_URL}/rest/v1/module_access?user_id=eq.{user_id}&module_name=eq.{module_name}&select=id",
            headers=headers,
            timeout=10
        )

        return len(response.json()) > 0
    except Exception:
        return False

def get_available_modules(user_id: str) -> list[str]:
    """Get list of modules available to user via REST API"""
    try:
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}"
        }

        response = requests.get(
            f"{SUPABASE_URL}/rest/v1/module_access?user_id=eq.{user_id}&select=module_name",
            headers=headers,
            timeout=10
        )

        modules = [row["module_name"] for row in response.json()]
        return sorted(modules)
    except Exception:
        return []

def get_user_role(user_id: str) -> str:
    """Get user role from Supabase REST API"""
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

def check_permission(module_name: str):
    """Decorator to enforce module access permissions"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            user_id = st.session_state.get("user_id")
            if not user_id or not has_access(user_id, module_name):
                st.error(f"Brak dostępu do modułu: {module_name}")
                st.stop()
            return func(*args, **kwargs)
        return wrapper
    return decorator
