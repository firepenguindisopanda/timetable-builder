"""
Resolve course codes read from PDFs against CELCAT's canonical list.

Two things corrupt a code inside a class block. Narrow columns wrap it
mid-word, so "CLL PORTUGUESE 1A" arrives as "CLL PORTUGU ESE 1A"; and text
that follows the code on the same line gets swallowed, giving
"FOUN 1001 (FULL & PART- TIME)" or "IENG 3017 LALLA,TERRENCE".

Left alone each variant becomes its own course row, splitting a real course's
timetable in two. finder.xml lists every course the university publishes, so
it is the authority to snap back to.
"""

from __future__ import annotations

import re

_WHITESPACE = re.compile(r"\s+")


def code_key(code: str) -> str:
    """Whitespace-free, case-folded form used to match spelling variants."""
    return _WHITESPACE.sub("", code).upper()


def build_code_index(canonical_codes: list[str]) -> dict[str, str]:
    """Map every match key to its canonical course code."""
    index: dict[str, str] = {}
    for code in canonical_codes:
        index.setdefault(code_key(code), code)
    return index


def resolve_course_code(raw: str, index: dict[str, str]) -> str:
    """
    Return the canonical code for `raw`, or `raw` unchanged.

    Tries the whole string first, which repairs wrapped codes. Failing that it
    walks back one token at a time and takes the *longest* prefix that is a
    real course, which strips trailing junk without truncating a legitimate
    multi-word code such as "CAPE BIOL".
    """
    exact = index.get(code_key(raw))
    if exact:
        return exact

    tokens = raw.split()
    for end in range(len(tokens) - 1, 0, -1):
        candidate = index.get(code_key(" ".join(tokens[:end])))
        if candidate:
            return candidate

    return raw
