"""
Permissions module for Quant Energy Trading App
Handles role-based access control and module authorization via Supabase
"""

import streamlit as st
from supabase import create_client, Client

def _get_supabase_client() -> Client:
    """Initialize Supabase client from secrets"""
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)

def has_access(user_id: int, module_name: str) -> bool:
    """Check if user has access to specific module in Supabase"""
    try:
        client = _get_supabase_client()

        # Check if user has access to module
        response = client.table("module_access").select("id").eq("user_id", user_id).eq("module_name", module_name).execute()

        return len(response.data) > 0
    except Exception:
        return False

def get_available_modules(user_id: int) -> list[str]:
    """Get list of modules available to user"""
    try:
        client = _get_supabase_client()
        response = client.table("module_access").select("module_name").eq("user_id", user_id).execute()

        modules = [row["module_name"] for row in response.data]
        return sorted(modules)
    except Exception:
        return []

def get_user_role(user_id: int) -> str:
    """Get user role from Supabase"""
    try:
        client = _get_supabase_client()
        response = client.table("user_roles").select("role").eq("user_id", user_id).execute()

        if response.data:
            return response.data[0]["role"]
        return "viewer"
    except Exception:
        return "viewer"

def check_permission(module_name: str):
    """Decorator to enforce module access permissions"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            user_id = st.session_state.get("user_id")
            if not user_id or not has_access(user_id, module_name):
                st.error(f"❌ Brak dostępu do modułu: {module_name}")
                st.stop()
            return func(*args, **kwargs)
        return wrapper
    return decorator
