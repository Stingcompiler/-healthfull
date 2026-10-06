from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hospital_agent.config import ConfigError, load_config, parse_config

from .conftest import TOKEN, base_config


def parse(tmp_path: Path, data: dict[str, Any]) -> Any:
    return parse_config(data, base=tmp_path)


def test_example_config_is_valid_after_setting_a_token(tmp_path: Path) -> None:
    example = Path(__file__).resolve().parents[1] / "config.example.toml"
    text = example.read_text(encoding="utf-8").replace(
        'token = "change-me-generate-a-long-random-token"', f'token = "{TOKEN}"'
    )
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    cfg = load_config(path)
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 9123
    assert cfg.dry_run is True
    assert cfg.dry_run_dir == tmp_path / "print-out"
    assert cfg.receipt is not None and cfg.receipt.columns == 48
    assert cfg.label is not None and cfg.label.language == "zpl"


def test_example_config_placeholder_token_is_rejected() -> None:
    example = Path(__file__).resolve().parents[1] / "config.example.toml"
    with pytest.raises(ConfigError, match="placeholder"):
        load_config(example)


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "example.org", "::"])  # noqa: S104
def test_non_loopback_bind_is_refused(tmp_path: Path, host: str) -> None:
    with pytest.raises(ConfigError, match="loopback"):
        parse(tmp_path, base_config(tmp_path, host=host))


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost", "127.0.0.2"])
def test_loopback_bind_is_accepted(tmp_path: Path, host: str) -> None:
    assert parse(tmp_path, base_config(tmp_path, host=host)).host == host


@pytest.mark.parametrize("token", ["", "short", "x" * 23])
def test_weak_token_is_refused(tmp_path: Path, token: str) -> None:
    with pytest.raises(ConfigError, match="token"):
        parse(tmp_path, base_config(tmp_path, token=token))


def test_token_file_relative_to_config(tmp_path: Path) -> None:
    (tmp_path / "agent-token.txt").write_text(TOKEN + "\n", encoding="utf-8")
    data = base_config(tmp_path)
    del data["server"]["token"]
    data["server"]["token_file"] = "agent-token.txt"
    assert parse(tmp_path, data).token == TOKEN


def test_token_and_token_file_are_exclusive(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="only one"):
        parse(tmp_path, base_config(tmp_path, token_file="x.txt"))


@pytest.mark.parametrize("origin", ["hospital.lan", "ftp://hospital.lan", "http://h.lan/app"])
def test_bad_origin_is_refused(tmp_path: Path, origin: str) -> None:
    with pytest.raises(ConfigError, match="allowed_origins"):
        parse(tmp_path, base_config(tmp_path, allowed_origins=[origin]))


def test_origins_are_normalised(tmp_path: Path) -> None:
    cfg = parse(tmp_path, base_config(tmp_path, allowed_origins=["HTTP://Hospital.LAN:8080/"]))
    assert cfg.allowed_origins == frozenset({"http://hospital.lan:8080"})


def test_bool_is_not_a_port(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"server\.port"):
        parse(tmp_path, base_config(tmp_path, port=True))


def test_printer_transport_requirements(tmp_path: Path) -> None:
    data = base_config(tmp_path)
    data["receipt_printer"] = {"transport": "usb"}
    with pytest.raises(ConfigError, match="vendor_id"):
        parse(tmp_path, data)
    data["receipt_printer"] = {"transport": "network"}
    with pytest.raises(ConfigError, match="host"):
        parse(tmp_path, data)
    data["receipt_printer"] = {"transport": "serial"}
    with pytest.raises(ConfigError, match="transport"):
        parse(tmp_path, data)
    data["receipt_printer"] = {"transport": "usb", "vendor_id": 0x0416, "product_id": 0x5011}
    printer = parse(tmp_path, data).receipt
    assert printer is not None and printer.vendor_id == 0x0416


def test_unknown_profile_is_refused(tmp_path: Path) -> None:
    data = base_config(tmp_path)
    data["receipt_printer"]["profile"] = "No-Such-Printer"
    with pytest.raises(ConfigError, match="profile"):
        parse(tmp_path, data)


def test_disabled_or_missing_printers(tmp_path: Path) -> None:
    data = base_config(tmp_path)
    data["receipt_printer"]["enabled"] = False
    del data["label_printer"]
    cfg = parse(tmp_path, data)
    assert cfg.receipt is None
    assert cfg.label is None


def test_invalid_toml_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[server\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid TOML"):
        load_config(path)
