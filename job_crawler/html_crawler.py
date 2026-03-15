from __future__ import annotations

import json
import re
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from .constants import JOB_CUE_PHRASES, LOCATION_ALIASES
from .http_client import HttpClient
from .models import CompanyTarget, JobResult
from .relevance import JobRelevance
from .dates import parse_iso_datetime
from .text import (
    extract_job_id,
    is_allowed_url,
    normalize_text,
    normalize_url,
    same_company_scope,
    title_from_url,
)


class HtmlCrawler:
    def __init__(
        self,
        http: HttpClient,
        relevance: JobRelevance,
        debug: bool = False,
        debug_file: Path | None = None,
    ) -> None:
        self.http = http
        self.relevance = relevance
        self.debug = debug
        self.debug_file = debug_file

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

            self._debug(f"[HTML] visiting {page_url}")

            response = self.http.get(page_url)

            if response is None:
                continue
            if "text/html" not in response.headers.get("content-type", "").lower():
                continue

            soup = BeautifulSoup(response.text, "html.parser")

            page_text = self._extract_page_text(soup)

            base_url = self._get_base_url(soup, response.url)
            cues_present = any(cue in page_text for cue in ["job", "career", "opening", "hiring", "position"])
            self._debug(f"[HTML] cue match: {cues_present} for {response.url}")
            if cues_present:
                jsonld_jobs = self._extract_jobs_from_jsonld(
                    soup,
                    target.name,
                    response.url,
                    target.careers_url,
                )
                self._debug(f"[HTML] json-ld jobs: {len(jsonld_jobs)} for {response.url}")
                jobs.extend(jsonld_jobs)

                link_jobs = self._extract_jobs_from_links(
                    soup,
                    target.name,
                    base_url,
                    target.careers_url,
                )
                self._debug(f"[HTML] link jobs: {len(link_jobs)} for {response.url}")
                jobs.extend(link_jobs)

            for next_page in self._extract_next_pages(soup, base_url, start_host):
                if next_page not in visited and next_page not in queue:
                    queue.append(next_page)

        return jobs

    def _extract_page_text(self, soup: BeautifulSoup) -> str:
        return normalize_text(soup.get_text(" ", strip=True))

    def _get_base_url(self, soup: BeautifulSoup, current_url: str) -> str:
        base_tag = soup.find("base", href=True)
        if not base_tag:
            return current_url
        return normalize_url(
            urljoin(current_url, base_tag["href"]),
            remove_tracking=False,
            drop_fragment=False,
            trim_trailing_slash=False,
        )

    def _looks_like_job_navigation(self, text: str, href: str) -> bool:
        joined = normalize_text(f"{text} {href}")
        return any(cue in joined for cue in JOB_CUE_PHRASES)

    def _looks_like_job_list_link(self, text: str, href: str) -> bool:
        joined = normalize_text(f"{text} {href}")
        list_phrases = [
            "see open",
            "view open",
            "view all jobs",
            "view jobs",
            "open positions",
            "open roles",
            "all roles",
            "all jobs",
            "job search",
            "search jobs",
            "jobs search",
            "search careers",
            "explore jobs",
            "join our team",
        ]
        if any(phrase in joined for phrase in list_phrases):
            return True

        parsed = urlparse(href)
        path = parsed.path.rstrip("/")
        if path.endswith(("/jobs", "/careers", "/job-search", "/jobsearch", "/open-positions", "/positions", "/search")):
            return True
        if "open-positions" in path or "job-search" in path:
            return True
        return False

    def _flatten_jsonld_job_postings(self, node: Any, depth: int = 0) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        if depth > 8:
            return results
        if isinstance(node, dict):
            if self._is_job_posting_node(node) or self._looks_like_job_posting(node):
                results.append(node)
            for value in node.values():
                if isinstance(value, (dict, list)):
                    results.extend(self._flatten_jsonld_job_postings(value, depth + 1))
            graph = node.get("@graph")
            if graph is not None:
                results.extend(self._flatten_jsonld_job_postings(graph, depth + 1))
        elif isinstance(node, list):
            for item in node:
                results.extend(self._flatten_jsonld_job_postings(item, depth + 1))
        return results

    def _is_job_posting_node(self, node: dict[str, Any]) -> bool:
        node_type = node.get("@type") or node.get("type")
        for type_value in self._extract_type_values(node_type):
            if self._normalize_type_value(type_value) == "jobposting":
                return True
        return False

    def _extract_type_values(self, node_type: Any) -> list[str]:
        values: list[str] = []
        if isinstance(node_type, str):
            values.append(node_type)
        elif isinstance(node_type, list):
            for entry in node_type:
                values.extend(self._extract_type_values(entry))
        elif isinstance(node_type, dict):
            for key in ("@id", "@type", "id", "type"):
                if key in node_type:
                    values.extend(self._extract_type_values(node_type[key]))
        return values

    def _normalize_type_value(self, value: str) -> str:
        lowered = value.strip().lower()
        if "/" in lowered:
            lowered = lowered.rsplit("/", 1)[-1]
        if ":" in lowered:
            lowered = lowered.rsplit(":", 1)[-1]
        return lowered

    def _looks_like_job_posting(self, node: dict[str, Any]) -> bool:
        title = node.get("title")
        description = node.get("description")
        if not (title or description):
            return False
        indicators = (
            "jobLocation",
            "hiringOrganization",
            "employmentType",
            "datePosted",
            "validThrough",
            "applicantLocationRequirements",
            "baseSalary",
        )
        return any(key in node for key in indicators)

    def _extract_jobs_from_jsonld(
        self,
        soup: BeautifulSoup,
        company_name: str,
        current_url: str,
        careers_url: str,
    ) -> list[JobResult]:
        jobs: list[JobResult] = []
        scripts = soup.find_all("script", attrs={"type": "application/ld+json"})
        self._debug(f"[JSON-LD] scripts found: {len(scripts)} for {current_url}")
        for script in scripts:
            raw = (script.string or script.get_text() or "").strip()
            if not raw:
                self._debug("[JSON-LD] empty script block")
                continue

            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                preview = raw[:200].replace("\n", " ")
                self._debug(f"[JSON-LD] parse failed: {preview}...")
                continue

            postings = self._flatten_jsonld_job_postings(payload)
            self._debug(f"[JSON-LD] postings found: {len(postings)} for {current_url}")
            if postings:
                first = postings[0]
                preview = str(first)[:200].replace("\n", " ")
                self._debug(f"[JSON-LD] first posting preview: {preview}...")
            for posting in postings:
                title = str(posting.get("title", "")).strip()
                description = str(posting.get("description", ""))
                combined = f"{title} {description}"
                if not self.relevance.is_relevant(combined):
                    continue
                if not self.relevance.has_role_indicator(combined):
                    continue

                job_url = str(posting.get("url") or posting.get("applyUrl") or "").strip()
                if not job_url:
                    continue
                if not is_allowed_url(job_url):
                    job_url = urljoin(current_url, job_url)
                if not is_allowed_url(job_url):
                    continue
                posted_at = parse_iso_datetime(str(posting.get("datePosted") or ""))

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
                        posted_at=posted_at,
                    )
                )

        return jobs

    def _debug(self, message: str) -> None:
        if not self.debug or not self.debug_file:
            return
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with self.debug_file.open("a", encoding="utf-8") as handle:
                handle.write(f"{timestamp} {message}\n")
        except OSError:
            return

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
            if href.startswith(("mailto:", "javascript:")):
                continue
            if href.startswith("#") and not (href.startswith("#/") or href.startswith("#!")):
                continue

            output_url = normalize_url(
                urljoin(current_url, href),
                remove_tracking=False,
                drop_fragment=False,
                trim_trailing_slash=False,
            )
            if not is_allowed_url(output_url):
                continue
            if output_url.rstrip("/") in {current_url.rstrip("/"), careers_url.rstrip("/")}:
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
            if self._looks_like_job_list_link(text, output_url):
                continue

            jobs.append(
                JobResult(
                    company=company_name,
                    title=text,
                    url=output_url,
                    source="html-link",
                    location=self._extract_location_from_anchor(anchor, text),
                    job_id=extract_job_id(f"{text} {output_url}"),
                    careers_url=careers_url,
                    posted_at=None,
                )
            )

        return jobs

    def _extract_location_from_anchor(self, anchor: Tag, title_text: str) -> str:
        for attr in ("data-location", "data-job-location", "data-location-name"):
            value = anchor.get(attr)
            if isinstance(value, str) and value.strip():
                return self._sanitize_location_text(value, title_text)

        ancestors: list[Tag] = []
        current: Tag | None = anchor
        for _ in range(4):
            if current is None:
                break
            ancestors.append(current)
            current = current.parent if isinstance(current.parent, Tag) else None

        pattern = re.compile(r"(loc|location)", re.IGNORECASE)
        for node in ancestors:
            for element in node.find_all(["span", "div", "p", "li"], attrs={"class": pattern}):
                text = element.get_text(" ", strip=True)
                candidate = self._sanitize_location_text(text, title_text)
                if candidate:
                    return candidate
            for element in node.find_all(["span", "div", "p", "li"], attrs={"id": pattern}):
                text = element.get_text(" ", strip=True)
                candidate = self._sanitize_location_text(text, title_text)
                if candidate:
                    return candidate

        return ""

    def _sanitize_location_text(self, text: str, title_text: str) -> str:
        if not text:
            return ""
        cleaned = " ".join(text.split())
        if not cleaned or cleaned == title_text:
            return ""
        if len(cleaned) > 120:
            return ""
        lowered = normalize_text(cleaned)
        if "," in cleaned:
            return cleaned
        if any(token in lowered for token in ["remote", "hybrid", "onsite", "on-site", "on site"]):
            return cleaned

        for key, aliases in LOCATION_ALIASES.items():
            if key in lowered:
                return cleaned
            for alias in aliases:
                if alias in lowered:
                    return cleaned

        if re.search(r"\b[a-z]+,\s*[a-z]{2,}\b", cleaned, re.IGNORECASE):
            return cleaned
        return ""

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
