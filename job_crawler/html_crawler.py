from __future__ import annotations

import json
from collections import deque
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .constants import JOB_CUE_PHRASES
from .http_client import HttpClient
from .models import CompanyTarget, JobResult
from .relevance import JobRelevance
from .text import (
    extract_job_id,
    is_allowed_url,
    normalize_text,
    normalize_url,
    same_company_scope,
    title_from_url,
)


class HtmlCrawler:
    def __init__(self, http: HttpClient, relevance: JobRelevance) -> None:
        self.http = http
        self.relevance = relevance

    def crawl_company(self, target: CompanyTarget, max_pages: int) -> list[JobResult]:
        start_host = urlparse(target.careers_url).netloc
        queue: deque[str] = deque([target.careers_url])
        visited: set[str] = set()
        jobs: list[JobResult] = []

        while queue and len(visited) < max_pages:
            page_url = queue.popleft()
            if page_url in visited:
                continue
            visited.add(page_url)

            response = self.http.get(page_url)
            if response is None:
                continue
            if "text/html" not in response.headers.get("content-type", "").lower():
                continue

            soup = BeautifulSoup(response.text, "html.parser")
            page_text = self._extract_page_text(soup)
            if any(cue in page_text for cue in ["job", "career", "opening", "hiring", "position"]):
                jobs.extend(
                    self._extract_jobs_from_jsonld(
                        soup,
                        target.name,
                        response.url,
                        target.careers_url,
                    )
                )
                jobs.extend(
                    self._extract_jobs_from_links(
                        soup,
                        target.name,
                        response.url,
                        target.careers_url,
                    )
                )

            for next_page in self._extract_next_pages(soup, response.url, start_host):
                if next_page not in visited and next_page not in queue:
                    queue.append(next_page)

        return jobs

    def _extract_page_text(self, soup: BeautifulSoup) -> str:
        return normalize_text(soup.get_text(" ", strip=True))

    def _looks_like_job_navigation(self, text: str, href: str) -> bool:
        joined = normalize_text(f"{text} {href}")
        return any(cue in joined for cue in JOB_CUE_PHRASES)

    def _flatten_jsonld_job_postings(self, node: Any) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        if isinstance(node, dict):
            node_type = node.get("@type")
            type_values = node_type if isinstance(node_type, list) else [node_type]
            if any(str(value).lower() == "jobposting" for value in type_values if value):
                results.append(node)
            graph = node.get("@graph")
            if graph is not None:
                results.extend(self._flatten_jsonld_job_postings(graph))
        elif isinstance(node, list):
            for item in node:
                results.extend(self._flatten_jsonld_job_postings(item))
        return results

    def _extract_jobs_from_jsonld(
        self,
        soup: BeautifulSoup,
        company_name: str,
        current_url: str,
        careers_url: str,
    ) -> list[JobResult]:
        jobs: list[JobResult] = []
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            raw = (script.string or "").strip()
            if not raw:
                continue

            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue

            for posting in self._flatten_jsonld_job_postings(payload):
                title = str(posting.get("title", "")).strip()
                description = str(posting.get("description", ""))
                combined = f"{title} {description}"
                if not self.relevance.is_relevant(combined):
                    continue
                if not self.relevance.has_role_indicator(combined):
                    continue

                job_url = str(posting.get("url") or posting.get("applyUrl") or current_url).strip()
                if not is_allowed_url(job_url):
                    job_url = current_url

                location = ""
                job_location = posting.get("jobLocation")
                if isinstance(job_location, dict):
                    addr = job_location.get("address", {})
                    if isinstance(addr, dict):
                        locality = addr.get("addressLocality", "")
                        country = addr.get("addressCountry", "")
                        location = ", ".join(part for part in [locality, country] if part)

                jobs.append(
                    JobResult(
                        company=company_name,
                        title=title or title_from_url(job_url),
                        url=normalize_url(
                            job_url,
                            remove_tracking=False,
                            drop_fragment=False,
                            trim_trailing_slash=False,
                        ),
                        source="json-ld",
                        location=location,
                        job_id=extract_job_id(f"{title} {job_url} {description}"),
                        careers_url=careers_url,
                    )
                )

        return jobs

    def _extract_jobs_from_links(
        self,
        soup: BeautifulSoup,
        company_name: str,
        current_url: str,
        careers_url: str,
    ) -> list[JobResult]:
        jobs: list[JobResult] = []
        for anchor in soup.find_all("a", href=True):
            href = anchor.get("href", "").strip()
            if href.startswith(("mailto:", "javascript:", "#")):
                continue

            output_url = normalize_url(
                urljoin(current_url, href),
                remove_tracking=False,
                drop_fragment=False,
                trim_trailing_slash=False,
            )
            if not is_allowed_url(output_url):
                continue

            text = anchor.get_text(" ", strip=True)
            if not text:
                text = anchor.get("aria-label", "").strip()
            if not text:
                text = title_from_url(output_url)

            relevance_text = f"{text} {output_url}"
            if not self.relevance.is_relevant(relevance_text):
                continue
            if not self.relevance.has_role_indicator(relevance_text):
                continue

            jobs.append(
                JobResult(
                    company=company_name,
                    title=text,
                    url=output_url,
                    source="html-link",
                    job_id=extract_job_id(f"{text} {output_url}"),
                    careers_url=careers_url,
                )
            )

        return jobs

    def _extract_next_pages(
        self,
        soup: BeautifulSoup,
        current_url: str,
        start_host: str,
    ) -> list[str]:
        next_urls: list[str] = []
        for anchor in soup.find_all("a", href=True):
            href = anchor.get("href", "").strip()
            if href.startswith(("mailto:", "javascript:", "#")):
                continue
            absolute = normalize_url(urljoin(current_url, href))
            if not is_allowed_url(absolute):
                continue

            parsed = urlparse(absolute)
            if not same_company_scope(start_host, parsed.netloc):
                continue

            text = anchor.get_text(" ", strip=True)
            if self._looks_like_job_navigation(text, absolute):
                next_urls.append(absolute)
        return next_urls
