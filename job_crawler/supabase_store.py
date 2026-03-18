from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import timezone
from typing import Iterable

import requests

from .config import DEFAULT_SUPABASE_COMPANIES_TABLE, DEFAULT_SUPABASE_SENT_JOBS_TABLE
from .io_utils import parse_company_target_records
from .models import CompanyTarget, JobResult
from .text import normalize_text


class SupabaseStoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class SupabaseStoreConfig:
    url: str
    api_key: str
    timeout_seconds: int
    sent_jobs_table: str
    companies_table: str


def build_sent_job_key(job: JobResult) -> str:
    normalized_company = normalize_text(job.company)
    normalized_title = normalize_text(job.title)
    normalized_job_id = normalize_text(job.job_id or "")
    raw_key = f"{normalized_company}::{normalized_title}::{normalized_job_id}"
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def build_company_key(target: CompanyTarget) -> str:
    normalized_company = normalize_text(target.name)
    raw_key = normalized_company or normalize_text(target.careers_url)
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def load_supabase_config(timeout_seconds: int) -> SupabaseStoreConfig | None:
    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    api_key = (
        os.environ.get("SUPABASE_SECRET_KEY", "").strip()
        or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        or os.environ.get("SUPABASE_KEY", "").strip()
    )
    sent_jobs_table = (
        os.environ.get("SUPABASE_SENT_JOBS_TABLE", DEFAULT_SUPABASE_SENT_JOBS_TABLE).strip()
        or DEFAULT_SUPABASE_SENT_JOBS_TABLE
    )
    companies_table = (
        os.environ.get("SUPABASE_COMPANIES_TABLE", DEFAULT_SUPABASE_COMPANIES_TABLE).strip()
        or DEFAULT_SUPABASE_COMPANIES_TABLE
    )

    if not url or not api_key:
        return None

    return SupabaseStoreConfig(
        url=url,
        api_key=api_key,
        timeout_seconds=max(1, timeout_seconds),
        sent_jobs_table=sent_jobs_table,
        companies_table=companies_table,
    )


class SupabaseTableStore:
    def __init__(self, config: SupabaseStoreConfig) -> None:
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({"apikey": self.config.api_key})

    def _table_url(self, table_name: str) -> str:
        return f"{self.config.url}/rest/v1/{table_name}"

    def _raise_for_status(self, response: requests.Response, action: str) -> None:
        if response.ok:
            return
        detail = response.text.strip()
        if len(detail) > 500:
            detail = detail[:500] + "..."
        raise SupabaseStoreError(f"Failed to {action}: HTTP {response.status_code} {detail}")

    def _chunked(self, items: list[object], size: int) -> list[list[object]]:
        return [items[index : index + size] for index in range(0, len(items), size)]


class SupabaseSentJobsStore(SupabaseTableStore):
    @classmethod
    def from_env(cls, timeout_seconds: int) -> SupabaseSentJobsStore | None:
        config = load_supabase_config(timeout_seconds)
        if config is None:
            return None
        return cls(config)

    def filter_unsent_jobs(self, jobs: list[JobResult]) -> list[JobResult]:
        if not jobs:
            return []

        requested_keys = {build_sent_job_key(job) for job in jobs}
        existing_keys = self._fetch_existing_keys(requested_keys)
        return [job for job in jobs if build_sent_job_key(job) not in existing_keys]

    def store_sent_jobs(self, jobs: Iterable[JobResult]) -> None:
        rows = [self._serialize_job(job) for job in jobs]
        if not rows:
            return

        for chunk in self._chunked(rows, size=100):
            response = self.session.post(
                self._table_url(self.config.sent_jobs_table),
                json=chunk,
                headers={"Content-Type": "application/json", "Prefer": "return=minimal"},
                timeout=self.config.timeout_seconds,
            )
            self._raise_for_status(response, "insert sent jobs")

    def _fetch_existing_keys(self, job_keys: set[str]) -> set[str]:
        existing: set[str] = set()
        for chunk in self._chunked(sorted(job_keys), size=50):
            response = self.session.get(
                self._table_url(self.config.sent_jobs_table),
                params={
                    "select": "job_key",
                    "job_key": f"in.({','.join(chunk)})",
                },
                timeout=self.config.timeout_seconds,
            )
            self._raise_for_status(response, "fetch sent jobs")
            payload = response.json()
            for row in payload:
                key = str(row.get("job_key", "")).strip()
                if key:
                    existing.add(key)
        return existing

    def _serialize_job(self, job: JobResult) -> dict[str, str | None]:
        posted_at = None
        if job.posted_at is not None:
            posted_at = job.posted_at.astimezone(timezone.utc).isoformat()

        return {
            "job_key": build_sent_job_key(job),
            "company": job.company,
            "title": job.title,
            "job_id": job.job_id or "",
            "location": job.location,
            "job_url": job.url,
            "careers_url": job.careers_url,
            "source": job.source,
            "posted_at": posted_at,
        }


