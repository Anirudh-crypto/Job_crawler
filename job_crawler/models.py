from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CompanyTarget:
    name: str
    careers_url: str


@dataclass
class JobResult:
    company: str
    title: str
    url: str
    source: str
    location: str = ""
    job_id: str = ""
    careers_url: str = ""
