from __future__ import annotations

from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import socket
import ssl
import threading
from urllib.parse import parse_qs, urlparse

from py_remote_input import paths
from py_remote_input.auth import TRUSTED_DEVICES_FILE_NAME, AuthStore, load_pin
from py_remote_input.logger import Logger
from py_remote_input.typer import press_key, type_text
from py_remote_input.web import handle_request


def get_local_addresses(port: int) -> list[str]:
    addresses: list[str] = []
    seen: set[str] = set()
    try:
        hostname = socket.gethostname()
        for family, _, _, _, sockaddr in socket.getaddrinfo(hostname, port, family=socket.AF_INET):
            if family != socket.AF_INET:
                continue
            address = sockaddr[0]
            if address.startswith("127.") or address in seen:
                continue
            seen.add(address)
            addresses.append(f"{address}:{port}")
    except OSError:
        pass
    return addresses


def build_history_recorder(log_dir: Path):
    history_dir = log_dir / "history"
    history_dir.mkdir(parents=True, exist_ok=True)

    def record_history(item: dict) -> None:
        now = datetime.now()
        day_dir = history_dir / now.strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)
        path = day_dir / (now.strftime("%H") + ".log")
        payload = {
            "createdAt": now.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            **item,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    return record_history


def build_handler(logger: Logger, record_history, type_text, auth: AuthStore, press_key=None):
    class RequestHandler(BaseHTTPRequestHandler):
        # HTTP/1.1 enables keep-alive so repeated sends reuse the connection.
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:  # noqa: N802
            self._handle()

        def do_POST(self) -> None:  # noqa: N802
            self._handle()

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self._send_cors_headers()
            self.end_headers()

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            # Suppressed on purpose: request lines can contain the token and
            # typed text (GET /api/type?token=...&text=...). Never log them.
            return

        def _send_cors_headers(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

        def _bearer_token(self) -> str | None:
            header = self.headers.get("Authorization", "")
            if header.startswith("Bearer "):
                return header[len("Bearer "):].strip() or None
            return None

        def _handle(self) -> None:
            parsed = urlparse(self.path)
            query = {k: v[0] for k, v in parse_qs(parsed.query, keep_blank_values=True).items()}
            content_length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(content_length) if content_length else b""
            response = handle_request(
                self.command,
                parsed.path,
                body,
                type_text,
                logger,
                press_key=press_key,
                record_history=record_history,
                auth=auth,
                client_ip=self.client_address[0],
                token=self._bearer_token(),
                query=query,
            )
            self.send_response(response.status_code)
            self.send_header("Content-Type", response.content_type)
            self.send_header("Content-Length", str(len(response.body)))
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(response.body)

    return RequestHandler


DEFAULT_CERT_FILE = "cert.pem"
DEFAULT_KEY_FILE = "key.pem"


def resolve_tls_files(base_dir: Path) -> tuple[str, str]:
    """Pick TLS cert/key paths.

    Same idiom as shell ``: "${SSL_CERT_FILE:=<config>/cert.pem}"``:
    base_dir's cert.pem/key.pem (the XDG config directory by default) are the
    defaults, and an environment variable overrides the corresponding path
    when set.
    """
    cert_file = os.environ.get("SSL_CERT_FILE") or str(base_dir / DEFAULT_CERT_FILE)
    key_file = os.environ.get("SSL_KEY_FILE") or str(base_dir / DEFAULT_KEY_FILE)
    return cert_file, key_file


def wrap_tls(server: ThreadingHTTPServer, cert_file: str, key_file: str) -> None:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_file, key_file)
    server.socket = context.wrap_socket(server.socket, server_side=True)


def tls_status(base_dir: Path) -> tuple[str, str, bool]:
    """Return (cert_file, key_file, ready). Raises if only one file exists."""
    cert_file, key_file = resolve_tls_files(base_dir)
    cert_exists = Path(cert_file).is_file()
    key_exists = Path(key_file).is_file()
    if cert_exists and key_exists:
        return cert_file, key_file, True
    if not cert_exists and not key_exists:
        return cert_file, key_file, False
    missing = []
    if not cert_exists:
        missing.append(f"certificate {cert_file}")
    if not key_exists:
        missing.append(f"private key {key_file}")
    raise RuntimeError(
        "To enable HTTPS both files must exist; missing: "
        + " and ".join(missing)
        + ". Generate them with remote-input-board-generate-cert "
        "(scripts/generate_cert.sh in the source tree), or set/clear "
        "SSL_CERT_FILE and SSL_KEY_FILE."
    )


def maybe_wrap_tls(server: ThreadingHTTPServer, logger: Logger, base_dir: Path) -> bool:
    """Enable HTTPS when both cert and key are available (default paths or env)."""
    cert_file, key_file, ready = tls_status(base_dir)
    if not ready:
        return False
    wrap_tls(server, cert_file, key_file)
    logger.info(f"TLS enabled with certificate {cert_file} (key {key_file}).")
    return True


def create_servers(
    handler: type[BaseHTTPRequestHandler],
    port: int,
    https_port: int | None,
    base_dir: Path,
    logger: Logger,
) -> tuple[list[ThreadingHTTPServer], int | None]:
    """Bind the plain HTTP server and, when certs exist, a second TLS server.

    Both share the same handler (PIN sessions and history included).
    """
    http_server = ThreadingHTTPServer(("0.0.0.0", port), handler)
    cert_file, key_file, tls_ready = tls_status(base_dir)
    if not tls_ready:
        return [http_server], None
    if https_port is not None and https_port == port and port != 0:
        raise RuntimeError("HTTPS_PORT must differ from PORT (HTTP and HTTPS need separate ports).")
    https_server = ThreadingHTTPServer(("0.0.0.0", https_port if https_port is not None else port + 1), handler)
    wrap_tls(https_server, cert_file, key_file)
    logger.info(f"TLS enabled with certificate {cert_file} (key {key_file}).")
    return [http_server, https_server], https_server.server_address[1]


def serve() -> None:
    port = int(os.environ.get("PORT", "3210"))
    base_dir, data_dir = paths.ensure_app_dirs()
    # Migrate before anything (e.g. the logger) writes into data/logs,
    # otherwise the legacy logs/ directory can no longer move over wholesale.
    moved = paths.migrate_legacy_files(base_dir, data_dir)
    log_dir = data_dir / "logs"
    logger = Logger(log_dir / "server.log")
    logger.info(f"Config directory: {base_dir}")
    logger.info(f"Data directory:   {data_dir}")
    for name in moved:
        logger.info(f"Migrated legacy file from the working directory into the XDG layout: {name}")

    pin, pin_path, pin_generated = load_pin(base_dir)
    trusted_path = base_dir / TRUSTED_DEVICES_FILE_NAME
    auth = AuthStore(pin, trusted_path=trusted_path)
    if trusted_path.exists():
        logger.info(f"Loaded {auth.device_count} trusted device(s) from {trusted_path}.")
    if pin_generated:
        logger.info(f"Generated a new PIN and saved it to {pin_path} (chmod 600).")
    else:
        logger.info(f"Loaded PIN from {'PIN_CODE' if os.environ.get('PIN_CODE', '').strip() else pin_path}.")

    record_history = build_history_recorder(log_dir)
    handler = build_handler(logger, record_history, type_text, auth, press_key=press_key)

    # HTTP always listens on PORT (legacy behaviour); HTTPS joins on
    # HTTPS_PORT (default PORT + 1) when cert.pem/key.pem are present.
    https_port_env = os.environ.get("HTTPS_PORT")
    https_port = int(https_port_env) if https_port_env is not None else None
    servers, https_port = create_servers(handler, port, https_port, base_dir, logger)
    for running_server in servers:
        running_server.daemon_threads = True
        threading.Thread(target=running_server.serve_forever, daemon=True).start()

    logger.info(f"Remote input server is running. HTTP on port {port}."
                + (f" HTTPS on port {https_port}." if https_port is not None else ""))
    logger.info("Open one of these addresses on your phone:")
    for address in get_local_addresses(port):
        logger.info(f"http://{address}")
    if https_port is not None:
        for address in get_local_addresses(https_port):
            logger.info(f"https://{address}")
    logger.info(f"PIN required on first connect: {pin}")
    if https_port is None:
        logger.warn(
            "Running over plain HTTP only: the PIN and typed text are visible on the network. "
            f"Run remote-input-board-generate-cert to create cert.pem/key.pem in {base_dir}, then restart "
            "(HTTPS is picked up automatically on port "
            f"{os.environ.get('HTTPS_PORT', str(port + 1))}; SSL_CERT_FILE/SSL_KEY_FILE can override paths)."
        )
    else:
        logger.info("Both HTTP and HTTPS are live; open the https:// address for an encrypted connection.")
    logger.info("Keep the target desktop app focused before sending text from your phone.")

    # Handle SIGINT (Ctrl-C / kill -INT) and SIGTERM (systemd's default) the
    # same way so shutdown flushes paired devices either way.
    stop_event = threading.Event()

    def _request_stop(_signum, _frame) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)
    try:
        stop_event.wait()
        logger.info("Server stopping...")
    finally:
        for running_server in servers:
            running_server.shutdown()
            running_server.server_close()
        auth.flush()
        logger.info("Server stopped.")
