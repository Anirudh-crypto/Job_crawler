from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .models import CompanyTarget, JobResult
from .text import is_allowed_url, normalize_url


def parse_company_targets(path: Path) -> list[CompanyTarget]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    records: list[Any]
    if isinstance(raw, dict) and "companies" in raw:
        records = raw["companies"]
    elif isinstance(raw, list):
        records = raw
    else:
        raise ValueError("Company file must be a list or an object with a 'companies' list.")

    targets: list[CompanyTarget] = []
    for idx, record in enumerate(records, start=1):
        if isinstance(record, str):
            name = urlparse(record).netloc or f"company_{idx}"
            url = record
        elif isinstance(record, dict):
            name = (record.get("name") or "").strip()
            url = (record.get("careers_url") or record.get("url") or "").strip()
            api_post = record.get("api_post")
        else:
            continue

        if not name or not url or not is_allowed_url(url):
            continue

        targets.append(
            CompanyTarget(
                name=name,
                careers_url=normalize_url(url),
                api_post=api_post if isinstance(api_post, dict) else None,
            )
        )

    if not targets:
        raise ValueError("No valid companies found in input file.")
    return targets


def write_csv(path: Path, jobs: list[JobResult]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["company", "title", "location", "job_id", "careers_url", "source"],
        )
        writer.writeheader()
        for job in jobs:
            writer.writerow(
                {
                    "company": job.company,
                    "title": job.title,
                    "location": job.location,
                    "job_id": job.job_id,
                    "careers_url": job.careers_url,
                    "source": job.source,
                }
            )


def write_markdown(path: Path, jobs: list[JobResult]) -> None:
    grouped: dict[str, list[JobResult]] = {}
    for job in jobs:
        grouped.setdefault(job.company, []).append(job)

    lines: list[str] = []
    lines.append("# Filtered ML / Data Science Jobs")
    lines.append("")
    if not grouped:
        lines.append("No relevant jobs found.")
    else:
        for company in sorted(grouped):
            lines.append(f"## {company}")
            lines.append("")
            for job in sorted(grouped[company], key=lambda item: item.title.lower()):
                location = f" ({job.location})" if job.location else ""
                lines.append(f"- [{job.title}]({job.url}){location}")
            lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
