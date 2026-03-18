#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from job_crawler.config import DEFAULT_COMPANIES_FILE, FALLBACK_COMPANIES_FILE
from job_crawler.io_utils import parse_company_targets
from job_crawler.supabase_store import SupabaseCompaniesStore, SupabaseStoreError


def main() -> int:
    load_dotenv()

    companies_file = DEFAULT_COMPANIES_FILE
    if not companies_file.exists() and FALLBACK_COMPANIES_FILE.exists():
        companies_file = FALLBACK_COMPANIES_FILE

    store = SupabaseCompaniesStore.from_env(timeout_seconds=15)
    if store is None:
        print(
            "Supabase is not configured. Set SUPABASE_URL and SUPABASE_SECRET_KEY first.",
            file=sys.stderr,
        )
        return 2

    try:
        targets = parse_company_targets(Path(companies_file))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Error reading company list: {exc}", file=sys.stderr)
        return 2

    try:
        inserted_count, updated_count = store.sync_company_targets(targets)
    except SupabaseStoreError as exc:
        print(f"Supabase company sync failed: {exc}", file=sys.stderr)
        return 2

    print(
        f"Synced {len(targets)} companies from {companies_file} "
        f"({inserted_count} inserted, {updated_count} updated)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
