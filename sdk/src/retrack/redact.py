"""Strip obvious secrets before a run is sent (docs/constraints.md, SDK rules).

The server does the full secret and personal-data redaction; this is a first line of
defence so well-known credentials never leave the customer's process.
"""

import re
from typing import Any

_SENSITIVE_KEY_RE = re.compile(
    r"pass(word|wd)?|pwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|"
    r"authorization|cookie|credential",
    re.IGNORECASE,
)
_PATTERNS = [
    (
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
        "<SECRET>",
    ),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"), "<SECRET>"),
    (re.compile(r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{16,}"), "<SECRET>"),
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "<SECRET>"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}"), "<SECRET>"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}"), "<SECRET>"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"), "<SECRET>"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{35}"), "<SECRET>"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"), "<SECRET>"),
    (re.compile(r"\brtk_(?:live|test)_[0-9a-f]{48}\b"), "<SECRET>"),
    (re.compile(r"(?i)(\bbearer\s+)[A-Za-z0-9._~+/-]{16,}=*"), r"\g<1><SECRET>"),
    (re.compile(r"(://)[^/\s:@]+:[^/\s@]+(@)"), r"\g<1><SECRET>\g<2>"),
    (
        re.compile(
            r"(?i)(\b(?:password|passwd|pwd|secret|client[_-]?secret|api[_-]?key|access[_-]?key|"
            r"token)\s*[:=]\s*[\"']?)(?!<SECRET>)[^\s\"',;]{4,}"
        ),
        r"\g<1><SECRET>",
    ),
]


def redact_secrets(value: Any) -> Any:
    """Return a copy of JSON-like data with well-known secrets replaced by <SECRET>."""
    if isinstance(value, str):
        for pattern, replacement in _PATTERNS:
            value = pattern.sub(replacement, value)
        return value
    if isinstance(value, dict):
        return {
            key: "<SECRET>"
            if isinstance(key, str) and _SENSITIVE_KEY_RE.search(key) and child is not None
            else redact_secrets(child)
            for key, child in value.items()
        }
    if isinstance(value, list | tuple):
        return [redact_secrets(child) for child in value]
    return value
