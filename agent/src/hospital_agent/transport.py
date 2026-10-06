"""Deliver rendered bytes to a printer, or to a file in dry-run mode.

One lock per printer serialises jobs so two receipts never interleave on the paper.
"""

from __future__ import annotations

import contextlib
import itertools
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from escpos import printer as escpos_printer

from .config import AgentConfig, PrinterConfig


class PrinterUnavailableError(RuntimeError):
    """The printer could not be reached or rejected the job."""


@dataclass(frozen=True, slots=True)
class Delivery:
    job_id: str
    printer: str
    dry_run: bool
    bytes: int
    output: str | None


_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()
_sequence = itertools.count(1)


def _lock_for(name: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(name, threading.Lock())


def new_job_id(kind: str) -> str:
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
    return f"{kind}-{stamp}-{os.getpid()}-{next(_sequence):05d}"


def _open_device(printer: PrinterConfig) -> Any:
    # USB (libusb) and Win32 (pywin32) native libraries load only when those printers open.
    if printer.transport == "network":
        return escpos_printer.Network(printer.host, port=printer.port, timeout=printer.timeout_s)
    if printer.transport == "usb":
        return escpos_printer.Usb(
            printer.vendor_id,
            printer.product_id,
            timeout=int(printer.timeout_s * 1000),
            in_ep=printer.in_ep,
            out_ep=printer.out_ep,
        )
    if printer.transport == "file":
        return escpos_printer.File(printer.device_path)
    if printer.transport == "win32":
        return escpos_printer.Win32Raw(printer.win32_printer)
    raise PrinterUnavailableError(f"unsupported transport {printer.transport}")  # pragma: no cover


def _write_dry_run(directory: Path, job_id: str, data: bytes) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    final = directory / f"{job_id}.bin"
    partial = directory / f".{job_id}.partial"
    partial.write_bytes(data)
    partial.replace(final)  # atomic: readers never see a half-written job
    return final


def deliver(config: AgentConfig, printer: PrinterConfig, kind: str, data: bytes) -> Delivery:
    job_id = new_job_id(kind)
    with _lock_for(printer.name):
        if config.dry_run:
            path = _write_dry_run(config.dry_run_dir, job_id, data)
            return Delivery(job_id, printer.name, True, len(data), str(path))
        device = None
        try:
            device = _open_device(printer)
            device.open()
            device._raw(data)  # python-escpos exposes raw writes only through _raw
        except PrinterUnavailableError:
            raise
        except Exception as exc:  # backend libraries raise many unrelated types
            raise PrinterUnavailableError(
                f"{printer.name} printer ({printer.transport}): {exc}"
            ) from exc
        finally:
            if device is not None:
                # Closing a failed device must not mask the original error.
                with contextlib.suppress(Exception):
                    device.close()
        return Delivery(job_id, printer.name, False, len(data), None)
