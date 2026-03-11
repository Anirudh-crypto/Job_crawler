from __future__ import annotations

import re

from .constants import RELEVANT_PHRASES, ROLE_WORDS
from .text import normalize_text


class JobRelevance:
    def is_relevant(self, text: str) -> bool:
        if not text:
            return False
        lowered = normalize_text(text)
        if any(phrase in lowered for phrase in RELEVANT_PHRASES):
            return True
        return bool(re.search(r"\bml\b", lowered))

    def has_role_indicator(self, text: str) -> bool:
        if not text:
            return False
        lowered = normalize_text(text)
        if any(word in lowered for word in ROLE_WORDS):
            return True
        return bool(re.search(r"\b(swe|sde|mle)\b", lowered))
