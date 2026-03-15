from __future__ import annotations

from typing import Any

import requests

from .constants import USER_AGENT


class HttpClient:
    def __init__(self, timeout_seconds: int) -> None:
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def get(self, url: str) -> requests.Response | None:
        try:
            response = self.session.get(url, timeout=self.timeout_seconds, allow_redirects=True)
            if response.status_code >= 400:
                return None
            content_type = response.headers.get("content-type", "").lower()
            if "text/html" not in content_type and "application/json" not in content_type:
                return None
            return response
        except requests.RequestException:
            return None

    def post_json(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> requests.Response | None:
        try:
            response = self.session.post(
                url,
                json=payload,
                timeout=self.timeout_seconds,
                allow_redirects=True,
                headers=headers,
            )
            if response.status_code >= 400:
                return None
            content_type = response.headers.get("content-type", "").lower()
            if "application/json" not in content_type:
                return None
            return response
        except requests.RequestException:
            return None
