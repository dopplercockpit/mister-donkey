from flask import request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address


def _rate_limit_key() -> str:
    """Use session_id from the JSON body as the rate-limit key.
    Falls back to the client IP so unauthenticated callers are still bounded.
    """
    try:
        data = request.get_json(silent=True) or {}
        sid = (data.get("session_id") or "").strip()
        if sid:
            return f"session:{sid}"
    except Exception:
        pass
    return get_remote_address()


limiter = Limiter(
    key_func=_rate_limit_key,
    default_limits=[],
    storage_uri="memory://",
    headers_enabled=True,
)
