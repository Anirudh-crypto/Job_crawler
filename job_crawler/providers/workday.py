from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from ..dates import parse_workday_posted
from ..http_client import HttpClient
from ..location import LocationFilter
from ..models import CompanyTarget, JobResult
from ..relevance import JobRelevance
from ..text import extract_job_id, extract_workday_site, is_allowed_url, normalize_text, normalize_url


class WorkdayProvider:
    def __init__(
        self,
        http: HttpClient,
        relevance: JobRelevance,
        location_filter: LocationFilter,
        max_rows: int = 1000,
        page_limit: int = 20,
    ) -> None:
        self.http = http
        self.relevance = relevance
        self.location_filter = location_filter
        self.max_rows = max_rows
        # Many Workday endpoints reject limits larger than 20.
        self.page_limit = min(page_limit, 20)

    def fetch(self, target: CompanyTarget) -> list[JobResult]:
        parsed = urlparse(target.careers_url)
        host = parsed.netloc.lower()
        if "myworkdayjobs.com" not in host:
            return []

        site = extract_workday_site(parsed.path)
        tenant = host.split(".")[0]
        if not site or not tenant:
            return []

        api_url = f"https://{parsed.netloc}/wday/cxs/{tenant}/{site}/jobs"
        initial_response = self.http.post_json(api_url, self._build_payload(offset=0))
        if initial_response is None:
            return []

        try:
            initial_payload = initial_response.json()
        except json.JSONDecodeError:
            return []

        facet_queries = self._build_location_queries(initial_payload)
        postings: list[dict[str, Any]] = []
        if facet_queries:
            for applied_facets in facet_queries:
                postings.extend(self._fetch_paginated(api_url, applied_facets=applied_facets))
        else:
            postings.extend(self._fetch_paginated(api_url, first_page_payload=initial_payload))

        jobs = [job for job in (self._to_job_result(target, parsed.netloc, item) for item in postings) if job]
        return self._dedupe_jobs(jobs)

    def _build_payload(
        self,
        offset: int,
        applied_facets: dict[str, list[str]] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"limit": self.page_limit, "offset": offset, "searchText": ""}
        if applied_facets:
            payload["appliedFacets"] = applied_facets
        return payload

    def _fetch_paginated(
        self,
        api_url: str,
        applied_facets: dict[str, list[str]] | None = None,
        first_page_payload: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        offset = 0
        postings: list[dict[str, Any]] = []

        while offset < self.max_rows:
            if first_page_payload is not None and offset == 0 and not applied_facets:
                payload = first_page_payload
            else:
                response = self.http.post_json(
                    api_url,
                    self._build_payload(offset=offset, applied_facets=applied_facets),
                )
                if response is None:
                    break
                try:
                    payload = response.json()
                except json.JSONDecodeError:
                    break

            chunk = payload.get("jobPostings", [])
            if not chunk:
                break
            postings.extend(chunk)

            offset += len(chunk)
            if len(chunk) < self.page_limit:
                break

        return postings

    def _to_job_result(
        self,
        target: CompanyTarget,
        hostname: str,
        item: dict[str, Any],
    ) -> JobResult | None:
        title = str(item.get("title", "")).strip()
        if not title:
            return None
        if not self.relevance.is_relevant(title):
            return None
        if not self.relevance.has_role_indicator(title):
            return None

        external_path = str(item.get("externalPath", "")).strip()
        if not external_path:
            return None
        if is_allowed_url(external_path):
            job_url = normalize_url(
                external_path,
                remove_tracking=False,
                drop_fragment=False,
                trim_trailing_slash=False,
            )
        else:
            job_url = normalize_url(
                f"https://{hostname}{external_path}",
                remove_tracking=False,
                drop_fragment=False,
                trim_trailing_slash=False,
            )

        location = str(item.get("locationsText", "")).strip()
        posted_at = parse_workday_posted(str(item.get("postedOn", "") or ""))
        experience_text = " ".join(
            str(value).strip()
            for value in [title, *list(item.get("bulletFields", []) or [])]
            if str(value).strip()
        )
        job_id = ""
        for entry in item.get("bulletFields", []) or []:
            job_id = extract_job_id(str(entry))
            if job_id:
                break
        if not job_id:
            job_id = extract_job_id(f"{title} {external_path}")

        job = JobResult(
            company=target.name,
            title=title,
            url=job_url,
            source="workday-api",
            location=location,
            job_id=job_id,
            careers_url=target.careers_url,
            experience_text=experience_text,
            posted_at=posted_at,
        )
        if self.location_filter.enabled and not self.location_filter.matches_job(job):
            return None
        return job

    def _dedupe_jobs(self, jobs: list[JobResult]) -> list[JobResult]:
        deduped: dict[str, JobResult] = {}
        for job in jobs:
            key = normalize_url(job.url).lower()
            if key not in deduped:
                deduped[key] = job
        return list(deduped.values())

    def _build_location_queries(self, payload: dict[str, Any]) -> list[dict[str, list[str]]]:
        if not self.location_filter.enabled:
            return []

        groups = self._extract_location_groups(payload)
        if not groups:
            return []

        queries: list[dict[str, list[str]]] = []
        for term in self.location_filter.workday_terms():
            country_ids = self._exact_descriptor_ids(groups.get("locationHierarchy1", []), term)
            if country_ids:
                queries.append({"locationHierarchy1": country_ids})
                continue

            site_ids = self._site_descriptor_ids(groups.get("locations", []), term)
            if site_ids:
                queries.append({"locations": site_ids})

        return self._dedupe_queries(queries)

    def _extract_location_groups(self, payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        facets = payload.get("facets", [])
        location_main = next(
            (facet for facet in facets if facet.get("facetParameter") == "locationMainGroup"),
            None,
        )
        if not isinstance(location_main, dict):
            return {}

        groups: dict[str, list[dict[str, Any]]] = {}
        for group in location_main.get("values", []):
            if not isinstance(group, dict):
                continue
            facet_parameter = group.get("facetParameter")
            values = group.get("values", [])
            if facet_parameter and isinstance(values, list):
                groups[facet_parameter] = values
        return groups

    def _exact_descriptor_ids(self, values: list[dict[str, Any]], term: str) -> list[str]:
        ids: list[str] = []
        for item in values:
            descriptor = normalize_text(str(item.get("descriptor", "")))
            facet_id = str(item.get("id", "")).strip()
            if descriptor == term and facet_id:
                ids.append(facet_id)
        return sorted(set(ids))

    def _site_descriptor_ids(self, values: list[dict[str, Any]], term: str) -> list[str]:
        ids: list[str] = []
        for item in values:
            descriptor = normalize_text(str(item.get("descriptor", "")))
            facet_id = str(item.get("id", "")).strip()
            if not facet_id:
                continue
            if term and term in descriptor:
                ids.append(facet_id)
        return sorted(set(ids))

    def _dedupe_queries(self, queries: list[dict[str, list[str]]]) -> list[dict[str, list[str]]]:
        deduped: list[dict[str, list[str]]] = []
        seen: set[str] = set()
        for query in queries:
            cleaned = {key: sorted(set(values)) for key, values in query.items() if values}
            if not cleaned:
                continue
            marker = json.dumps(cleaned, sort_keys=True)
            if marker in seen:
                continue
            seen.add(marker)
            deduped.append(cleaned)
        return deduped
