from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .config import (
    DEFAULT_COMPANIES_FILE,
    DEFAULT_EMAIL_RECIPIENTS,
    DEFAULT_EMAIL_SUBJECT,
    DEFAULT_ENABLE_PLAYWRIGHT_FALLBACK,
    DEFAULT_ENABLE_SUPABASE_COMPANIES,
    DEFAULT_ENABLE_SUPABASE_SENT_JOBS,
    DEFAULT_LOCATIONS,
    DEFAULT_MAX_AGE_DAYS,
    DEFAULT_MAX_EXPERIENCE_YEARS,
    DEFAULT_MAX_PAGES_PER_COMPANY,
    DEFAULT_SEND_EMAIL,
    FALLBACK_COMPANIES_FILE,
)
from dotenv import load_dotenv
from .emailer import send_email
from .io_utils import parse_company_targets
from .location import LocationFilter
from .models import CompanyTarget, JobResult
from .service import JobCrawlerService
from .supabase_store import SupabaseCompaniesStore, SupabaseSentJobsStore, SupabaseStoreError


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Crawl company careers pages and collect jobs related to Machine Learning / Data Science."
        )
    )
    parser.add_argument(
        "--companies",
        type=Path,
        default=DEFAULT_COMPANIES_FILE,
        help="Path to JSON file containing company names and careers URLs.",
    )
    parser.add_argument(
        "--max-pages-per-company",
        type=int,
        default=DEFAULT_MAX_PAGES_PER_COMPANY,
        help="Maximum number of pages to crawl per company careers site.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=15,
        help="HTTP request timeout in seconds.",
    )
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=DEFAULT_MAX_AGE_DAYS,
        help="Only keep jobs posted within this many days (0 disables).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=5,
        help="Number of companies to crawl in parallel.",
    )
    parser.add_argument(
        "--location",
        action="append",
        default=None,
        help=(
            "Location filter (repeatable). Example: --location Germany --location Bengaluru. "
            "For Workday this uses API facets when available."
        ),
    )
    parser.add_argument(
        "--send-email",
        action=argparse.BooleanOptionalAction,
        default=DEFAULT_SEND_EMAIL,
        help="Send an email with the CSV contents using Gmail SMTP.",
    )
    parser.add_argument(
        "--email-to",
        action="append",
        default=None,
        help="Email recipient (repeatable). Defaults to config if omitted.",
    )
    parser.add_argument(
        "--email-subject",
        default=DEFAULT_EMAIL_SUBJECT,
        help="Optional subject prefix for the email.",
    )
    return parser


def load_company_targets(
    companies_file: Path,
    timeout_seconds: int,
) -> tuple[list[CompanyTarget], str]:
    if DEFAULT_ENABLE_SUPABASE_COMPANIES:
        companies_store = SupabaseCompaniesStore.from_env(timeout_seconds=timeout_seconds)
        if companies_store is not None:
            try:
                targets = companies_store.load_company_targets()
                if targets:
                    return (targets, "supabase")
                print(
                    "Supabase companies table returned 0 enabled rows. Falling back to JSON input.",
                    file=sys.stderr,
                )
            except (SupabaseStoreError, ValueError) as exc:
                print(f"Supabase companies load failed: {exc}. Falling back to JSON input.", file=sys.stderr)

    targets = parse_company_targets(companies_file)
    return (targets, str(companies_file))


