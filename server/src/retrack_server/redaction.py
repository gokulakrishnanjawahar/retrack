"""Redaction of secrets and personal data (docs/firewall.md, "Automatic checks").

Runs at ingest, before anything is stored, so raw secrets and personal data never
reach the database, embeddings or an LLM. Matches become placeholders such as
<SECRET> or <EMAIL>, which also help playbooks generalise.
"""

import math
import re
from collections import Counter
from typing import Any

KINDS = ("secret", "email", "phone", "card", "aadhaar", "pan", "ssn")

# Dictionary keys whose values are always secret, whatever they contain.
SENSITIVE_KEY_RE = re.compile(
    r"pass(word|wd)?|pwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|"
    r"authorization|auth[_-]?header|cookie|credential|session[_-]?id",
    re.IGNORECASE,
)

_SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),  # OpenAI, Anthropic
    re.compile(r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{16,}"),  # Stripe
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),  # AWS access key id
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}"),  # GitHub tokens
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),  # Slack
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}"),  # Google API key
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),  # JWT
    re.compile(r"\brtk_(?:live|test)_[0-9a-f]{48}\b"),  # Retrack API keys
]
# These keep their surrounding context; only the captured value is replaced.
_BEARER_RE = re.compile(r"(?i)(\bbearer\s+)[A-Za-z0-9._~+/-]{16,}=*")
_URL_CREDENTIALS_RE = re.compile(r"(://)[^/\s:@]+:[^/\s@]+(@)")
_ASSIGNMENT_RE = re.compile(
    r"(?i)(\b(?:password|passwd|pwd|secret|client[_-]?secret|api[_-]?key|access[_-]?key|"
    r"token)\s*[:=]\s*[\"']?)([^\s\"',;]{4,})"
)
_RANDOM_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9+/_=-])[A-Za-z0-9+/_=-]{24,}")

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_AADHAAR_RE = re.compile(r"(?<!\d)[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}(?!\d)")
_PAN_RE = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")
_SSN_RE = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
_PHONE_RES = [
    re.compile(r"(?<![\w+])\+\d{1,3}(?:[ .-]?\d){7,12}(?!\d)"),  # international
    re.compile(r"(?<![\d.])[6-9]\d{9}(?!\d)"),  # Indian mobile
    re.compile(r"(?<!\d)\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)"),  # North American
]


def _luhn_valid(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


_VERHOEFF_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
    [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
    [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]
_VERHOEFF_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 7, 8, 6, 0],
    [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
    [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]


def _verhoeff_valid(digits: str) -> bool:
    check = 0
    for i, ch in enumerate(reversed(digits)):
        check = _VERHOEFF_D[check][_VERHOEFF_P[i % 8][int(ch)]]
    return check == 0


def _looks_random(token: str) -> bool:
    """Long mixed-case alphanumeric strings with high entropy look like generated secrets."""
    if not (
        any(c.isupper() for c in token)
        and any(c.islower() for c in token)
        and any(c.isdigit() for c in token)
    ):
        return False
    counts = Counter(token)
    entropy = -sum(n / len(token) * math.log2(n / len(token)) for n in counts.values())
    return entropy >= 3.8


def redact_text(text: str) -> tuple[str, dict[str, int]]:
    """Return the text with secrets and personal data replaced, plus counts per kind."""
    counts = dict.fromkeys(KINDS, 0)

    def sub(pattern: re.Pattern, kind: str, replacement: str, valid=None) -> None:
        nonlocal text

        def replace(match: re.Match) -> str:
            if valid and not valid(match):
                return match.group(0)
            counts[kind] += 1
            return match.expand(replacement)

        text = pattern.sub(replace, text)

    for pattern in _SECRET_PATTERNS:
        sub(pattern, "secret", "<SECRET>")
    sub(_BEARER_RE, "secret", r"\g<1><SECRET>")
    sub(_URL_CREDENTIALS_RE, "secret", r"\g<1><SECRET>\g<2>")
    sub(_ASSIGNMENT_RE, "secret", r"\g<1><SECRET>", lambda m: m.group(2) != "<SECRET>")
    sub(_RANDOM_TOKEN_RE, "secret", "<SECRET>", lambda m: _looks_random(m.group(0)))

    sub(_EMAIL_RE, "email", "<EMAIL>")
    digits = lambda m: re.sub(r"\D", "", m.group(0))  # noqa: E731
    sub(_CARD_RE, "card", "<CARD>", lambda m: 13 <= len(digits(m)) <= 19 and _luhn_valid(digits(m)))
    sub(_AADHAAR_RE, "aadhaar", "<AADHAAR>", lambda m: _verhoeff_valid(digits(m)))
    sub(_PAN_RE, "pan", "<PAN>")
    sub(_SSN_RE, "ssn", "<SSN>")
    for pattern in _PHONE_RES:
        sub(pattern, "phone", "<PHONE>")
    return text, counts


def redact_value(value: Any) -> tuple[Any, dict[str, int]]:
    """Redact strings inside JSON-like data; values under sensitive keys become <SECRET>."""
    totals = dict.fromkeys(KINDS, 0)

    def walk(item: Any) -> Any:
        if isinstance(item, str):
            redacted, counts = redact_text(item)
            for kind, n in counts.items():
                totals[kind] += n
            return redacted
        if isinstance(item, dict):
            result = {}
            for key, child in item.items():
                if isinstance(key, str) and SENSITIVE_KEY_RE.search(key) and child is not None:
                    totals["secret"] += 1
                    result[key] = "<SECRET>"
                else:
                    result[key] = walk(child)
            return result
        if isinstance(item, list | tuple):
            return [walk(child) for child in item]
        return item

    return walk(value), totals
