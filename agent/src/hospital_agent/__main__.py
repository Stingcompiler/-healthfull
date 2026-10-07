"""Command line entry point: `hospital-agent --config config.toml`."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
from pathlib import Path

from . import __version__
from .config import ConfigError, load_config
from .server import make_server

log = logging.getLogger("hospital_agent")


def default_config_path() -> Path:
    env = os.environ.get("HOSPITAL_AGENT_CONFIG")
    if env:
        return Path(env)
    # Next to the executable when frozen by PyInstaller, else the current directory.
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "config.toml"
    return Path.cwd() / "config.toml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hospital-agent", description=__doc__)
    parser.add_argument("--config", type=Path, default=None, help="path to config.toml")
    parser.add_argument("--check", action="store_true", help="validate the config and exit")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    args = parser.parse_args(argv)

    # force=True: python-escpos installs a root handler at import time, which would
    # otherwise turn this call into a no-op and hide our INFO logs.
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )
    path = args.config or default_config_path()
    try:
        config = load_config(path)
    except ConfigError as exc:
        log.error("config error: %s", exc)
        return 2
    if args.check:
        print(f"config OK: {path}")
        return 0

    try:
        server = make_server(config)
    except OSError as exc:
        log.error("cannot listen on %s:%s: %s", config.host, config.port, exc)
        return 1

    def stop(signum: int, _frame: object) -> None:
        log.info("signal %s received, shutting down", signum)
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    log.info(
        "hospital-agent %s listening on http://%s:%s (dry_run=%s, receipt=%s, label=%s)",
        __version__,
        config.host,
        server.bound_port,
        config.dry_run,
        config.receipt.transport if config.receipt else "none",
        config.label.transport if config.label else "none",
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
