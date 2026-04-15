from __future__ import annotations

from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

import json

from .dates import parse_epoch_ms, parse_human_date, parse_iso_datetime
from .http_client import HttpClient
from .html_crawler import HtmlCrawler
from .models import CompanyTarget, JobResult
from .relevance import JobRelevance
from .text import is_allowed_url, normalize_url


class PlaywrightCrawler:
    def __init__(
        self,
        relevance: JobRelevance,
        timeout_seconds: int,
        debug: bool = False,
        debug_file: Path | None = None,
    ) -> None:
        self.relevance = relevance
        self.timeout_seconds = max(1, timeout_seconds)
        self.debug = debug
        self.debug_file = debug_file

    @staticmethod
    def is_available() -> bool:
        try:
            import playwright.sync_api  # noqa: F401
        except Exception:
            return False
        return True

    def crawl_company(self, target: CompanyTarget, max_pages: int) -> list[JobResult]:
        if max_pages <= 0:
            return []
        if not self.is_available():
            self._debug("[PW] Playwright not installed; skipping.")
            return []

        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright

        html_helper = HtmlCrawler(
            http=HttpClient(timeout_seconds=self.timeout_seconds),
            relevance=self.relevance,
            debug=self.debug,
            debug_file=self.debug_file,
        )
        start_host = urlparse(target.careers_url).netloc
        queue: deque[str] = deque([target.careers_url])
        visited: set[str] = set()
        jobs: list[JobResult] = []
        captured_jobs: list[JobResult] = []

        timeout_ms = self.timeout_seconds * 1000

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context()
                page = context.new_page()
                self._debug(f"[PW] start {target.name} via {target.careers_url}")
                self._attach_response_capture(page, target, captured_jobs)
                if self.debug:
                    self._attach_debug_listeners(page)
                while queue and len(visited) < max_pages:
                    page_url = queue.popleft()
                    if page_url in visited:
                        continue
                    visited.add(page_url)

                    if not self._navigate(page, page_url, timeout_ms, PlaywrightTimeoutError):
                        self._debug(f"[PW] navigation failed: {page_url}")
                        continue
                    self._debug(f"[PW] loaded {page.url}")
                    soup = BeautifulSoup(page.content(), "html.parser")
                    page_text = html_helper._extract_page_text(soup)
                    base_url = html_helper._get_base_url(soup, page.url)
                    if any(cue in page_text for cue in ["job", "career", "opening", "hiring", "position"]):
                        jobs.extend(
                            html_helper._extract_jobs_from_jsonld(
                                soup,
                                target.name,
                                page.url,
                                target.careers_url,
                            )
                        )
                        jobs.extend(
                            html_helper._extract_jobs_from_links(
                                soup,
                                target.name,
                                base_url,
                                target.careers_url,
                            )
                        )

                    for next_page in html_helper._extract_next_pages(soup, base_url, start_host):
                        if next_page not in visited and next_page not in queue:
                            queue.append(next_page)

                context.close()
                browser.close()
        except Exception as exc:
            self._debug(f"[PW] failed: {type(exc).__name__}: {exc}")
            return []

        if captured_jobs:
            jobs.extend(captured_jobs)
        return jobs

    def _navigate(
        self,
        page: "object",
        url: str,
        timeout_ms: int,
        timeout_error: type[BaseException],
    ) -> bool:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            self._auto_scroll(page)
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
            return True
        except timeout_error:
            try:
                page.goto(url, wait_until="load", timeout=timeout_ms)
                self._auto_scroll(page)
                return True
            except timeout_error:
                return False
        except Exception:
            return False

    def _auto_scroll(self, page: "object") -> None:
        try:
            for _ in range(4):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(400)
        except Exception:
            return

    def _attach_debug_listeners(self, page: "object") -> None:
        def on_console(message: "object") -> None:
            try:
                self._debug(f"[PW] console {message.type}: {message.text}")
            except Exception:
                return

        def on_page_error(exception: "object") -> None:
            try:
                self._debug(f"[PW] pageerror: {exception}")
            except Exception:
                return

        def on_response(response: "object") -> None:
            try:
                request = response.request
                resource_type = getattr(request, "resource_type", "")
                content_type = response.headers.get("content-type", "")
                if resource_type in {"xhr", "fetch"} or "json" in content_type:
                    self._debug(
                        f"[PW] response {response.status} {response.url} {resource_type} {content_type}"
                    )
            except Exception:
                return

        try:
            page.on("console", on_console)
            page.on("pageerror", on_page_error)
            page.on("response", on_response)
        except Exception:
            return

    def _attach_response_capture(
        self,
        page: "object",
        target: CompanyTarget,
        captured_jobs: list[JobResult],
    ) -> None:
        def on_response(response: "object") -> None:
            if len(captured_jobs) >= 200:
                return
            try:
                jobs = self._extract_jobs_from_response(response, target)
                if jobs:
                    captured_jobs.extend(jobs)
                    self._debug(f"[PW] json jobs: {len(jobs)} from {response.url}")
            except Exception as exc:
                self._debug(f"[PW] json capture failed: {type(exc).__name__}: {exc}")

        try:
            page.on("response", on_response)
        except Exception:
            return

    def _extract_jobs_from_response(
        self,
        response: "object",
        target: CompanyTarget,
    ) -> list[JobResult]:
        content_type = (response.headers.get("content-type") or "").lower()
        if "text/html" in content_type:
            return []
        url = response.url
        resource_type = getattr(response.request, "resource_type", "")
        looks_like_data = (
            "json" in content_type
            or "graphql" in url
            or "job" in url
            or "jobs" in url
            or "search" in url
            or "position" in url
            or resource_type in {"xhr", "fetch"}
        )
        if not looks_like_data:
            return []

        length = response.headers.get("content-length")
        if length:
            try:
                if int(length) > 2_000_000:
                    return []
            except ValueError:
                pass

        text = ""
        payload: Any | None = None
        if "json" in content_type:
            try:
                payload = response.json()
            except Exception:
                text = response.text()
        if payload is None:
            if not text:
                text = response.text()
            if not text:
                return []
            stripped = text.lstrip()
            if not stripped or stripped[0] not in "{[":
                return []
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                return []

        return self._extract_jobs_from_json_payload(
            payload=payload,
            company_name=target.name,
            source_url=url,
            careers_url=target.careers_url,
        )

    def _extract_jobs_from_json_payload(
        self,
        payload: Any,
        company_name: str,
        source_url: str,
        careers_url: str,
    ) -> list[JobResult]:
        results: list[JobResult] = []
        seen_keys: set[str] = set()
        for node in self._iter_json_nodes(payload):
            if not isinstance(node, dict):
                continue
            title = self._first_string(
                node,
                [
                    "title",
                    "jobTitle",
                    "positionTitle",
                    "postingTitle",
                    "name",
                    "job_title",
                ],
            )
            if not title:
                continue
            description = self._first_string(
                node,
                [
                    "description",
                    "jobDescription",
                    "descriptionHtml",
                    "summary",
                    "jobSummary",
                    "job_description",
                ],
            )
            combined = f"{title} {description}"
            if not self.relevance.is_relevant(combined):
                continue
            if not self.relevance.has_role_indicator(combined):
                continue

            job_url = self._first_string(
                node,
                [
                    "applyUrl",
                    "apply_url",
                    "url",
                    "jobUrl",
                    "job_url",
                    "postingUrl",
                    "externalApplyUrl",
                    "applyLink",
                    "applyLinkUrl",
                ],
            )
            job_url = self._normalize_candidate_url(job_url, source_url, careers_url)
            if not job_url:
                continue

            job_id = self._first_string(
                node,
                [
                    "jobId",
                    "job_id",
                    "id",
                    "requisitionId",
                    "reqId",
                    "jobReqId",
                    "postingId",
                ],
            )
            location = self._extract_location_from_node(node)
            posted_at = self._extract_posted_at(node)

            key = f"{job_url}::{title.lower()}"
            if key in seen_keys:
                continue
            seen_keys.add(key)

            results.append(
                JobResult(
                    company=company_name,
                    title=title,
                    url=job_url,
                    source="playwright-json",
                    location=location,
                    job_id=job_id,
                    careers_url=careers_url,
                    experience_text=combined,
                    posted_at=posted_at,
                )
            )

        return results

    def _iter_json_nodes(self, payload: Any, max_depth: int = 6, max_nodes: int = 4000) -> list[dict[str, Any]]:
        stack: list[tuple[Any, int]] = [(payload, 0)]
        nodes: list[dict[str, Any]] = []
        while stack:
            current, depth = stack.pop()
            if isinstance(current, dict):
                nodes.append(current)
                if len(nodes) >= max_nodes:
                    break
                if depth < max_depth:
                    for value in current.values():
                        if isinstance(value, (dict, list)):
                            stack.append((value, depth + 1))
            elif isinstance(current, list) and depth < max_depth:
                for item in current:
                    if isinstance(item, (dict, list)):
                        stack.append((item, depth + 1))
        return nodes

    def _first_string(self, node: dict[str, Any], keys: list[str]) -> str:
        for key in keys:
            if key not in node:
                continue
            value = node.get(key)
            text = self._stringify_value(value)
            if text:
                return text
        return ""

    def _stringify_value(self, value: Any) -> str:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, list):
            parts = [self._stringify_value(item) for item in value]
            parts = [part for part in parts if part]
            return ", ".join(parts[:3]).strip()
        if isinstance(value, dict):
            for key in ("name", "label", "value", "text", "title"):
                text = self._stringify_value(value.get(key))
                if text:
                    return text
            address = value.get("address")
            if isinstance(address, dict):
                locality = self._stringify_value(address.get("addressLocality"))
                region = self._stringify_value(address.get("addressRegion"))
                country = self._stringify_value(address.get("addressCountry"))
                parts = [part for part in [locality, region, country] if part]
                if parts:
                    return ", ".join(parts)
        return ""

    def _normalize_candidate_url(self, value: str, source_url: str, careers_url: str) -> str:
        if not value:
            return ""
        url_value = value.strip()
        if not url_value:
            return ""
        if not is_allowed_url(url_value):
            url_value = urljoin(source_url, url_value)
        if not is_allowed_url(url_value):
            url_value = urljoin(careers_url, url_value)
        if not is_allowed_url(url_value):
            return ""
        return normalize_url(
            url_value,
            remove_tracking=False,
            drop_fragment=False,
            trim_trailing_slash=False,
        )

    def _extract_location_from_node(self, node: dict[str, Any]) -> str:
        for key in (
            "location",
            "locations",
            "jobLocation",
            "jobLocations",
            "locationName",
            "city",
            "country",
            "state",
            "region",
        ):
            if key in node:
                text = self._stringify_value(node.get(key))
                if text:
                    return text
        address = node.get("address")
        if isinstance(address, dict):
            locality = self._stringify_value(address.get("addressLocality"))
            region = self._stringify_value(address.get("addressRegion"))
            country = self._stringify_value(address.get("addressCountry"))
            parts = [part for part in [locality, region, country] if part]
            if parts:
                return ", ".join(parts)
        return ""

    def _extract_posted_at(self, node: dict[str, Any]) -> datetime | None:
        for key in ("datePosted", "postedDate", "postedAt", "createdAt", "startDate"):
            if key not in node:
                continue
            value = node.get(key)
            if isinstance(value, (int, float)):
                return parse_epoch_ms(value)
            if isinstance(value, str):
                return (
                    parse_iso_datetime(value)
                    or parse_human_date(value)
                    or parse_epoch_ms(value)
                )
        return None

    def _debug(self, message: str) -> None:
        if not self.debug or not self.debug_file:
            return
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with self.debug_file.open("a", encoding="utf-8") as handle:
                handle.write(f"{timestamp} {message}\n")
        except OSError:
            return
