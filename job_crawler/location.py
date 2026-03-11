from __future__ import annotations

from .constants import LOCATION_ALIASES
from .models import JobResult
from .text import normalize_text


class LocationFilter:
    def __init__(self, raw_locations: list[str] | None = None) -> None:
        self.raw_locations = [entry for entry in (raw_locations or []) if entry.strip()]
        self.expanded_terms = self._expand_terms(self.raw_locations)

    @property
    def enabled(self) -> bool:
        return bool(self.expanded_terms)

    def matches_text(self, text: str) -> bool:
        if not self.enabled:
            return True
        haystack = normalize_text(text)
        return any(term in haystack for term in self.expanded_terms)

    def matches_job(self, job: JobResult) -> bool:
        return self.matches_text(f"{job.location} {job.title} {job.url}")

    def workday_terms(self) -> list[str]:
        return self.expanded_terms

    def _expand_terms(self, raw_locations: list[str]) -> list[str]:
        expanded: set[str] = set()
        for raw in raw_locations:
            normalized = normalize_text(raw)
            if not normalized:
                continue
            expanded.add(normalized)
            for alias in LOCATION_ALIASES.get(normalized, []):
                alias_value = normalize_text(alias)
                if alias_value:
                    expanded.add(alias_value)
        return sorted(expanded)
