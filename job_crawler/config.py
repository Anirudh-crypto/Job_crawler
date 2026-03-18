from __future__ import annotations

from pathlib import Path

# Default runtime configuration for GitHub Actions or no-args execution.
DEFAULT_COMPANIES_FILE = Path("companies.json")
FALLBACK_COMPANIES_FILE = Path("companies.example.json")

DEFAULT_LOCATIONS = ["Germany", "Bengaluru"]
DEFAULT_MAX_AGE_DAYS = 2
DEFAULT_MAX_PAGES_PER_COMPANY = 20
DEFAULT_ENABLE_PLAYWRIGHT_FALLBACK = True
DEFAULT_ENABLE_SUPABASE_SENT_JOBS = True
DEFAULT_ENABLE_SUPABASE_COMPANIES = True
DEFAULT_SUPABASE_SENT_JOBS_TABLE = "sent_jobs"
DEFAULT_SUPABASE_COMPANIES_TABLE = "companies"

# Email behavior defaults.
DEFAULT_SEND_EMAIL = True
DEFAULT_EMAIL_RECIPIENTS = ["ani.josh01@gmail.com"]
DEFAULT_EMAIL_SUBJECT = "Job Crawler Results"
