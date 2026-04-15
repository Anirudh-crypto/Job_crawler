from __future__ import annotations

import json
from urllib.parse import parse_qsl, urlparse

from ..http_client import HttpClient
from ..models import CompanyTarget, JobResult
from ..relevance import JobRelevance
from ..dates import parse_iso_datetime
from ..text import extract_job_id, normalize_url


class GreenhouseProvider:
    def __init__(self, http: HttpClient, relevance: JobRelevance) -> None:
        self.http = http
        self.relevance = relevance

    def fetch(self, target: CompanyTarget) -> list[JobResult]:
        parsed = urlparse(target.careers_url)
        if "greenhouse.io" not in parsed.netloc.lower():
            return []

        token = ""
        if parsed.path.strip("/"):
            token = parsed.path.strip("/").split("/")[0]
        if not token:
            query = dict(parse_qsl(parsed.query))
            token = query.get("for", "")
        if not token:
            return []

        api_url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
        response = self.http.get(api_url)
        if response is None:
            return []

        try:
            payload = response.json()
        except json.JSONDecodeError:
            return []

        jobs: list[JobResult] = []
        for item in payload.get("jobs", []):
            title = str(item.get("title", "")).strip()
            url = str(item.get("absolute_url", "")).strip()
            location = str(item.get("location", {}).get("name", "")).strip()
            experience_text = str(item.get("content", "") or item.get("internal_job_id", "") or "").strip()
            posted_at = parse_iso_datetime(str(item.get("updated_at") or item.get("created_at") or ""))
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
                    source="greenhouse-api",
                    location=location,
                    job_id=str(item.get("requisition_id") or item.get("id") or "") or extract_job_id(title),
                    careers_url=target.careers_url,
                    experience_text=f"{title} {experience_text}".strip(),
                    posted_at=posted_at,
                )
            )
        return jobs
