from __future__ import annotations

import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .constants import ALLOWED_SCHEMES, KNOWN_JOB_HOST_MARKERS, TRACKING_QUERY_KEYS


def normalize_text(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value or "")
    ascii_text = folded.encode("ascii", "ignore").decode("ascii")
    ascii_text = ascii_text.lower().replace("-", " ").replace("/", " ")
    return re.sub(r"\s+", " ", ascii_text).strip()


def normalize_url(
    raw_url: str,
    *,
    remove_tracking: bool = True,
    drop_fragment: bool = True,
    trim_trailing_slash: bool = True,
) -> str:
    parsed = urlparse(raw_url.strip())
    if remove_tracking:
        query_items = [
            (k, v)
            for (k, v) in parse_qsl(parsed.query, keep_blank_values=True)
            if k.lower() not in TRACKING_QUERY_KEYS and not k.lower().startswith("utm_")
        ]
        query = urlencode(query_items, doseq=True)
    else:
        query = parsed.query

    path = parsed.path
    if trim_trailing_slash:
        path = path.rstrip("/") or "/"
    elif not path:
        path = "/"

    cleaned = parsed._replace(
        fragment="" if drop_fragment else parsed.fragment,
        query=query,
        path=path,
    )
    return urlunparse(cleaned)


def is_allowed_url(raw_url: str) -> bool:
    parsed = urlparse(raw_url)
    return parsed.scheme in ALLOWED_SCHEMES and bool(parsed.netloc)


def is_known_job_host(hostname: str) -> bool:
    host = hostname.lower()
    return any(marker in host for marker in KNOWN_JOB_HOST_MARKERS)


def same_company_scope(start_host: str, candidate_host: str) -> bool:
    start = start_host.lower()
    candidate = candidate_host.lower()
    if start == candidate:
        return True
    if candidate.endswith("." + start) or start.endswith("." + candidate):
        return True
    if is_known_job_host(candidate):
        return True
    return False


def title_from_url(job_url: str) -> str:
    path = urlparse(job_url).path.strip("/")
    if not path:
        return "Unknown role"
    last = path.split("/")[-1]
    last = re.sub(r"[-_]+", " ", last)
    last = re.sub(r"\d+", " ", last)
    cleaned = re.sub(r"\s+", " ", last).strip()
    if not cleaned:
        return "Unknown role"
    return cleaned.title()


def extract_workday_site(path: str) -> str:
    parts = [part for part in path.strip("/").split("/") if part]
    if not parts:
        return ""
    first = parts[0]
    if re.fullmatch(r"[a-z]{2}-[a-z]{2}", first.lower()) and len(parts) > 1:
        return parts[1]
    return first


def extract_job_id(text: str) -> str:
    if not text:
        return ""
    candidates = [
        r"\bJR\d{5,}\b",
        r"\bREQ\d{4,}\b",
        r"\bR\d{5,}\b",
        r"\bJob\s?ID[:\s#-]*([A-Za-z0-9-]+)\b",
        r"\bReq(?:uisition)?\s?ID[:\s#-]*([A-Za-z0-9-]+)\b",
    ]
    for pattern in candidates:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        if match.groups():
            return match.group(1)
        return match.group(0)
    return ""
