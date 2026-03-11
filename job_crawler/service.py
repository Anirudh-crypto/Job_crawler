from __future__ import annotations

from .html_crawler import HtmlCrawler
from .http_client import HttpClient
from .location import LocationFilter
from .models import CompanyTarget, JobResult
from .providers import GreenhouseProvider, LeverProvider, WorkdayProvider
from .relevance import JobRelevance
from .text import normalize_url


class JobCrawlerService:
    def __init__(
        self,
        timeout_seconds: int,
        max_pages_per_company: int,
        location_filter: LocationFilter,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_pages_per_company = max_pages_per_company
        self.location_filter = location_filter

    def crawl_company(self, target: CompanyTarget) -> list[JobResult]:
        http = HttpClient(timeout_seconds=self.timeout_seconds)
        relevance = JobRelevance()

        providers = [
            GreenhouseProvider(http=http, relevance=relevance),
            LeverProvider(http=http, relevance=relevance),
            WorkdayProvider(http=http, relevance=relevance, location_filter=self.location_filter),
        ]

        jobs: list[JobResult] = []
        for provider in providers:
            jobs.extend(provider.fetch(target))

        html_crawler = HtmlCrawler(http=http, relevance=relevance)
        jobs.extend(html_crawler.crawl_company(target=target, max_pages=self.max_pages_per_company))

        deduped: dict[str, JobResult] = {}
        for job in jobs:
            key = f"{job.company.lower()}::{normalize_url(job.url).lower()}"
            existing = deduped.get(key)
            if existing is None or (existing.source == "html-link" and job.source != "html-link"):
                deduped[key] = job

        filtered = [job for job in deduped.values() if self.location_filter.matches_job(job)]
        return sorted(filtered, key=lambda item: (item.company.lower(), item.title.lower(), item.url.lower()))
