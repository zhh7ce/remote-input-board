from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
import json

from py_remote_input.auth import InvalidPin, RateLimited


def load_html_page() -> str:
    return resources.files(__package__).joinpath("templates", "index.html").read_text(encoding="utf-8")


HTML_PAGE = load_html_page()


@dataclass
class Response:
    status_code: int
    content_type: str
    body: bytes


def json_response(status_code: int, payload: dict) -> Response:
    return Response(
        status_code=status_code,
        content_type="application/json; charset=utf-8",
        body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )


def _read_json_body(body: bytes, logger) -> dict | None:
    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        logger.warn("Rejected invalid JSON body.")
        return None
    return payload


def _unauthorized() -> Response:
    return json_response(401, {"ok": False, "error": "PIN required.", "authRequired": True})


PUBLIC_ROUTES = {("GET", "/"), ("GET", "/api/auth-info"), ("POST", "/api/auth")}


# Mirrors key_input.ALLOWED_KEYS — a new key must be added to both layers.
ALLOWED_REMOTE_KEYS = {"Return"}

# Cap for text passed via the query string (GET /api/type). Percent-encoded
# CJK inflates 3-9x, so this keeps URLs well under every proxy/browser limit.
MAX_GET_TEXT_CHARS = 600


def _handle_type_text(text, type_text, logger, record_history) -> Response:
    if not isinstance(text, str) or not text.strip():
        logger.warn("Rejected empty text submission.")
        return json_response(400, {"error": "Text is required."})

    logger.info("Received typing request.", {"textLength": len(text)})
    try:
        result = type_text(text)
        if record_history is not None:
            record_history({"kind": "text", "text": text})
        logger.info("Typing request completed.", result)
        payload = {"ok": True, "sentChars": len(text), **result}
        return json_response(200, payload)
    except Exception as exc:  # noqa: BLE001
        logger.error("Typing request failed.", {"error": str(exc)})
        return json_response(500, {"error": str(exc)})


def _handle_type_key(key, press_key, logger, record_history) -> Response:
    if not isinstance(key, str) or key not in ALLOWED_REMOTE_KEYS:
        return json_response(400, {"ok": False, "error": "Unsupported key."})
    logger.info("Received key request.", {"key": key})
    try:
        if press_key is None:
            return json_response(500, {"ok": False, "error": "Key input is not configured."})
        result = press_key(key)
        if record_history is not None:
            record_history({"kind": "key", "key": key})
        logger.info("Key request completed.", result)
        return json_response(200, {"ok": True, **result})
    except Exception as exc:  # noqa: BLE001
        logger.error("Key request failed.", {"error": str(exc)})
        return json_response(500, {"ok": False, "error": str(exc)})


def handle_request(
    method: str,
    path: str,
    body: bytes,
    type_text,
    logger,
    *,
    press_key=None,
    record_history=None,
    auth=None,
    client_ip: str = "",
    token: str | None = None,
    query: dict[str, str] | None = None,
) -> Response:
    # Token may arrive as an Authorization: Bearer header or, for plain-URL
    # clients (shortcuts, curl, bookmarks), as a "token" query parameter.
    params = query or {}
    resolved_token = token or params.get("token") or None
    if method == "GET" and path == "/":
        logger.info("Served mobile page.")
        return Response(200, "text/html; charset=utf-8", HTML_PAGE.encode("utf-8"))

    if method == "GET" and path == "/api/auth-info":
        pin_length = auth.pin_length if auth is not None else 0
        return json_response(200, {"ok": True, "pinLength": pin_length})

    if method == "POST" and path == "/api/auth":
        payload = _read_json_body(body, logger)
        if payload is None:
            return json_response(400, {"ok": False, "error": "Invalid JSON body."})
        pin = payload.get("pin", "")
        if not isinstance(pin, str) or not pin.strip():
            return json_response(400, {"ok": False, "error": "PIN is required."})
        try:
            session_token = auth.authenticate(client_ip, pin)
        except RateLimited as exc:
            logger.warn("PIN login rate limited.", {"ip": client_ip, "retryAfter": exc.retry_after})
            return json_response(429, {"ok": False, "error": str(exc), "retryAfter": exc.retry_after})
        except InvalidPin:
            logger.warn("PIN login rejected.", {"ip": client_ip})
            return json_response(401, {"ok": False, "error": "Incorrect PIN."})
        logger.info("Client authenticated with PIN.", {"ip": client_ip})
        return json_response(200, {"ok": True, "token": session_token})

    if method == "POST" and path == "/api/logout":
        revoked = auth.revoke(resolved_token)
        logger.info("Device unpaired.", {"ip": client_ip, "revoked": revoked})
        return json_response(200, {"ok": True})

    if auth is not None and (method, path) not in PUBLIC_ROUTES:
        if not auth.validate(resolved_token, client_ip):
            logger.warn("Rejected unauthenticated request.", {"ip": client_ip, "path": path})
            return _unauthorized()

    if method == "GET" and path == "/api/ping":
        # Cheap pairing probe for the mobile page (requires a valid token).
        return json_response(200, {"ok": True})

    if method == "GET" and path == "/api/type":
        if "key" in params:
            return _handle_type_key(params.get("key"), press_key, logger, record_history)
        if "text" in params:
            url_text = params.get("text") or ""
            if len(url_text) > MAX_GET_TEXT_CHARS:
                return json_response(
                    400,
                    {"error": f"Text too long for GET (max {MAX_GET_TEXT_CHARS} chars); use POST /api/type."},
                )
            return _handle_type_text(url_text, type_text, logger, record_history)
        return json_response(400, {"error": "Provide text or key in the query string."})

    if method == "POST" and path == "/api/type":
        payload = _read_json_body(body, logger)
        if payload is None:
            return json_response(400, {"error": "Invalid JSON body."})

        # Key press request: {"key": "Return"}.
        key = payload.get("key")
        if key is not None:
            return _handle_type_key(key, press_key, logger, record_history)

        return _handle_type_text(payload.get("text", ""), type_text, logger, record_history)

    return json_response(404, {"error": "Not found."})
