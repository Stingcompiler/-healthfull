"""Loopback HTTP API used by the hospital-sys web app on this workstation.

GET  /health          no auth; tells the web app the agent is running
POST /print/receipt   Bearer token; ESC/POS receipt to the receipt printer
POST /print/label     Bearer token; ZPL or ESC/POS label to the label printer

Errors use the same JSON shape as the main API: {"code", "message", "details"}.
Defences: loopback bind only, Host header allow-list (DNS rebinding), Origin allow-list with
CORS and Private Network Access preflight, constant-time token check, body size cap,
socket timeouts. Request bodies (patient data) are never logged.
"""

from __future__ import annotations

import hmac
import json
import logging
import socket
from collections.abc import Callable
from decimal import Decimal
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from . import __version__
from .config import AgentConfig, PrinterConfig
from .render import PayloadError, parse_label, parse_receipt, receipt_escpos, render_label
from .transport import Delivery, PrinterUnavailableError, deliver

log = logging.getLogger("hospital_agent")


class ApiError(Exception):
    def __init__(
        self, status: HTTPStatus, code: str, message: str, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}


def _allowed_hosts(host: str, port: int) -> frozenset[str]:
    literal = f"[{host}]" if ":" in host else host
    return frozenset(
        {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}", f"{literal}:{port}"}
    )


class AgentServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        if ":" in config.host:  # IPv6 loopback
            self.address_family = socket.AF_INET6
        super().__init__((config.host, config.port), AgentHandler)
        # Computed after bind so port 0 (tests) resolves to the real port.
        self.allowed_hosts = _allowed_hosts(config.host, self.bound_port)

    @property
    def bound_port(self) -> int:
        return int(self.server_address[1])


