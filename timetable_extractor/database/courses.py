"""
Resolve course codes read from PDFs against CELCAT's canonical list.

Two things corrupt a code inside a class block. Narrow columns wrap it
mid-word, so "CLL PORTUGUESE 1A" arrives as "CLL PORTUGU ESE 1A"; and text
that follows the code on the same line gets swallowed, giving
"FOUN 1001 (FULL & PART- TIME)" or "IENG 3017 LALLA,TERRENCE".

Left alone each variant becomes its own course row, splitting a real course's
timetable in two. finder.xml lists every course the university publishes, so
it is the authority to snap back to.

The same problem arrives from the other direction once the warehouse is loaded:
a code typed into a URL, pasted from a registration screenshot, or sent to the
timetable API has to be matched against what was published. That is the second
half of this module.
"""

from __future__ import annotations

import re

import psycopg

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


# Matching a code someone typed against what was published


def normalise_course_code(code: str) -> str:
    """
    Accept "comp2601", "COMP 2601" or "comp-2601" and return "COMP 2601".

    Codes are stored with a single space between the subject prefix and the
    number, but a URL is just as likely to arrive without it.

    Lossy on codes that are not that shape, which is why nothing should match
    on its output alone. See `published_code_candidates`.
    """
    cleaned = " ".join(code.replace("-", " ").replace("_", " ").split()).upper()
    if " " in cleaned:
        return cleaned

    # Split a run-together code at the first digit: "COMP2601" -> "COMP 2601".
    for i, char in enumerate(cleaned):
        if char.isdigit():
            return f"{cleaned[:i]} {cleaned[i:]}" if i else cleaned
    return cleaned


def published_code_candidates(raw: str) -> list[str]:
    """
    The match keys to try for a caller-supplied code, best first.

    `normalise_course_code` assumes every code is the "SUBJ 1234" shape, and
    several published codes are not. Matching on its output alone reports real
    courses as missing, in two different ways:

    * It splits "WW101" and "GW101" at the first digit, giving "WW 101". Here
      `code_key` covers for it by ignoring spacing on both sides.
    * It turns the hyphen inside "FOUN 1001 (FULL & PART-TIME)" into a space,
      which `code_key` cannot undo because the hyphen is gone. Nothing covers
      for that except trying what the caller wrote first, which is why the
      order here is load-bearing rather than tidy.

    The normalised form still earns its place second: it is what accepts the
    hyphen-separated "comp-2601" that the explorer's URLs allow, since
    `code_key` keeps hyphens.
    """
    keys = [code_key(raw), code_key(normalise_course_code(raw))]
    # dict.fromkeys rather than a set, because order is the whole point.
    return [key for key in dict.fromkeys(keys) if key]


def resolve_published_code(raw: str, index: dict[str, str]) -> str | None:
    """
    Map a caller-supplied code onto the spelling the warehouse holds.

    Returns None rather than the input when nothing matches, because callers
    report unknown codes to the student rather than querying for them.
    """
    for key in published_code_candidates(raw):
        published = index.get(key)
        if published:
            return published
    return None


def find_published_code(cur: psycopg.Cursor, raw: str) -> str | None:
    """
    The same lookup against the database, for the one-course-at-a-time paths.

    A page view for a single course should not pull all 1,082 codes across to
    build an index it uses once, so the match runs in SQL instead. The
    expression rules out the index on `courses.code`, which is of no
    consequence over a table this size.
    """
    for key in published_code_candidates(raw):
        cur.execute(
            """
            SELECT code
              FROM courses
             WHERE upper(regexp_replace(code, '\\s', '', 'g')) = %s
             ORDER BY code
             LIMIT 1
            """,
            (key,),
        )
        row = cur.fetchone()
        if row:
            return row[0]
    return None
