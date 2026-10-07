"""Agent configuration: a TOML file, validated strictly at startup.

The agent refuses to start on anything unsafe (non-loopback bind, weak or placeholder token)
so that a misconfigured workstation fails loudly instead of exposing a print API on the LAN.
"""

from __future__ import annotations

import ipaddress
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from escpos.capabilities import get_profile

Transport = Literal["usb", "network", "file", "win32"]
LabelLanguage = Literal["zpl", "escpos"]

TRANSPORTS: tuple[str, ...] = ("usb", "network", "file", "win32")
LABEL_LANGUAGES: tuple[str, ...] = ("zpl", "escpos")
LOOPBACK_NAMES = frozenset({"localhost"})
MIN_TOKEN_LENGTH = 24
PLACEHOLDER_MARKERS = ("change-me", "changeme", "replace-me", "example")


class ConfigError(ValueError):
    """Raised for any invalid configuration value; the message names the offending key."""


@dataclass(frozen=True, slots=True)
class PrinterConfig:
    name: str
    transport: Transport
    profile: str = "default"
    columns: int = 48
    host: str = ""
    port: int = 9100
    timeout_s: float = 10.0
    vendor_id: int = 0
    product_id: int = 0
    in_ep: int = 0x82
    out_ep: int = 0x01
    device_path: str = ""
    win32_printer: str = ""
    cut: bool = True
    qr_native: bool = True
    # Label printers only.
    language: LabelLanguage = "zpl"
    width_mm: float = 50.0
    height_mm: float = 25.0
    dpi: int = 203


@dataclass(frozen=True, slots=True)
class AgentConfig:
    host: str
    port: int
    token: str
    allowed_origins: frozenset[str]
    dry_run: bool
    dry_run_dir: Path
    max_body_bytes: int = 65536
    receipt: PrinterConfig | None = None
    label: PrinterConfig | None = None
    source: Path | None = field(default=None, compare=False)


