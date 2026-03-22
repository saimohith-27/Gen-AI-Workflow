import os
from typing import Optional

from supabase import Client, create_client


_supabase_client: Optional[Client] = None


def is_supabase_configured() -> bool:
    """Return True when required Supabase environment variables are present."""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    return bool(url and key)


def get_supabase_client() -> Client:
    """
    Create (once) and return a Supabase client.

    Required env vars:
    - SUPABASE_URL
    - SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY
    """
    global _supabase_client

    if _supabase_client is not None:
        return _supabase_client

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")

    if not url or not key:
        raise RuntimeError(
            "Supabase is not configured. Set SUPABASE_URL and "
            "SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_ANON_KEY)."
        )

    _supabase_client = create_client(url, key)
    return _supabase_client
