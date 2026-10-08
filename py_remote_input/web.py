from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
import json
import math


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


def _is_finite_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _finish_text_message(text: str, result: dict, record_history, text_stats) -> dict:
    if record_history is not None:
        record_history({"kind": "text", "text": text})
    total_chars = text_stats.get_total_chars() if text_stats is not None else None
    response = {"ok": True, "type": "type", "sentChars": len(text), **result}
    if total_chars is not None:
        response["totalChars"] = total_chars
    return response


def handle_realtime_message(
    payload: dict,
    logger,
    *,
    type_text=None,
    record_history=None,
    text_stats=None,
) -> dict:
    if not isinstance(payload, dict):
        return {"ok": False, "error": "Realtime message must be a JSON object."}

    message_type = payload.get("type")
    try:
        if message_type == "getStats":
            if text_stats is None:
                return {"ok": False, "error": "Text stats are not configured."}
            return {"ok": True, "type": "stats", "totalChars": text_stats.get_total_chars()}

        if message_type == "setStats":
            if text_stats is None:
                return {"ok": False, "error": "Text stats are not configured."}
            total = payload.get("totalChars")
            if not _is_finite_number(total):
                return {"ok": False, "error": "Expected a numeric totalChars."}
            saved = text_stats.save_total_chars(int(round(total)))
            return {"ok": True, "type": "stats", "totalChars": saved}

        if message_type == "type":
            text = payload.get("text", "")
            if not isinstance(text, str) or not text.strip():
                return {"ok": False, "error": "Text is required."}
            if type_text is None:
                return {"ok": False, "error": "Text input is not configured."}
            return _finish_text_message(text, type_text(text), record_history, text_stats)

        if message_type == "ping":
            return {"ok": True, "type": "pong"}

        return {"ok": False, "error": f"Unsupported realtime message: {message_type}"}
    except Exception as exc:  # noqa: BLE001
        logger.error("Realtime message failed.", {"type": message_type, "error": str(exc)})
        return {"ok": False, "error": str(exc)}


def handle_request(
    method: str,
    path: str,
    body: bytes,
    type_text,
    logger,
    *,
    record_history=None,
    text_stats=None,
) -> Response:
    if method == "GET" and path == "/":
        logger.info("Served mobile page.")
        return Response(200, "text/html; charset=utf-8", HTML_PAGE.encode("utf-8"))

    if method == "GET" and path == "/api/stats":
        total_chars = text_stats.get_total_chars() if text_stats is not None else 0
        return json_response(200, {"ok": True, "totalChars": total_chars})

    if method == "POST" and path == "/api/type":
        payload = _read_json_body(body, logger)
        if payload is None:
            return json_response(400, {"error": "Invalid JSON body."})

        text = payload.get("text", "")
        if not isinstance(text, str) or not text.strip():
            logger.warn("Rejected empty text submission.")
            return json_response(400, {"error": "Text is required."})

        logger.info("Received typing request.", {"textLength": len(text)})
        try:
            result = type_text(text)
            if record_history is not None:
                record_history({"kind": "text", "text": text})
            total_chars = text_stats.get_total_chars() if text_stats is not None else None
            logger.info("Typing request completed.", result)
            response_payload = {"ok": True, "sentChars": len(text), **result}
            if total_chars is not None:
                response_payload["totalChars"] = total_chars
            return json_response(200, response_payload)
        except Exception as exc:  # noqa: BLE001
            logger.error("Typing request failed.", {"error": str(exc)})
            return json_response(500, {"error": str(exc)})

    return json_response(404, {"error": "Not found."})
