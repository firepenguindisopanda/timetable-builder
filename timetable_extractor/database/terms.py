"""
Which term a read is about, and how a query restricts itself to it.

The warehouse holds more than one term from 27 Nov 2026 (the semester 2
inspection copy beside semester 1), so every query that used to read "the
current publication" now names its term. It is an explicit argument rather
than a session setting the views read: a request that forgot a setting would
silently serve the default term and nothing would fail, the shape of the
stale-registry fault in CLAUDE.md. SEMESTERS-SPEC.md section 7.2.

A term is `(academic_year, semester)`, the key `weeks.TERMS` and the
`publications` columns already use. In a URL it is a slug, `2026-27-s2`.
"""

from __future__ import annotations

import re
from typing import Any

import psycopg

from timetable_extractor.database.weeks import TERMS

#: (academic year, semester number), as `publications` files a publication.
TermKey = tuple[str, int]

#: The term a page shows when nothing chose one. Pinned to semester 1 until
#: the builder can switch term (phase 3), so loading the inspection copy
#: changes nothing a student sees. `latest_publication` in schema.sql is
#: pinned to the same term and the two must move together.
DEFAULT_TERM: TermKey = ("2026/2027", 1)

#: How many teaching weeks a term outside `TERMS` is given. Semester 1's
#: count, which bounded every week before terms existed.
FALLBACK_WEEKS = 12

#: The term's current publication, for queries that read `sessions` directly.
#: Takes the named parameters `params()` supplies.
TERM_PUBLICATION = (
    "(SELECT id FROM term_publication"
    " WHERE academic_year = %(year)s AND semester = %(semester)s)"
)

def in_term(alias: str | None = None) -> str:
    """
    Restricts `term_sessions` (aliased or not) to one term. `term_semester`,
    because the view's `semester` column is the PDF's own label, as in
    `current_sessions`.
    """
    prefix = f"{alias}." if alias else ""
    return f"{prefix}academic_year = %(year)s AND {prefix}term_semester = %(semester)s"


#: `in_term()` for an unaliased `term_sessions`.
IN_TERM = in_term()

_SLUG = re.compile(r"^(\d{4})-(\d{2})-s(\d)$")


def params(term: TermKey, **extra: Any) -> dict[str, Any]:
    """Named query parameters for `TERM_PUBLICATION` and `IN_TERM`."""
    year, semester = term
    return {"year": year, "semester": semester, **extra}


def slug(term: TermKey) -> str:
    """`("2026/2027", 2)` as `2026-27-s2`, for URLs and cache keys."""
    year, semester = term
    first, second = year.split("/")
    return f"{first}-{second[-2:]}-s{semester}"


def parse_slug(value: str | None) -> TermKey | None:
    """
    `2026-27-s2` back to `("2026/2027", 2)`, or None for anything else.

    The second year must follow the first, so `2026-28-s1` is not a term
    rather than a guess at one.
    """
    match = _SLUG.match((value or "").strip().lower())
    if not match:
        return None
    first, second, semester = match.groups()
    if (int(first) + 1) % 100 != int(second):
        return None
    return f"{first}/{int(first) + 1}", int(semester)


def total_weeks(term: TermKey) -> int:
    """The term's teaching weeks: 12 for semester 1 2026/27, 13 for semester 2."""
    dates = TERMS.get(term)
    return dates.teaching_weeks if dates else FALLBACK_WEEKS


def label(term: TermKey, stage: str | None = None) -> str:
    """"Semester 2 2026/27 (inspection copy)", as a term switch names it."""
    year, semester = term
    first, second = year.split("/")
    text = f"Semester {semester} {first}/{second[-2:]}"
    return f"{text} (inspection copy)" if stage == "inspection" else text


def held_terms(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """
    Every term with a loaded publication, oldest first, with its current one.

    What a `?term=` is checked against and what a term switch lists. A term
    in `TERMS` with nothing loaded is not held: there is no timetable to show.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT academic_year, semester, id, stage, published_at
              FROM term_publication
             WHERE academic_year IS NOT NULL AND semester IS NOT NULL
             ORDER BY academic_year, semester
            """
        )
        return [
            {
                "term": (year, semester),
                "publication_id": publication_id,
                "stage": stage,
                "published_at": published_at,
            }
            for year, semester, publication_id, stage, published_at in cur.fetchall()
        ]


__all__ = [
    "DEFAULT_TERM",
    "FALLBACK_WEEKS",
    "IN_TERM",
    "TERM_PUBLICATION",
    "TermKey",
    "held_terms",
    "in_term",
    "label",
    "params",
    "parse_slug",
    "slug",
    "total_weeks",
]
