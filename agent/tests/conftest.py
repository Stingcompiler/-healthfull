from __future__ import annotations

import http.client
import json
import threading
from collections.abc import Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

from hospital_agent.config import AgentConfig, PrinterConfig, parse_config
from hospital_agent.server import AgentServer, make_server

TOKEN = "test-token-0123456789-abcdefghij"  # test value only
ORIGIN = "http://hospital.test"


def base_config(tmp_path: Path, **server_overrides: Any) -> dict[str, Any]:
    server: dict[str, Any] = {
        "host": "127.0.0.1",
        "port": 9123,
        "token": TOKEN,
        "allowed_origins": [ORIGIN],
        "dry_run": True,
        "dry_run_dir": str(tmp_path / "out"),
    }
    server.update(server_overrides)
    return {
        "server": server,
        "receipt_printer": {"transport": "network", "host": "192.0.2.10", "profile": "TM-T20II"},
        "label_printer": {"transport": "network", "host": "192.0.2.11", "language": "zpl"},
    }


@pytest.fixture
def config(tmp_path: Path) -> AgentConfig:
    cfg = parse_config(base_config(tmp_path), base=tmp_path)
    # Port 0: the OS picks a free port so tests can run in parallel.
    return replace(cfg, port=0)


@pytest.fixture
def receipt_printer(config: AgentConfig) -> PrinterConfig:
    assert config.receipt is not None
    return config.receipt


@dataclass
class Response:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body)


class Client:
    def __init__(self, server: AgentServer) -> None:
        self.port = server.bound_port

    def request(
        self,
        method: str,
        path: str,
        body: Any = None,
        headers: dict[str, str] | None = None,
        raw: bytes | None = None,
    ) -> Response:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            payload = (
                raw
                if raw is not None
                else (json.dumps(body).encode() if body is not None else None)
            )
            all_headers = {"Host": f"127.0.0.1:{self.port}"}
            if payload is not None:
                all_headers["Content-Type"] = "application/json"
            all_headers.update(headers or {})
            conn.request(method, path, body=payload, headers=all_headers)
            resp = conn.getresponse()
            return Response(resp.status, {k.lower(): v for k, v in resp.getheaders()}, resp.read())
        finally:
            conn.close()

    def auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def server(config: AgentConfig) -> Iterator[AgentServer]:
    srv = make_server(config)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


@pytest.fixture
def client(server: AgentServer) -> Client:
    return Client(server)


def receipt_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "receipt_no": "RC-2026-000123",
        "issued_at": "2026-10-06 10:15",
        "center": {"name": "Test Medical Center", "address": "Khartoum", "phone": "0912345678"},
        "patient": {"name": "Test Patient", "file_no": "000123"},
        "cashier": "cashier",
        "lines": [
            {"description": "Consultation - general practice", "qty": "1", "amount": "10000.00"},
            {"description": "CBC", "qty": "1", "amount": "4500.50"},
        ],
        "total": "14500.50",
        "paid": "14500.50",
        "method": "cash",
        "qr": "RC-2026-000123",
        "footer": "Thank you",
    }
    payload.update(overrides)
    return payload