class SupabaseCompaniesStore(SupabaseTableStore):
    @classmethod
    def from_env(cls, timeout_seconds: int) -> SupabaseCompaniesStore | None:
        config = load_supabase_config(timeout_seconds)
        if config is None:
            return None
        return cls(config)

    def load_company_targets(self) -> list[CompanyTarget]:
        response = self.session.get(
            self._table_url(self.config.companies_table),
            params={
                "select": "name,careers_url,api_post",
                "enabled": "eq.true",
                "order": "name.asc",
            },
            timeout=self.config.timeout_seconds,
        )
        self._raise_for_status(response, "load companies")
        payload = response.json()
        if not isinstance(payload, list):
            raise SupabaseStoreError("Failed to load companies: unexpected response payload.")
        if not payload:
            return []
        return parse_company_target_records(payload)

    def sync_company_targets(self, targets: list[CompanyTarget]) -> tuple[int, int]:
        if not targets:
            return (0, 0)

        existing_keys = self._fetch_existing_company_keys({build_company_key(target) for target in targets})
        to_insert: list[dict[str, object]] = []
        updated_count = 0

        for target in targets:
            row = self._serialize_company(target)
            company_key = str(row["company_key"])
            if company_key in existing_keys:
                self._update_company(row)
                updated_count += 1
            else:
                to_insert.append(row)

        inserted_count = 0
        for chunk in self._chunked(to_insert, size=100):
            response = self.session.post(
                self._table_url(self.config.companies_table),
                json=chunk,
                headers={"Content-Type": "application/json", "Prefer": "return=minimal"},
                timeout=self.config.timeout_seconds,
            )
            self._raise_for_status(response, "insert companies")
            inserted_count += len(chunk)

        return (inserted_count, updated_count)

    def _fetch_existing_company_keys(self, company_keys: set[str]) -> set[str]:
        existing: set[str] = set()
        for chunk in self._chunked(sorted(company_keys), size=50):
            response = self.session.get(
                self._table_url(self.config.companies_table),
                params={
                    "select": "company_key",
                    "company_key": f"in.({','.join(chunk)})",
                },
                timeout=self.config.timeout_seconds,
            )
            self._raise_for_status(response, "fetch existing companies")
            payload = response.json()
            for row in payload:
                key = str(row.get("company_key", "")).strip()
                if key:
                    existing.add(key)
        return existing

    def _update_company(self, row: dict[str, object]) -> None:
        company_key = str(row["company_key"])
        payload = {
            "name": row["name"],
            "careers_url": row["careers_url"],
            "api_post": row["api_post"],
            "enabled": row["enabled"],
        }
        response = self.session.patch(
            self._table_url(self.config.companies_table),
            params={"company_key": f"eq.{company_key}"},
            json=payload,
            headers={"Content-Type": "application/json", "Prefer": "return=minimal"},
            timeout=self.config.timeout_seconds,
        )
        self._raise_for_status(response, "update company")

    def _serialize_company(self, target: CompanyTarget) -> dict[str, object]:
        return {
            "company_key": build_company_key(target),
            "name": target.name,
            "careers_url": target.careers_url,
            "api_post": target.api_post,
            "enabled": True,
        }
