"""
Weeks that have passed are history, not a change.

CELCAT exports each timetable from the current teaching week to the end of the
semester. Teaching began on 1 September 2026, so the PDFs pulled on 11 September
were all titled "(Wks W2-W12)" where the week before they had said
"(Wks W1-W12)". The warehouse stored what the PDFs printed, and the result
looked like a catastrophe: the diff reported 1,624 classes moved when 99 had,
a student was told a lecture running W1-W12 "now runs W2-W12", and every
weekly republish until the end of the semester would have done it again.

A week before the export horizon cannot change any more, so the only authority
on it is the last publication that still covered it. The loader therefore
takes those weeks from the previous publication and only the weeks from the
horizon on from the new PDFs. Each load merges against a publication that
already carries its own history, so week 1 survives to week 12.

What this never does is invent a week. Past weeks come only from a sitting the
previous publication actually published in the same slot, and when more than
one earlier sitting could be the source and none is an exact match, the record
is left exactly as printed and the ambiguity is reported.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import psycopg

from timetable_extractor.database.records import SessionRecord
from timetable_extractor.database.weeks import render_weeks
from timetable_extractor.observability import Diagnostics


@dataclass(frozen=True)
class EarlierSitting:
    """One session of the previous publication, reduced to what carrying needs."""

    course_code: str
    activity_type: str | None
    stream_label: str | None
    day: str
    start_min: int
    end_min: int
    room_code: str | None
    weeks_raw: str | None
    weeks: tuple[int, ...]


def slot_key(
    course_code: str,
    activity_type: str | None,
    stream_label: str | None,
    day: str,
    start_min: int,
    end_min: int,
    room_code: str | None,
) -> tuple:
    """
    Where a class sits, without its weeks.

    Everything in a session's identity except the weeks, because the weeks are
    the one part the export horizon changes. The room stays in: a class that
    moved room has no earlier sitting in its new one to inherit weeks from.
    """
    return (
        course_code,
        activity_type or "",
        stream_label or "",
        day,
        start_min,
        end_min,
        room_code or "",
    )


def record_horizon(record: SessionRecord, horizons: dict[str, int | None]) -> int | None:
    """
    The export horizon a merged record was printed under.

    The lowest horizon among its source PDFs. Every PDF in one pull should
    agree, but a pull that straddles midnight on a Sunday would not, and a week
    that any source still printed must not be treated as past.
    """
    known = [h for source in record.sources if (h := horizons.get(source))]
    return min(known) if known else None


def carry_past_weeks(
    records: Iterable[SessionRecord],
    earlier: Iterable[EarlierSitting],
    horizons: dict[str, int | None],
    diagnostics: Diagnostics | None = None,
) -> int:
    """
    Restore the weeks before the horizon from the previous publication.

    Mutates the records and returns how many gained weeks. For each record, the
    earlier sittings in the same slot are the candidates. One whose weeks from
    the horizon on equal what the PDF printed is an exact match; failing that,
    a single candidate is still the same class whose upcoming weeks changed.
    Several candidates with no exact match is ambiguous and left alone.

    When the reconstructed weeks equal the earlier sitting's, its week string
    is reused verbatim rather than re-rendered. That is what a saved timetable
    compares against, and an unchanged class must read as unchanged.
    """
    by_slot: dict[tuple, list[EarlierSitting]] = {}
    for sitting in earlier:
        key = slot_key(
            sitting.course_code,
            sitting.activity_type,
            sitting.stream_label,
            sitting.day,
            sitting.start_min,
            sitting.end_min,
            sitting.room_code,
        )
        by_slot.setdefault(key, []).append(sitting)

    carried = 0
    for record in records:
        horizon = record_horizon(record, horizons)
        # Nothing has passed yet, or the PDF did not say. A record with no
        # weeks reads as "every week", and giving it past weeks would narrow it.
        if not horizon or horizon <= 1 or not record.weeks:
            continue

        candidates = by_slot.get(
            slot_key(
                record.course_code,
                record.activity_type,
                record.stream_label,
                record.day,
                record.start_min,
                record.end_min,
                record.room_code,
            ),
            [],
        )
        if not candidates:
            continue

        printed = set(record.weeks)
        exact = [c for c in candidates if {w for w in c.weeks if w >= horizon} == printed]
        chosen = exact or (candidates if len(candidates) == 1 else [])
        if not chosen:
            if diagnostics is not None:
                diagnostics.add(
                    "past_weeks_ambiguous",
                    course=record.course_code,
                    day=record.day,
                    start_min=record.start_min,
                    printed=record.weeks_raw,
                    earlier=[c.weeks_raw for c in candidates],
                )
            continue

        past = {w for c in chosen for w in c.weeks if w < horizon} - printed
        if not past:
            continue

        weeks = sorted(past | printed)
        if len(chosen) == 1 and weeks == list(chosen[0].weeks):
            record.weeks_raw = chosen[0].weeks_raw
        else:
            record.weeks_raw = render_weeks(weeks)
        record.weeks = weeks
        if record.week_count is not None:
            record.week_count += len(past)
        carried += 1

    return carried


def earlier_sittings(conn: psycopg.Connection, publication_id: int) -> list[EarlierSitting]:
    """Every session of a publication, in the shape `carry_past_weeks` reads."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.code, s.activity_type, s.stream_label, s.day::text,
                   s.start_min, s.end_min, r.code, s.weeks_raw, s.weeks
              FROM sessions s
              JOIN courses c ON c.id = s.course_id
              LEFT JOIN rooms r ON r.id = s.room_id
             WHERE s.publication_id = %s
            """,
            (publication_id,),
        )
        return [
            EarlierSitting(
                course_code=row[0],
                activity_type=row[1],
                stream_label=row[2],
                day=row[3],
                start_min=row[4],
                end_min=row[5],
                room_code=row[6],
                weeks_raw=row[7],
                weeks=tuple(row[8] or ()),
            )
            for row in cur.fetchall()
        ]
