from __future__ import annotations

from datetime import datetime
from typing import Literal

from ninja import Schema


class HealthOut(Schema):
    status: Literal["ok", "degraded"]
    db: Literal["ok", "error"]
    version: str
    time: datetime
