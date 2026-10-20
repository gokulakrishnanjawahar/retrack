"""Heuristic detection of instructions hidden inside data (docs/firewall.md).

Free and fast, so it runs on every run's untrusted content and on every playbook text.
The LLM classifier (classifier.py) covers phrasings these patterns miss.
"""

import base64
import binascii
import re

_I = re.IGNORECASE
_PATTERNS: list[tuple[str, re.Pattern]] = [
    (
        "override",
        re.compile(
            r"\b(ignore|disregard|forget|override)\b[^.\n]{0,30}\b(previous|prior|above|earlier|"
            r"all|any|the|your)\b[^.\n]{0,20}\b(instructions?|prompts?|rules|messages|directions)\b",
            _I,
        ),
    ),
    ("role", re.compile(r"(^|\n)\s*(system|assistant|developer)\s*:", _I)),
    ("role", re.compile(r"<\|?im_(start|end)\|?>|\[/?INST\]|</?(system|assistant)>", _I)),
    (
        "persona",
        re.compile(
            r"\byou are now\b|\bact as (an? )?(admin|administrator|developer|system|root|"
            r"unrestricted)\b|\bnew instructions\s*:",
            _I,
        ),
    ),
    (
        "memory",
        re.compile(
            r"\b(remember|memori[sz]e|store|save)\b[^.\n]{0,30}\b(for|in)\s+(all\s+)?"
            r"(future|later|next)\b|\bfrom now on\b",
            _I,
        ),
    ),
    (
        "memory",
        re.compile(
            r"\b(always|never)\s+(forward|send|approve|share|email|transfer|grant|delete)\b", _I
        ),
    ),
    (
        "exfil",
        re.compile(r"\b(send|post|upload|forward|leak|exfiltrate)\b[^.\n]{0,60}https?://", _I),
    ),
    ("exfil", re.compile(r"!\[[^\]]*\]\(https?://[^)]*\?", _I)),
]
_HIDDEN_UNICODE = re.compile("[​-‏⁠﻿‪-‮⁦-⁩\U000e0000-\U000e007f]")
_BASE64 = re.compile(r"[A-Za-z0-9+/]{24,}={0,2}")

ATTACK_CHECKS = {"override", "role", "persona", "memory", "exfil", "encoded", "hidden_unicode"}


def _snippet(text: str, start: int, end: int) -> str:
    return text[max(start - 20, 0) : min(end + 40, len(text))][:120]


def _decoded_texts(text: str) -> list[str]:
    decoded = []
    for match in _BASE64.finditer(text):
        token = match.group(0)
        try:
            raw = base64.b64decode(token + "=" * (-len(token) % 4), validate=True)
        except (binascii.Error, ValueError):
            continue
        if raw and sum(32 <= b < 127 for b in raw) / len(raw) > 0.95:
            decoded.append(raw.decode("ascii", "ignore"))
    return decoded


def scan(text: str, _depth: int = 0) -> list[tuple[str, str]]:
    """Findings as (check, snippet) pairs; empty when nothing looks like an injection."""
    if not text:
        return []
    findings: list[tuple[str, str]] = []
    seen: set[str] = set()
    for check, pattern in _PATTERNS:
        match = pattern.search(text)
        if match and check not in seen:
            seen.add(check)
            findings.append((check, _snippet(text, match.start(), match.end())))
    hidden = _HIDDEN_UNICODE.search(text)
    if hidden:
        findings.append(("hidden_unicode", f"invisible character U+{ord(hidden.group(0)):04X}"))
    if _depth == 0:
        for decoded in _decoded_texts(text):
            if scan(decoded, _depth=1):
                findings.append(("encoded", f"base64 hides: {decoded[:80]}"))
                break
    return findings
