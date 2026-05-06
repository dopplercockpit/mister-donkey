from enum import Enum
from datetime import datetime, timezone
from flask import jsonify, g, has_request_context


class ErrorCode(str, Enum):
    LOCATION_NOT_FOUND = "LOCATION_NOT_FOUND"
    API_ERROR          = "API_ERROR"
    RATE_LIMIT         = "RATE_LIMIT"
    INVALID_REQUEST    = "INVALID_REQUEST"
    INTERNAL_ERROR     = "INTERNAL_ERROR"


def error_response(
    message: str,
    code: ErrorCode = ErrorCode.INTERNAL_ERROR,
    http_status: int = 500,
    **extra,
):
    """Return a consistent JSON error tuple (response, status).

    All error responses include: error, code, timestamp, request_id.
    Pass keyword args to embed debug fields (trace, debug_info, etc.)
    without breaking the standard shape.
    """
    req_id = g.get("request_id", "unknown") if has_request_context() else "unknown"
    body = {
        "error": message,
        "code": code.value,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "request_id": req_id,
    }
    # Strip None-valued extras so they don't pollute prod responses
    body.update({k: v for k, v in extra.items() if v is not None})
    return jsonify(body), http_status