def main() -> int:
    load_dotenv()
    parser = build_arg_parser()
    args = parser.parse_args()
    timeout_seconds = max(1, args.timeout_seconds)

    companies_file = args.companies
    if not companies_file.exists() and FALLBACK_COMPANIES_FILE.exists():
        companies_file = FALLBACK_COMPANIES_FILE

    try:
        targets, target_source = load_company_targets(companies_file, timeout_seconds=timeout_seconds)
    except (OSError, json.JSONDecodeError, ValueError, SupabaseStoreError) as exc:
        print(f"Error reading company list: {exc}", file=sys.stderr)
        return 2

    raw_locations = args.location if args.location is not None else DEFAULT_LOCATIONS
    location_filter = LocationFilter(raw_locations)
    debug_mode = os.getenv("JOB_CRAWLER_DEBUG", "").strip().lower() in {"1", "true", "yes"}
    debug_file = None
    if debug_mode:
        debug_file_name = os.getenv("JOB_CRAWLER_DEBUG_FILE", "debug.log").strip() or "debug.log"
        debug_file = Path(debug_file_name)
    service = JobCrawlerService(
        timeout_seconds=timeout_seconds,
        max_pages_per_company=max(1, args.max_pages_per_company),
        location_filter=location_filter,
        max_age_days=args.max_age_days if args.max_age_days and args.max_age_days > 0 else None,
        max_experience_years=DEFAULT_MAX_EXPERIENCE_YEARS,
        enable_playwright_fallback=DEFAULT_ENABLE_PLAYWRIGHT_FALLBACK,
        debug=debug_mode,
        debug_file=debug_file,
    )
    sent_jobs_store = None
    if DEFAULT_ENABLE_SUPABASE_SENT_JOBS:
        sent_jobs_store = SupabaseSentJobsStore.from_env(timeout_seconds=timeout_seconds)
        if sent_jobs_store is None:
            print("Supabase sent-jobs dedupe disabled or not configured.", file=sys.stderr)

    all_jobs: list[JobResult] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        future_map = {executor.submit(service.crawl_company, target): target for target in targets}
        for future in as_completed(future_map):
            target = future_map[future]
            try:
                jobs = future.result()
                all_jobs.extend(jobs)
                # print(f"[{target.name}] found {len(jobs)} relevant jobs")
            except Exception as exc:  # noqa: BLE001
                print(f"[{target.name}] failed: {exc}", file=sys.stderr)

    deduped: dict[tuple[str, str], JobResult] = {}
    for job in all_jobs:
        key = (job.company.lower(), job.url.lower())
        if key not in deduped:
            deduped[key] = job

    final_jobs = sorted(deduped.values(), key=lambda item: (item.company.lower(), item.title.lower()))
    outgoing_jobs = final_jobs
    if sent_jobs_store is not None:
        try:
            outgoing_jobs = sent_jobs_store.filter_unsent_jobs(final_jobs)
        except SupabaseStoreError as exc:
            print(f"Supabase sent-jobs check failed: {exc}", file=sys.stderr)

    location_note = ""
    if location_filter.enabled:
        location_note = f" after location filtering ({', '.join(raw_locations)})"
    experience_note = ""
    if DEFAULT_MAX_EXPERIENCE_YEARS and DEFAULT_MAX_EXPERIENCE_YEARS > 0:
        experience_note = f" and experience filter (<{DEFAULT_MAX_EXPERIENCE_YEARS} years)"

    print(
        f"Prepared {len(outgoing_jobs)} jobs for email "
        f"from {len(targets)} companies{location_note}{experience_note}."
    )
    print(f"Loaded company targets from {target_source}.")
    if sent_jobs_store is not None:
        skipped_count = len(final_jobs) - len(outgoing_jobs)
        print(f"Supabase sent-jobs dedupe active. {skipped_count} jobs already existed.")

    if args.send_email:
        send_email(
            jobs=outgoing_jobs,
            subject_prefix=args.email_subject,
            recipients=args.email_to or DEFAULT_EMAIL_RECIPIENTS,
        )
        if sent_jobs_store is not None and outgoing_jobs:
            try:
                sent_jobs_store.store_sent_jobs(outgoing_jobs)
                print(f"Stored {len(outgoing_jobs)} emailed jobs in Supabase sent-jobs table.")
            except SupabaseStoreError as exc:
                print(f"Supabase sent-jobs update failed: {exc}", file=sys.stderr)
        if outgoing_jobs:
            print("Email sent.")
        else:
            print("Email sent with 'No new jobs posted' content.")
    return 0
