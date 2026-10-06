from __future__ import annotations

import json
import socket
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from hospital_agent.config import AgentConfig
from hospital_agent.server import AgentServer

from .conftest import ORIGIN, Client, receipt_payload


def test_health_needs_no_token(client: Client) -> None:
    resp = client.request("GET", "/health")
    assert resp.status == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["dry_run"] is True
    assert body["printers"]["receipt"] == {
        "configured": True,
        "transport": "network",
        "language": "escpos",
    }
    assert resp.headers["cache-control"] == "no-store"


def test_print_requires_bearer_token(client: Client) -> None:
    resp = client.request("POST", "/print/receipt", receipt_payload())
    assert resp.status == 401
    assert resp.json()["code"] == "AGENT_UNAUTHORIZED"
    resp = client.request(
        "POST", "/print/receipt", receipt_payload(), {"Authorization": "Bearer wrong-token"}
    )
    assert resp.status == 401


def test_print_receipt_dry_run_writes_bytes(client: Client, config: AgentConfig) -> None:
    resp = client.request("POST", "/print/receipt", receipt_payload(), client.auth())
    assert resp.status == 200, resp.body
    body = resp.json()
    assert body["dry_run"] is True
    assert body["printer"] == "receipt_printer"
    out = Path(body["output"])
    assert out.parent == config.dry_run_dir
    data = out.read_bytes()
    assert len(data) == body["bytes"]
    assert data.startswith(b"\x1b@")
    assert b"14,500.50" in data
    # No partial files are left behind.
    assert not list(config.dry_run_dir.glob(".*.partial"))


def test_print_label_dry_run_writes_zpl(client: Client) -> None:
    resp = client.request(
        "POST",
        "/print/label",
        {"lines": ["Test Patient", "CBC"], "barcode": "S-000123"},
        client.auth(),
    )
    assert resp.status == 200, resp.body
    zpl = Path(resp.json()["output"]).read_text(encoding="utf-8")
    assert zpl.startswith("^XA") and "S-000123" in zpl


def test_concurrent_jobs_get_distinct_files(client: Client) -> None:
    outputs = {
        client.request("POST", "/print/receipt", receipt_payload(), client.auth()).json()["output"]
        for _ in range(5)
    }
    assert len(outputs) == 5


def test_validation_error_names_field(client: Client) -> None:
    resp = client.request("POST", "/print/receipt", receipt_payload(total=1.5), client.auth())
    assert resp.status == 422
    body = resp.json()
    assert body["code"] == "AGENT_INVALID_PAYLOAD"
    assert body["details"] == {"field": "total"}


def test_bad_json_and_content_type(client: Client) -> None:
    resp = client.request("POST", "/print/receipt", raw=b"{nope", headers=client.auth())
    assert resp.status == 400
    assert resp.json()["code"] == "AGENT_BAD_JSON"
    resp = client.request(
        "POST",
        "/print/receipt",
        raw=b"{}",
        headers={**client.auth(), "Content-Type": "text/plain"},
    )
    assert resp.status == 415


def test_body_size_is_capped(client: Client, config: AgentConfig) -> None:
    big = json.dumps(receipt_payload(footer="x" * 100)).encode() + b" " * config.max_body_bytes
    resp = client.request("POST", "/print/receipt", raw=big, headers=client.auth())
    assert resp.status == 413


def test_unknown_route_and_method(client: Client) -> None:
    assert client.request("GET", "/nope").status == 404
    assert client.request("DELETE", "/print/receipt", headers=client.auth()).status == 404


def test_cors_preflight_for_allowed_origin(client: Client) -> None:
    resp = client.request(
        "OPTIONS",
        "/print/receipt",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization, content-type",
            "Access-Control-Request-Private-Network": "true",
        },
    )
    assert resp.status == 204
    assert resp.headers["access-control-allow-origin"] == ORIGIN
    assert "Authorization" in resp.headers["access-control-allow-headers"]
    assert resp.headers["access-control-allow-private-network"] == "true"


def test_disallowed_origin_is_rejected(client: Client) -> None:
    evil = {"Origin": "http://evil.example"}
    assert client.request("OPTIONS", "/print/receipt", headers=evil).status == 403
    resp = client.request("POST", "/print/receipt", receipt_payload(), {**client.auth(), **evil})
    assert resp.status == 403
    assert resp.json()["code"] == "AGENT_ORIGIN_DENIED"
    assert "access-control-allow-origin" not in resp.headers


def test_allowed_origin_gets_cors_header_on_success(client: Client) -> None:
    resp = client.request("GET", "/health", headers={"Origin": ORIGIN})
    assert resp.headers["access-control-allow-origin"] == ORIGIN


def test_dns_rebinding_host_is_rejected(client: Client) -> None:
    resp = client.request("GET", "/health", headers={"Host": f"attacker.example:{client.port}"})
    assert resp.status == 403
    assert resp.json()["code"] == "AGENT_BAD_HOST"


def test_missing_printer_returns_503(config: AgentConfig) -> None:
    srv = AgentServer(replace(config, label=None))
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        resp = Client(srv).request("POST", "/print/label", {"barcode": "S-1"}, Client(srv).auth())
        assert resp.status == 503
        assert resp.json()["code"] == "PRINTER_NOT_CONFIGURED"
    finally:
        srv.shutdown()
        srv.server_close()


def test_unreachable_network_printer_returns_502(config: AgentConfig) -> None:
    # A closed local port: connection is refused immediately.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]
    assert config.receipt is not None
    printer = replace(config.receipt, host="127.0.0.1", port=closed_port, timeout_s=2)
    srv = AgentServer(replace(config, dry_run=False, receipt=printer))
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        client = Client(srv)
        resp = client.request("POST", "/print/receipt", receipt_payload(), client.auth())
        assert resp.status == 502
        body = resp.json()
        assert body["code"] == "PRINTER_UNAVAILABLE"
        assert body["details"]["printer"] == "receipt_printer"
    finally:
        srv.shutdown()
        srv.server_close()


def test_real_network_printer_receives_bytes(config: AgentConfig) -> None:
    """A fake raw-9100 printer: the agent must deliver exactly the rendered bytes."""
    received = bytearray()
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    def accept() -> None:
        conn, _ = listener.accept()
        with conn:
            while chunk := conn.recv(65536):
                received.extend(chunk)

    sink = threading.Thread(target=accept, daemon=True)
    sink.start()
    assert config.receipt is not None
    printer = replace(config.receipt, host="127.0.0.1", port=port, timeout_s=5)
    srv = AgentServer(replace(config, dry_run=False, receipt=printer))
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        client = Client(srv)
        resp = client.request("POST", "/print/receipt", receipt_payload(), client.auth())
        assert resp.status == 200, resp.body
        sink.join(timeout=5)
        assert resp.json()["bytes"] == len(received)
        assert bytes(received).startswith(b"\x1b@")
    finally:
        srv.shutdown()
        srv.server_close()
        listener.close()


@pytest.mark.parametrize("path", ["/health", "/print/receipt"])
def test_error_responses_close_connection(client: Client, path: str) -> None:
    resp = client.request("POST", path, receipt_payload())
    assert resp.headers.get("connection") == "close"
