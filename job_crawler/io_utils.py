from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .models import CompanyTarget
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

    return parse_company_target_records(records)


def parse_company_target_records(records: list[Any]) -> list[CompanyTarget]:
    targets: list[CompanyTarget] = []
    for idx, record in enumerate(records, start=1):
        api_post = None
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
