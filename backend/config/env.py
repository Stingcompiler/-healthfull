"""Tiny typed helpers for reading configuration from environment variables."""

from __future__ import annotations

import ipaddress
import os
from collections.abc import Mapping

from django.core.exceptions import ImproperlyConfigured

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off", ""}


def env_str(name: str, default: str, environ: Mapping[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    return env.get(name, default)


def env_bool(name: str, default: bool, environ: Mapping[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    raw = env.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ImproperlyConfigured(f"{name} must be a boolean (1/0/true/false), got {raw!r}")


def env_int(name: str, default: int, environ: Mapping[str, str] | None = None) -> int:
    env = os.environ if environ is None else environ
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw.strip())
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} must be an integer, got {raw!r}") from exc


def env_list(name: str, default: list[str], environ: Mapping[str, str] | None = None) -> list[str]:
    """Comma-separated list; blank items are dropped."""
    env = os.environ if environ is None else environ
    raw = env.get(name)
    if raw is None:
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


#: Caddy's ``private_ranges`` shorthand, so one value means the same to both (infra/Caddyfile).
PRIVATE_RANGES = (
    "192.168.0.0/16",
    "172.16.0.0/12",
    "10.0.0.0/8",
    "127.0.0.0/8",
    "fd00::/8",
    "::1/128",
)

Network = ipaddress.IPv4Network | ipaddress.IPv6Network


def env_networks(
    name: str, default: str, environ: Mapping[str, str] | None = None
) -> tuple[Network, ...]:
    """IP networks separated by commas or spaces; ``private_ranges`` expands as in Caddy.

    A bare address is a one-host network; host bits are allowed (``172.18.0.1/16``). An
    invalid entry raises ``ImproperlyConfigured`` so a typo fails at start, not silently.
    """
    raw = env_str(name, default, environ)
    networks: list[Network] = []
    for item in raw.replace(",", " ").split():
        for value in PRIVATE_RANGES if item == "private_ranges" else (item,):
            try:
                networks.append(ipaddress.ip_network(value, strict=False))
            except ValueError as exc:
                raise ImproperlyConfigured(
                    f"{name} must list IP networks or private_ranges, got {item!r}"
                ) from exc
    return tuple(networks)
