"""
Resolve staff names read from PDFs against CELCAT's canonical list.

Narrow timetable columns wrap names mid-word, and pdfplumber rejoins the
fragments with a space. The same person therefore appears as "ADEYANJU,
Anthony", "ADEYANJU ,Anthony" and "ALEXANDE R,Rhea". finder.xml publishes one
authoritative spelling per staff member, so matching on the whitespace-free
form collapses the variants back onto it.
"""

from __future__ import annotations

import re

_WHITESPACE = re.compile(r"\s+")


def name_key(name: str) -> str:
    """Whitespace-free, case-folded form used to match spelling variants."""
    return _WHITESPACE.sub("", name).lower()


def tidy_name(name: str) -> str:
    """Collapse repeated spaces and the space CELCAT leaves before a comma."""
    cleaned = _WHITESPACE.sub(" ", name).strip()
    return re.sub(r"\s+,", ",", cleaned)


def build_name_index(canonical_names: list[str]) -> dict[str, str]:
    """
    Map every match key to its canonical spelling.

    Where two canonical names collapse to the same key the first wins; they
    are the same person spelled two ways in the index itself.
    """
    index: dict[str, str] = {}
    for name in canonical_names:
        index.setdefault(name_key(name), name)
    return index


def resolve_name(raw: str, index: dict[str, str]) -> str:
    """
    Return the canonical spelling for `raw`, or a tidied version of it.

    Falling back to the tidied name keeps people who are not in the index -
    visiting lecturers, say - rather than dropping them.
    """
    return index.get(name_key(raw)) or tidy_name(raw)