class AgentHandler(BaseHTTPRequestHandler):
    server: AgentServer
    server_version = f"hospital-agent/{__version__}"
    sys_version = ""
    protocol_version = "HTTP/1.1"
    timeout = 15  # seconds per socket operation; a stalled client cannot pin a thread

    # ------------------------------------------------------------------ plumbing

    @property
    def config(self) -> AgentConfig:
        return self.server.config

    def log_message(self, format: str, *args: Any) -> None:
        log.info("%s %s", self.address_string(), format % args)

    def _origin(self) -> str | None:
        origin = self.headers.get("Origin")
        return origin.lower() if origin else None

    def _cors_headers(self) -> dict[str, str]:
        origin = self._origin()
        if origin and origin in self.config.allowed_origins:
            return {"Access-Control-Allow-Origin": origin, "Vary": "Origin"}
        return {"Vary": "Origin"}

    def _send_json(
        self, status: HTTPStatus, body: dict[str, Any], extra: dict[str, str] | None = None
    ) -> None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in {**self._cors_headers(), **(extra or {})}.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(payload)

    def _send_error(self, error: ApiError) -> None:
        # The request body may be unread; never reuse this connection for another request.
        self.close_connection = True
        self._send_json(
            error.status,
            {"code": error.code, "message": error.message, "details": error.details},
            {"Connection": "close"},
        )

    def _guard_host_and_origin(self) -> None:
        host = (self.headers.get("Host") or "").lower()
        if host not in self.server.allowed_hosts:
            raise ApiError(HTTPStatus.FORBIDDEN, "AGENT_BAD_HOST", "Host header not allowed")
        origin = self._origin()
        if origin is not None and origin not in self.config.allowed_origins:
            raise ApiError(HTTPStatus.FORBIDDEN, "AGENT_ORIGIN_DENIED", "Origin not allowed")

    def _require_token(self) -> None:
        header = self.headers.get("Authorization", "")
        scheme, _, supplied = header.partition(" ")
        expected = self.config.token.encode("utf-8")
        if scheme.lower() != "bearer" or not hmac.compare_digest(
            supplied.strip().encode("utf-8"), expected
        ):
            raise ApiError(HTTPStatus.UNAUTHORIZED, "AGENT_UNAUTHORIZED", "Missing or bad token")

    def _read_json(self) -> Any:
        content_type = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if content_type != "application/json":
            raise ApiError(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                "AGENT_BAD_CONTENT_TYPE",
                "Content-Type must be application/json",
            )
        length_header = self.headers.get("Content-Length")
        if length_header is None:
            raise ApiError(
                HTTPStatus.LENGTH_REQUIRED, "AGENT_LENGTH_REQUIRED", "Content-Length required"
            )
        try:
            length = int(length_header)
        except ValueError as exc:
            raise ApiError(
                HTTPStatus.BAD_REQUEST, "AGENT_BAD_REQUEST", "Bad Content-Length"
            ) from exc
        if length < 0 or length > self.config.max_body_bytes:
            raise ApiError(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                "AGENT_BODY_TOO_LARGE",
                f"Body must be at most {self.config.max_body_bytes} bytes",
            )
        raw = self.rfile.read(length)
        try:
            # Decimal for any numeric literal: money must never pass through float.
            return json.loads(raw.decode("utf-8"), parse_float=Decimal)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError(
                HTTPStatus.BAD_REQUEST, "AGENT_BAD_JSON", "Body is not valid JSON"
            ) from exc

    # ------------------------------------------------------------------ verbs

    def do_OPTIONS(self) -> None:
        try:
            self._guard_host_and_origin()
            if self._origin() is None:
                raise ApiError(
                    HTTPStatus.BAD_REQUEST, "AGENT_BAD_REQUEST", "Preflight needs Origin"
                )
        except ApiError as error:
            self._send_error(error)
            return
        extra = {
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Authorization, Content-Type",
            "Access-Control-Max-Age": "600",
            "Content-Length": "0",
        }
        # Chrome Private/Local Network Access: a LAN page calling loopback needs explicit consent.
        if self.headers.get("Access-Control-Request-Private-Network", "").lower() == "true":
            extra["Access-Control-Allow-Private-Network"] = "true"
        self.send_response(HTTPStatus.NO_CONTENT)
        for key, value in {**self._cors_headers(), **extra}.items():
            self.send_header(key, value)
        self.end_headers()

    def do_GET(self) -> None:
        self._dispatch({"/health": self._health})

    def do_POST(self) -> None:
        self._dispatch({"/print/receipt": self._print_receipt, "/print/label": self._print_label})

    def do_PUT(self) -> None:
        self._dispatch({})

    def do_PATCH(self) -> None:
        self._dispatch({})

    def do_DELETE(self) -> None:
        self._dispatch({})

    def _dispatch(self, routes: dict[str, Callable[[], None]]) -> None:
        path = self.path.split("?", 1)[0]
        try:
            self._guard_host_and_origin()
            handler = routes.get(path)
            if handler is None:
                raise ApiError(HTTPStatus.NOT_FOUND, "NOT_FOUND", "No such endpoint")
            handler()
        except ApiError as error:
            self._send_error(error)
        except Exception:  # last resort: never leak a traceback to the client
            log.exception("unhandled error on %s %s", self.command, path)
            self._send_error(
                ApiError(HTTPStatus.INTERNAL_SERVER_ERROR, "AGENT_INTERNAL", "Internal error")
            )

    # ------------------------------------------------------------------ endpoints

    def _health(self) -> None:
        def describe(printer: PrinterConfig | None) -> dict[str, Any]:
            if printer is None:
                return {"configured": False}
            return {
                "configured": True,
                "transport": printer.transport,
                "language": printer.language,
            }

        self._send_json(
            HTTPStatus.OK,
            {
                "status": "ok",
                "version": __version__,
                "dry_run": self.config.dry_run,
                "printers": {
                    "receipt": describe(self.config.receipt),
                    "label": describe(self.config.label),
                },
            },
        )

    def _printer(self, printer: PrinterConfig | None, kind: str) -> PrinterConfig:
        if printer is None:
            raise ApiError(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "PRINTER_NOT_CONFIGURED",
                f"No {kind} printer is configured on this workstation",
            )
        return printer

    def _deliver(self, printer: PrinterConfig, kind: str, data: bytes) -> None:
        try:
            result: Delivery = deliver(self.config, printer, kind, data)
        except PrinterUnavailableError as exc:
            log.warning("print job failed: %s", exc)
            raise ApiError(
                HTTPStatus.BAD_GATEWAY,
                "PRINTER_UNAVAILABLE",
                "The printer could not be reached",
                {"printer": printer.name, "reason": str(exc)},
            ) from exc
        log.info(
            "printed %s job=%s bytes=%d dry_run=%s",
            kind,
            result.job_id,
            result.bytes,
            result.dry_run,
        )
        body: dict[str, Any] = {
            "job_id": result.job_id,
            "printer": result.printer,
            "dry_run": result.dry_run,
            "bytes": result.bytes,
        }
        if result.output is not None:
            body["output"] = result.output
        self._send_json(HTTPStatus.OK, body)

    def _print_receipt(self) -> None:
        self._require_token()
        printer = self._printer(self.config.receipt, "receipt")
        try:
            receipt = parse_receipt(self._read_json())
        except PayloadError as exc:
            raise ApiError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "AGENT_INVALID_PAYLOAD",
                exc.message,
                {"field": exc.field},
            ) from exc
        self._deliver(printer, "receipt", receipt_escpos(receipt, printer))

    def _print_label(self) -> None:
        self._require_token()
        printer = self._printer(self.config.label, "label")
        try:
            label = parse_label(self._read_json())
        except PayloadError as exc:
            raise ApiError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "AGENT_INVALID_PAYLOAD",
                exc.message,
                {"field": exc.field},
            ) from exc
        self._deliver(printer, "label", render_label(label, printer))


def make_server(config: AgentConfig) -> AgentServer:
    return AgentServer(config)
