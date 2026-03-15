from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class CompanyTarget:
    name: str
    careers_url: str
    api_post: dict[str, Any] | None = None


@dataclass
class JobResult:
    company: str
    title: str
    url: str
    source: str
    location: str = ""
    job_id: str = ""
    careers_url: str = ""
    posted_at: datetime | None = None
