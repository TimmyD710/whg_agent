from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Listing:
    title: str
    url: str
    source_site: str
    rent_eur: float | None = None
    rooms: float | None = None
    size_m2: float | None = None
    has_balcony_or_garden: bool | None = None
    district: str | None = None
    listed_at: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    site: str
    processed_urls: list[str]
    relevant_listings: list[Listing]
    started_at: datetime
    finished_at: datetime
    error: str | None = None
