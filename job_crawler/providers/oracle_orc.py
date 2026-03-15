from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from ..dates import parse_human_date, parse_iso_datetime
from ..http_client import HttpClient
from ..models import CompanyTarget, JobResult
from ..relevance import JobRelevance
from ..text import extract_job_id, normalize_text, normalize_url


class OracleOrcProvider:
    def __init__(self, http: HttpClient, relevance: JobRelevance) -> None:
        self.http = http
        self.relevance = relevance

    def fetch(self, target: CompanyTarget) -> list[JobResult]:
        parsed = urlparse(target.careers_url)
        host = parsed.netloc.lower()
        if "oracle.com" not in host and "oraclecloud.com" not in host:
            return []

        response = self.http.get(target.careers_url)
        if response is None:
            return []
        if "text/html" not in response.headers.get("content-type", "").lower():
            return []

        config = self._extract_cx_config(response.text)
        if not config:
            return []

        api_base = config.get("apiBaseUrl", "").rstrip("/")
        if not api_base:
            return []

        finder = self._discover_finder(response.text)
        items = self._fetch_requisitions(api_base, finder)
        if not items:
            return []

        jobs: list[JobResult] = []
        for item in items:
            title = self._get_value(item, ["Title", "title", "JobTitle"])
            if not title:
                continue
            if not self.relevance.is_relevant(title) or not self.relevance.has_role_indicator(title):
                continue

            job_url = self._get_value(
                item,
                [
                    "ExternalUrl",
                    "ExternalURL",
                    "ExternalApplyURL",
                    "ExternalApplyUrl",
                    "ApplyUrl",
                    "ApplyURL",
                ],
            )
            if not job_url:
                continue

            location = self._get_value(
                item,
                [
                    "PrimaryLocation",
                    "PrimaryLocationName",
                    "Location",
                    "location",
                    "PrimaryLocationCity",
                ],
            )
            posted_at = self._parse_posted_at(item)
            job_id = self._get_value(item, ["RequisitionNumber", "JobId", "Id", "id"]) or extract_job_id(
                f"{title} {job_url}"
            )

            jobs.append(
                JobResult(
                    company=target.name,
                    title=title,
                    url=normalize_url(
                        job_url,
                        remove_tracking=False,
                        drop_fragment=False,
                        trim_trailing_slash=False,
                    ),
                    source="oracle-orc",
                    location=location,
                    job_id=job_id,
                    careers_url=target.careers_url,
                    posted_at=posted_at,
                )
            )

        return jobs

    def _extract_cx_config(self, html: str) -> dict[str, str]:
        match = re.search(r"CX_CONFIG\\s*=\\s*({.*?});", html, flags=re.S)
        if not match:
            return {}
        raw = match.group(1)
        # Make it JSON-like.
        cleaned = re.sub(r"([A-Za-z0-9_]+)\\s*:", r'\"\\1\":', raw)
        cleaned = cleaned.replace("'", "\"")
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            return {}
        return payload.get("app", {}) if isinstance(payload, dict) else {}

    def _discover_finder(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        scripts = [s.get("src") for s in soup.find_all("script") if s.get("src")]
        for src in scripts:
            if "main-minimal" not in src:
                continue
            bundle = self.http.get(src)
            if bundle is None:
                continue
            match = re.search(r"recruitingCEJobRequisitions[^\\n]*?finder=([A-Za-z0-9_]+)", bundle.text)
            if match:
                return match.group(1)
        return ""

    def _fetch_requisitions(self, api_base: str, finder: str) -> list[dict[str, Any]]:
        endpoint = f"{api_base}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
        offset = 0
        limit = 100
        items: list[dict[str, Any]] = []
        while offset < 1000:
            params = f"onlyData=true&limit={limit}&offset={offset}"
            if finder:
                params += f"&finder={finder}"
            url = f"{endpoint}?{params}"
            response = self.http.get(url)
            if response is None:
                break
            try:
                payload = response.json()
            except json.JSONDecodeError:
                break
            chunk = payload.get("items", [])
            if not chunk:
                break
            items.extend(chunk)
            if not payload.get("hasMore") and len(chunk) < limit:
                break
            offset += len(chunk)
        return items

    def _get_value(self, item: dict[str, Any], keys: list[str]) -> str:
        for key in keys:
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _parse_posted_at(self, item: dict[str, Any]) -> datetime | None:
        for key in ["PostedDate", "PostingStartDate", "datePosted", "DatePosted"]:
            value = item.get(key)
            if not value:
                continue
            parsed = parse_iso_datetime(str(value)) or parse_human_date(str(value))
            if parsed:
                return parsed
        return None
