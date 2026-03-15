from __future__ import annotations

from datetime import datetime
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..dates import parse_human_date
from ..http_client import HttpClient
from ..models import CompanyTarget, JobResult
from ..relevance import JobRelevance
from ..text import extract_job_id, normalize_text, normalize_url


class SuccessFactorsProvider:
    def __init__(self, http: HttpClient, relevance: JobRelevance) -> None:
        self.http = http
        self.relevance = relevance

    def fetch(self, target: CompanyTarget) -> list[JobResult]:
        parsed = urlparse(target.careers_url)
        host = parsed.netloc.lower()
        if "jobs.sap.com" not in host and "successfactors.com" not in host:
            return []

        response = self.http.get(target.careers_url)
        if response is None:
            return []
        if "text/html" not in response.headers.get("content-type", "").lower():
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        jobs: list[JobResult] = []
        for anchor in soup.find_all("a", href=True):
            href = anchor.get("href", "")
            if "/job/" not in href:
                continue
            title = anchor.get_text(" ", strip=True)
            if not title:
                continue
            if not self.relevance.is_relevant(title) or not self.relevance.has_role_indicator(title):
                continue

            job_url = normalize_url(
                urljoin(response.url, href),
                remove_tracking=False,
                drop_fragment=False,
                trim_trailing_slash=False,
            )
            location, posted_at = self._extract_context(anchor, title)
            jobs.append(
                JobResult(
                    company=target.name,
                    title=title,
                    url=job_url,
                    source="successfactors-html",
                    location=location,
                    job_id=extract_job_id(f"{title} {job_url}"),
                    careers_url=target.careers_url,
                    posted_at=posted_at,
                )
            )
        return jobs

    def _extract_context(self, anchor, title: str) -> tuple[str, datetime | None]:
        parent = anchor.find_parent("tr") or anchor.find_parent("li") or anchor.find_parent("div")
        if not parent:
            return "", None
        context = parent.get_text(" | ", strip=True)
        parts = [p.strip() for p in context.split("|") if p.strip()]
        normalized_title = normalize_text(title)
        parts = [p for p in parts if normalize_text(p) != normalized_title]
        location = ""
        posted_at = None
        for part in parts:
            if posted_at is None:
                posted_at = parse_human_date(part)
            if not location and "," in part:
                location = part
        return location, posted_at
