# hospital-agent: local device agent

A small HTTP service that runs on a workstation (cashier, lab, pharmacy) and prints to the thermal
receipt printer and the label printer attached to it. The hospital-sys web app, open in that
workstation's browser, calls it on `http://127.0.0.1:9123`. FEATURES.md 0.11.

- Python 3.12, stdlib HTTP server, [python-escpos](https://python-escpos.readthedocs.io/) for ESC/POS.
- Binds to loopback only. Every print call needs `Authorization: Bearer <token>`.
- Dry-run mode writes each job's bytes to a file instead of a printer (setup, training, tests).
- Packaged as one executable with PyInstaller; no Python install needed on the workstation.

## API

| Method | Path | Auth | Body | Result |
|---|---|---|---|---|
| GET | `/health` | none | | `{status, version, dry_run, printers: {receipt, label}}` |
| POST | `/print/receipt` | Bearer | receipt JSON (below) | `{job_id, printer, dry_run, bytes, output?}` |
| POST | `/print/label` | Bearer | `{lines: [..≤6], barcode?, copies?}` | same as above |

Errors use the main API's shape `{code, message, details}`:
`AGENT_UNAUTHORIZED` 401, `AGENT_ORIGIN_DENIED` / `AGENT_BAD_HOST` 403, `NOT_FOUND` 404,
`AGENT_BAD_CONTENT_TYPE` 415, `AGENT_BODY_TOO_LARGE` 413, `AGENT_BAD_JSON` 400,
`AGENT_INVALID_PAYLOAD` 422 (`details.field` names the field), `PRINTER_NOT_CONFIGURED` 503,
`PRINTER_UNAVAILABLE` 502.

Receipt body (money is always a decimal string computed by the backend; the agent only formats it):

```json
{
  "receipt_no": "RC-2026-000123",
  "issued_at": "2026-10-06 10:15",
  "center": {"name": "Center name", "address": "Khartoum", "phone": "0912345678"},
  "patient": {"name": "Patient name", "file_no": "000123"},
  "cashier": "cashier1",
  "lines": [{"description": "Consultation", "qty": "1", "amount": "10000.00"}],
  "total": "10000.00",
  "paid": "10000.00",
  "method": "cash",
  "reference": "",
  "currency": "SDG",
  "qr": "RC-2026-000123",
  "footer": "Thank you",
  "copies": 1
}
```

Browser access: the web app's origin must be listed in `server.allowed_origins`. The agent answers
CORS preflights and Chrome's Private Network Access preflight
(`Access-Control-Allow-Private-Network`). Chrome may ask the user once to allow the page to reach
local devices. Requests with a `Host` other than the loopback address are refused (DNS rebinding).

## Configure

```bash
cp config.example.toml config.toml
python -c "import secrets; print(secrets.token_urlsafe(32))"   # paste into server.token
hospital-agent --config config.toml --check                     # validates and exits
```

Transports: `network` (raw TCP 9100, recommended), `usb` (libusb; Linux), `file` (`/dev/usb/lp0`),
`win32` (a Windows printer queue, sent RAW through the spooler). Label language: `zpl` (Zebra and
compatible) or `escpos`.

## Develop

```bash
uv sync
uv run pytest            # all printers in dry-run or against a fake raw-9100 socket
uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run hospital-agent --config config.toml -v
```

From the repo root: `make agent-test`, `make agent-lint`.

## Build a single executable (PyInstaller)

Build on the target OS (PyInstaller does not cross-compile): Windows for Windows workstations,
Linux for Linux ones.

```bash
uv sync --group build
uv run --group build pyinstaller --noconfirm --clean --onefile --name hospital-agent \
  --paths src --collect-data escpos packaging/entry.py
# Output: dist/hospital-agent (dist\hospital-agent.exe on Windows)
dist/hospital-agent --version
```

`--collect-data escpos` bundles python-escpos's printer capability database; without it every
profile lookup fails. Place `config.toml` next to the executable (or set `HOSPITAL_AGENT_CONFIG`).

Run at login: on Windows, a Task Scheduler task "At log on" running
`hospital-agent.exe --config C:\HospitalAgent\config.toml`; on Linux, a systemd user service.

## Known limits

- Receipts print in ESC/POS text mode with English labels. Arabic text is sent through the
  printer's Arabic code page without contextual shaping or right-to-left reordering, so it is not
  reliably readable. Arabic receipts need raster (image) printing; that is a planned addition. Until
  then, print Arabic documents from the browser (A4 or 80mm print CSS).
- One job at a time per printer (a lock serialises jobs); no persistent queue. A failed job returns
  `PRINTER_UNAVAILABLE` and the web app decides whether to retry.