def is_loopback(host: str) -> bool:
    if host in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _table(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise ConfigError(f"[{key}] must be a table")
    return value


def _get(
    table: dict[str, Any], section: str, key: str, kind: type | tuple[type, ...], default: Any
) -> Any:
    value = table.get(key, default)
    # bool is a subclass of int; never accept it where a number is expected.
    if isinstance(value, bool) and kind is not bool:
        raise ConfigError(f"{section}.{key} must be {_kind_name(kind)}")
    if not isinstance(value, kind):
        raise ConfigError(f"{section}.{key} must be {_kind_name(kind)}")
    return value


def _kind_name(kind: type | tuple[type, ...]) -> str:
    if isinstance(kind, tuple):
        return " or ".join(k.__name__ for k in kind)
    return kind.__name__


def _port(value: int, where: str) -> int:
    if not 1 <= value <= 65535:
        raise ConfigError(f"{where} must be between 1 and 65535")
    return value


def _origin(value: str) -> str:
    parts = urlsplit(value)
    if (
        parts.scheme not in ("http", "https")
        or not parts.netloc
        or parts.path not in ("", "/")
        or parts.query
        or parts.fragment
    ):
        raise ConfigError(
            f"server.allowed_origins entry {value!r} must look like http(s)://host[:port]"
        )
    return f"{parts.scheme}://{parts.netloc}".lower()


def _token(server: dict[str, Any], base: Path) -> str:
    token: str = _get(server, "server", "token", str, "")
    token_file: str = _get(server, "server", "token_file", str, "")
    if token and token_file:
        raise ConfigError("set only one of server.token and server.token_file")
    if token_file:
        path = Path(token_file)
        if not path.is_absolute():
            path = base / path
        try:
            token = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ConfigError(f"server.token_file {path} cannot be read: {exc}") from exc
    if not token:
        raise ConfigError("server.token (or server.token_file) is required")
    if len(token) < MIN_TOKEN_LENGTH:
        raise ConfigError(f"server.token must be at least {MIN_TOKEN_LENGTH} characters")
    lowered = token.lower()
    if any(marker in lowered for marker in PLACEHOLDER_MARKERS):
        raise ConfigError("server.token still contains the example placeholder; generate one")
    return token


def _printer(data: dict[str, Any], section: str, *, is_label: bool) -> PrinterConfig | None:
    table = _table(data, section)
    if not table or not _get(table, section, "enabled", bool, True):
        return None
    transport = _get(table, section, "transport", str, "")
    if transport not in TRANSPORTS:
        raise ConfigError(f"{section}.transport must be one of {', '.join(TRANSPORTS)}")
    columns = _get(table, section, "columns", int, 48)
    if not 24 <= columns <= 64:
        raise ConfigError(f"{section}.columns must be between 24 and 64")
    timeout_s = float(_get(table, section, "timeout_s", (int, float), 10.0))
    if not 0 < timeout_s <= 120:
        raise ConfigError(f"{section}.timeout_s must be in (0, 120]")
    language = _get(table, section, "language", str, "zpl" if is_label else "escpos")
    if is_label and language not in LABEL_LANGUAGES:
        raise ConfigError(f"{section}.language must be one of {', '.join(LABEL_LANGUAGES)}")
    width_mm = float(_get(table, section, "width_mm", (int, float), 50.0))
    height_mm = float(_get(table, section, "height_mm", (int, float), 25.0))
    dpi = _get(table, section, "dpi", int, 203)
    if not (10 <= width_mm <= 120 and 10 <= height_mm <= 300):
        raise ConfigError(f"{section}.width_mm/height_mm out of range")
    if dpi not in (152, 203, 300, 600):
        raise ConfigError(f"{section}.dpi must be one of 152, 203, 300, 600")

    printer = PrinterConfig(
        name=section,
        transport=transport,  # validated against TRANSPORTS above
        profile=_get(table, section, "profile", str, "default"),
        columns=columns,
        host=_get(table, section, "host", str, ""),
        port=_port(_get(table, section, "port", int, 9100), f"{section}.port"),
        timeout_s=timeout_s,
        vendor_id=_get(table, section, "vendor_id", int, 0),
        product_id=_get(table, section, "product_id", int, 0),
        in_ep=_get(table, section, "in_ep", int, 0x82),
        out_ep=_get(table, section, "out_ep", int, 0x01),
        device_path=_get(table, section, "device_path", str, ""),
        win32_printer=_get(table, section, "win32_printer", str, ""),
        cut=_get(table, section, "cut", bool, True),
        qr_native=_get(table, section, "qr_native", bool, True),
        language=language if is_label else "escpos",
        width_mm=width_mm,
        height_mm=height_mm,
        dpi=dpi,
    )
    _check_profile(section, printer.profile)
    required = {
        "network": ("host", printer.host),
        "file": ("device_path", printer.device_path),
        "win32": ("win32_printer", printer.win32_printer),
    }
    if transport in required and not required[transport][1]:
        raise ConfigError(f"{section}.{required[transport][0]} is required for {transport}")
    if transport == "usb" and not (printer.vendor_id and printer.product_id):
        raise ConfigError(f"{section}.vendor_id and {section}.product_id are required for usb")
    return printer


def _check_profile(section: str, name: str) -> None:
    try:
        get_profile(name)
    except Exception as exc:  # python-escpos raises its own NotSupported type
        raise ConfigError(
            f"{section}.profile {name!r} is not a known python-escpos profile"
        ) from exc


def load_config(path: Path) -> AgentConfig:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError(f"invalid TOML in {path}: {exc}") from exc
    return parse_config(data, base=path.resolve().parent, source=path)


def parse_config(data: dict[str, Any], *, base: Path, source: Path | None = None) -> AgentConfig:
    server = _table(data, "server")
    host = _get(server, "server", "host", str, "127.0.0.1")
    if not is_loopback(host):
        raise ConfigError("server.host must be a loopback address (127.0.0.1, ::1 or localhost)")
    port = _port(_get(server, "server", "port", int, 9123), "server.port")
    origins = _get(server, "server", "allowed_origins", list, [])
    if not all(isinstance(o, str) for o in origins):
        raise ConfigError("server.allowed_origins must be a list of strings")
    dry_run_dir = Path(_get(server, "server", "dry_run_dir", str, "print-out"))
    if not dry_run_dir.is_absolute():
        dry_run_dir = base / dry_run_dir
    max_body = _get(server, "server", "max_body_bytes", int, 65536)
    if not 1024 <= max_body <= 1_048_576:
        raise ConfigError("server.max_body_bytes must be between 1024 and 1048576")

    return AgentConfig(
        host=host,
        port=port,
        token=_token(server, base),
        allowed_origins=frozenset(_origin(o) for o in origins),
        dry_run=_get(server, "server", "dry_run", bool, False),
        dry_run_dir=dry_run_dir,
        max_body_bytes=max_body,
        receipt=_printer(data, "receipt_printer", is_label=False),
        label=_printer(data, "label_printer", is_label=True),
        source=source,
    )
