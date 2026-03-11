from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .emailer import send_email_from_csv
from .io_utils import parse_company_targets, write_csv, write_markdown
from .location import LocationFilter
from .models import JobResult
from .service import JobCrawlerService


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Crawl company careers pages and collect jobs related to Machine Learning / Data Science."
        )
    )
    parser.add_argument(
        "--companies",
        required=True,
        type=Path,
        help="Path to JSON file containing company names and careers URLs.",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=Path("jobs.csv"),
        help="Output CSV file path.",
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path("jobs.md"),
        help="Output Markdown file path.",
    )
    parser.add_argument(
        "--max-pages-per-company",
        type=int,
        default=20,
        help="Maximum number of pages to crawl per company careers site.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=15,
        help="HTTP request timeout in seconds.",
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
        default=[],
        help=(
            "Location filter (repeatable). Example: --location Germany --location Bengaluru. "
            "For Workday this uses API facets when available."
        ),
    )
    parser.add_argument(
        "--send-email",
        action="store_true",
        help="Send an email with the CSV contents using Gmail SMTP.",
    )
    parser.add_argument(
        "--email-to",
        action="append",
        default=[],
        help="Email recipient (repeatable). Defaults to GMAIL_USER if omitted.",
    )
    parser.add_argument(
        "--email-subject",
        default="",
        help="Optional subject prefix for the email.",
    )
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    try:
        targets = parse_company_targets(args.companies)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Error reading company list: {exc}", file=sys.stderr)
        return 2

    location_filter = LocationFilter(args.location)
    service = JobCrawlerService(
        timeout_seconds=max(1, args.timeout_seconds),
        max_pages_per_company=max(1, args.max_pages_per_company),
        location_filter=location_filter,
    )

    all_jobs: list[JobResult] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        future_map = {executor.submit(service.crawl_company, target): target for target in targets}
        for future in as_completed(future_map):
            target = future_map[future]
            try:
                jobs = future.result()
                all_jobs.extend(jobs)
                print(f"[{target.name}] found {len(jobs)} relevant jobs")
            except Exception as exc:  # noqa: BLE001
                print(f"[{target.name}] failed: {exc}", file=sys.stderr)

    deduped: dict[tuple[str, str], JobResult] = {}
    for job in all_jobs:
        key = (job.company.lower(), job.url.lower())
        if key not in deduped:
            deduped[key] = job

    final_jobs = sorted(deduped.values(), key=lambda item: (item.company.lower(), item.title.lower()))
    write_csv(args.output_csv, final_jobs)
    write_markdown(args.output_md, final_jobs)

    location_note = ""
    if location_filter.enabled:
        location_note = f" after location filtering ({', '.join(args.location)})"

    print(
        f"Saved {len(final_jobs)} jobs to {args.output_csv} and {args.output_md} "
        f"from {len(targets)} companies{location_note}."
    )

    if args.send_email:
        send_email_from_csv(
            csv_path=args.output_csv,
            subject_prefix=args.email_subject,
            recipients=args.email_to,
        )
        print("Email sent.")
    return 0
