from __future__ import annotations

from datetime import datetime, timezone

from .ats_resolver import AtsResolver
from .dates import is_recent
from .html_crawler import HtmlCrawler
from .http_client import HttpClient
from .location import LocationFilter
from pathlib import Path

from .models import CompanyTarget, JobResult
from .playwright_crawler import PlaywrightCrawler
from .providers import (
    GreenhouseProvider,
    IcimsProvider,
    LeverProvider,
    OracleOrcProvider,
    SuccessFactorsProvider,
    WorkdayProvider,
)
from .relevance import JobRelevance


class JobCrawlerService:
    def __init__(
        self,
        timeout_seconds: int,
        max_pages_per_company: int,
        location_filter: LocationFilter,
        max_age_days: int | None,
        enable_playwright_fallback: bool = True,
        debug: bool = False,
        debug_file: Path | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_pages_per_company = max_pages_per_company
        self.location_filter = location_filter
        self.max_age_days = max_age_days
        self.enable_playwright_fallback = enable_playwright_fallback
        self.debug = debug
        self.debug_file = debug_file

    def crawl_company(self, target: CompanyTarget) -> list[JobResult]:
        http = HttpClient(timeout_seconds=self.timeout_seconds)
        relevance = JobRelevance()
        resolver = AtsResolver(http=http)
        resolved_urls = resolver.resolve(target.careers_url)
        provider_targets = [
            CompanyTarget(name=target.name, careers_url=url) for url in resolved_urls
        ]

        providers = [
            GreenhouseProvider(http=http, relevance=relevance),
            LeverProvider(http=http, relevance=relevance),
            WorkdayProvider(http=http, relevance=relevance, location_filter=self.location_filter),
            OracleOrcProvider(http=http, relevance=relevance),
            SuccessFactorsProvider(http=http, relevance=relevance),
            IcimsProvider(http=http, relevance=relevance),
        ]

        jobs: list[JobResult] = []
        for provider in providers:
            for resolved_target in provider_targets:
                jobs.extend(provider.fetch(resolved_target))

        html_crawler = HtmlCrawler(
            http=http,
            relevance=relevance,
            debug=self.debug,
            debug_file=self.debug_file,
        )
        jobs.extend(html_crawler.crawl_company(target=target, max_pages=self.max_pages_per_company))

        # print(f"[{target.name}] extracted {len(jobs)} raw jobs before dedupe/filter")
        # for job in jobs[:5]:
        #     print(
        #         f"  - {job.source} | {job.title} | {job.location} | {job.job_id} | {job.url}"
        #     )
        # input("Enter to continue................................")

        deduped = self._dedupe_jobs(jobs)
        filtered = self._filter_jobs(deduped)

        if not filtered and self.enable_playwright_fallback:
            fallback = self._crawl_playwright_fallback(target=target, relevance=relevance)
            if fallback:
                jobs.extend(fallback)
                deduped = self._dedupe_jobs(jobs)
                filtered = self._filter_jobs(deduped)

        def sort_key(item: JobResult) -> tuple[int, float, str, str]:
            if item.posted_at is None:
                return (1, float("inf"), item.company.lower(), item.title.lower())
            timestamp = item.posted_at.astimezone(timezone.utc).timestamp()
            return (0, -timestamp, item.company.lower(), item.title.lower())

        return sorted(filtered, key=sort_key)

    def _dedupe_jobs(self, jobs: list[JobResult]) -> list[JobResult]:
        deduped: dict[str, JobResult] = {}
        # print(f"Existing job: ", jobs[0])
        # input("Enter to continue................................")
        for job in jobs:
            # print(f"Processing job for dedupe: ", job)
            # input("Enter to continue................................")
            url_key = (job.url or "").strip().lower()
            title_key = (job.title or "").strip().lower()
            if not url_key:
                url_key = "no-url"
            if not title_key:
                title_key = "no-title"
            key = f"{job.company.lower()}::{url_key}::{title_key}"
            existing = deduped.get(key)
            if existing is None or (existing.source == "html-link" and job.source != "html-link"):
                deduped[key] = job
        return list(deduped.values())

    def _filter_jobs(self, jobs: list[JobResult]) -> list[JobResult]:
        filtered = [job for job in jobs if self.location_filter.matches_job(job)]
        if self.max_age_days is not None and self.max_age_days > 0:
            recent = [job for job in filtered if is_recent(job.posted_at, self.max_age_days)]
            if recent:
                filtered = recent
            else:
                # Fallback: no jobs in the last N days, keep latest dated jobs if available,
                # otherwise keep undated results rather than returning empty.
                dated = [job for job in filtered if job.posted_at is not None]
                if dated:
                    filtered = dated
        return filtered

    def _crawl_playwright_fallback(
        self,
        target: CompanyTarget,
        relevance: JobRelevance,
    ) -> list[JobResult]:
        crawler = PlaywrightCrawler(
            relevance=relevance,
            timeout_seconds=self.timeout_seconds,
            debug=self.debug,
            debug_file=self.debug_file,
        )
        print(f"[{target.name}] Playwright fallback attempting (0 jobs after dedupe).")
        return crawler.crawl_company(target=target, max_pages=self.max_pages_per_company)
