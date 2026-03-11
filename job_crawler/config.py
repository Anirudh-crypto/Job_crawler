from __future__ import annotations

from pathlib import Path

# Default runtime configuration for GitHub Actions or no-args execution.
DEFAULT_COMPANIES_FILE = Path("companies.json")
FALLBACK_COMPANIES_FILE = Path("companies.example.json")

DEFAULT_LOCATIONS = ["Germany", "Bengaluru"]

# Email behavior defaults.
DEFAULT_SEND_EMAIL = True
DEFAULT_EMAIL_RECIPIENTS = ["ani.josh01@gmail.com"]
DEFAULT_EMAIL_SUBJECT = "Job Crawler Results"
