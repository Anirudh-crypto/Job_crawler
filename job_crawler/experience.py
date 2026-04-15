from __future__ import annotations

import re

from .models import JobResult
from .text import normalize_text


EARLY_CAREER_TITLE_HINTS = (
    "intern",
    "internship",
    "graduate",
    "new grad",
    "university graduate",
    "entry level",
    "entry-level",
    "junior",
    "associate",
    "apprentice",
    "trainee",
    "campus",
)

SENIOR_TITLE_HINTS = (
    "senior",
    "sr ",
    "sr.",
    "staff",
    "principal",
    "lead",
    "manager",
    "director",
    "head",
    "architect",
)


class ExperienceFilter:
    def __init__(self, max_years: int | None) -> None:
        self.max_years = max_years if max_years and max_years > 0 else None

    def matches_job(self, job: JobResult) -> bool:
        if self.max_years is None:
            return True

        title = normalize_text(job.title)
        if self._has_early_career_title_hint(title):
            return True
        if self._has_senior_title_hint(title):
            return False

        text = " ".join(
            part.strip()
            for part in [job.title, job.experience_text]
            if isinstance(part, str) and part.strip()
        )
        if not text:
            return True

        signals = self._extract_year_signals(text)
        if not signals:
            return True

        return max(signals) < self.max_years

    def _has_early_career_title_hint(self, title: str) -> bool:
        return any(hint in title for hint in EARLY_CAREER_TITLE_HINTS)

    def _has_senior_title_hint(self, title: str) -> bool:
        if any(hint in title for hint in SENIOR_TITLE_HINTS):
            return True
        return bool(re.search(r"\bsr\b", title))

    def _extract_year_signals(self, text: str) -> list[int]:
        lowered = text.lower()
        signals: list[int] = []

        range_patterns = [
            r"\b(\d{1,2})\s*(?:-|–|to)\s*(\d{1,2})\s*\+?\s+years?\b",
        ]
        for pattern in range_patterns:
            for start, end in re.findall(pattern, lowered):
                signals.append(max(int(start), int(end)))

        direct_patterns = [
            r"\b(\d{1,2})\+\s+years?\b",
            r"\bat least\s+(\d{1,2})\s+years?\b",
            r"\bminimum\s+(\d{1,2})\s+years?\b",
            r"\bmin(?:imum)?\.?\s+(\d{1,2})\s+years?\b",
            r"\b(\d{1,2})\s+years?\s+of\s+(?:relevant\s+|professional\s+|industry\s+|work\s+)?experience\b",
            r"\bexperience\s+of\s+(\d{1,2})\s+years?\b",
            r"\b(\d{1,2})\s+years?\s+experience\b",
            r"\brequire(?:s|d)?\s+(\d{1,2})\s+years?\b",
        ]
        for pattern in direct_patterns:
            for value in re.findall(pattern, lowered):
                signals.append(int(value))

        return signals
