from __future__ import annotations

from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .constants import KNOWN_JOB_HOST_MARKERS
from .http_client import HttpClient
from .text import is_allowed_url, normalize_url


class AtsResolver:
    def __init__(self, http: HttpClient) -> None:
        self.http = http

    def resolve(self, careers_url: str) -> list[str]:
        parsed = urlparse(careers_url)
        if any(marker in parsed.netloc.lower() for marker in KNOWN_JOB_HOST_MARKERS):
            return [careers_url]

        response = self.http.get(careers_url)
        if response is None:
            return [careers_url]
        if "text/html" not in response.headers.get("content-type", "").lower():
            return [careers_url]

        soup = BeautifulSoup(response.text, "html.parser")
        candidates: list[str] = []

        for tag in soup.find_all(["a", "link", "script", "iframe"]):
            url = (
                tag.get("href")
                or tag.get("src")
                or tag.get("data-src")
                or tag.get("data-url")
                or ""
            )
            if not url:
                continue
            normalized = normalize_url(
                url,
                remove_tracking=False,
                drop_fragment=False,
                trim_trailing_slash=False,
            )
            if not is_allowed_url(normalized):
                continue
            host = urlparse(normalized).netloc.lower()
            if any(marker in host for marker in KNOWN_JOB_HOST_MARKERS):
                candidates.append(normalized)

        if not candidates:
            return [careers_url]

        # Preserve order but remove duplicates.
        deduped: list[str] = []
        seen: set[str] = set()
        for url in candidates:
            if url in seen:
                continue
            seen.add(url)
            deduped.append(url)
        return deduped
