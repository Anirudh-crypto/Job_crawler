from __future__ import annotations

import json
from urllib.parse import urlparse

from ..http_client import HttpClient
from ..models import CompanyTarget, JobResult
from ..relevance import JobRelevance
from ..dates import parse_epoch_ms, parse_iso_datetime
from ..text import extract_job_id, normalize_url


class LeverProvider:
    def __init__(self, http: HttpClient, relevance: JobRelevance) -> None:
        self.http = http
        self.relevance = relevance

    def fetch(self, target: CompanyTarget) -> list[JobResult]:
        parsed = urlparse(target.careers_url)
        if "lever.co" not in parsed.netloc.lower():
            return []

        company_slug = parsed.path.strip("/").split("/")[0]
        if not company_slug:
            return []

        api_url = f"https://api.lever.co/v0/postings/{company_slug}?mode=json"
        response = self.http.get(api_url)
        if response is None:
            return []

        try:
            postings = response.json()
        except json.JSONDecodeError:
            return []

        jobs: list[JobResult] = []
        for item in postings:
            title = str(item.get("text", "")).strip()
            url = str(item.get("hostedUrl", "")).strip()
            location = str(item.get("categories", {}).get("location", "")).strip()
            experience_text = " ".join(
                part.strip()
                for part in [
                    title,
                    str(item.get("descriptionPlain", "") or ""),
                    str(item.get("description", "") or ""),
                    str(item.get("additionalPlain", "") or ""),
                ]
                if isinstance(part, str) and part.strip()
            )
            posted_at = parse_epoch_ms(item.get("createdAt")) or parse_iso_datetime(
                str(item.get("createdAt") or "")
            )
            if not title or not url:
                continue
            if not self.relevance.is_relevant(title):
                continue
            if not self.relevance.has_role_indicator(title):
                continue

            jobs.append(
                JobResult(
                    company=target.name,
                    title=title,
                    url=normalize_url(
                        url,
                        remove_tracking=False,
                        drop_fragment=False,
                        trim_trailing_slash=False,
                    ),
                    source="lever-api",
                    location=location,
                    job_id=str(item.get("reqCode") or item.get("id") or "") or extract_job_id(title),
                    careers_url=target.careers_url,
                    experience_text=experience_text,
                    posted_at=posted_at,
                )
            )
        return jobs
