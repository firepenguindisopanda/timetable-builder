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
from datetime import date
from typing import Any, Iterable

import psycopg

from timetable_extractor.database.weeks import TERMS

#: (academic year, semester number), as `publications` files a publication.
TermKey = tuple[str, int]

#: Semester 1 2026/27, the only term before terms existed. A timetable saved
#: then belongs to it, and it is the default of last resort when neither the
#: warehouse nor `TERMS` names one. `latest_publication` and
#: `current_sessions` in schema.sql stay pinned to it; nothing reads them.
LEGACY_TERM: TermKey = ("2026/2027", 1)

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


def choose_default(candidates: Iterable[TermKey], today: date) -> TermKey | None:
    """
    The term a page shows when nothing chose one (SEMESTERS-SPEC.md 7.1).

    The earliest of `candidates` whose teaching has not ended, else the
    newest. Semester 1 2026/27's teaching ended on 20 Nov 2026, so from the
    next day students are advised for semester 2 and the site opens on it.
    Exams are not in the teaching timetable, so they do not hold a term open.
    None when there are no candidates.
    """
    known = sorted(set(candidates))
    running = [t for t in known if t in TERMS and TERMS[t].teaching_ends >= today]
    if running:
        return running[0]
    return known[-1] if known else None


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


def publication_terms(conn: psycopg.Connection) -> dict[int, TermKey]:
    """
    Every loaded publication's term, by id.

    A saved timetable and a calendar subscription each carry the publication
    they were built on and nothing else, so this is how they find their term:
    a v3 timetable saved against publication 16 opens in semester 1, and a
    feed made then keeps serving semester 1 after the default moves on.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, academic_year, semester FROM publications
             WHERE load_revision > 0
               AND academic_year IS NOT NULL AND semester IS NOT NULL
             ORDER BY id
            """
        )
        return {publication_id: (year, semester) for publication_id, year, semester in cur.fetchall()}


__all__ = [
    "FALLBACK_WEEKS",
    "IN_TERM",
    "LEGACY_TERM",
    "TERM_PUBLICATION",
    "TermKey",
    "choose_default",
    "held_terms",
    "publication_terms",
    "in_term",
    "label",
    "params",
    "parse_slug",
    "slug",
    "total_weeks",
]
