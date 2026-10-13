"""
The calendar subscription feed's view of a student's timetable.

A subscription link is fetched by Google, Apple or Outlook every few hours for
the rest of the semester, long after the student built the timetable. Nothing
is stored about them (UX-IMPROVEMENT-PLAN.md 4.3: no table, no data at rest),
so the link itself carries their choices, and every fetch resolves those
choices against whatever UWI has published since.

The resolving is the browser's job too. Every republish stores every session
as a new row, so the builder used to drop a student's whole timetable on
"Update my courses" and place it again from scratch, unpinning what they had
chosen. `assets/js/slot-identity.js` fixed that with the rules below, and this
module mirrors it rule for rule: `tests/fixtures/slot_resolution.json` holds
both to the same answers, so a student's phone and their browser cannot
disagree about which lab they take. See SUBSCRIPTION-FEED-SPEC.md.

Pure: sessions in, a plan of events out. The route does the database reads.
"""

from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass, field
from typing import Any

#: The token format. A link made by a newer page than this server is refused
#: rather than half-read.
TOKEN_VERSION = 1

#: Longer than any real timetable needs (six courses is about 300), short
#: enough that a pasted novel is refused before it is decoded.
MAX_TOKEN_LENGTH = 2048

#: Matches `MAX_CODES_PER_REQUEST` in explore_router.py: no student takes 40
#: courses, so a token claiming more is not one.
MAX_TOKEN_COURSES = 40

#: A course holds a handful of placements; a few dozen is already absurd.
MAX_PICKS_PER_COURSE = 32

_HASH = re.compile(r"^[0-9a-f]{8}$")

#: Stands in for an empty activity type, as `UNSPECIFIED_TYPE` does in
#: option-groups.js, so grouping by type has a key.
UNSPECIFIED_TYPE = "Unspecified"

#: The dated one-offs that are listed by date rather than placed weekly.
#: Mirrors `DATED_TYPES` in option-groups.js, which explains the choice.
DATED_TYPES = frozenset(
    {
        "Examination",
        "Lecture Relocated",
        "Lecture Make-up",
        "Tutorial (make-up/relocated)",
    }
)


# Slot identity


def fnv1a_hex(text: str, seed: int = 0x811C9DC5) -> str:
    """
    FNV-1a over UTF-16 code units, as eight hex digits.

    UTF-16 rather than UTF-8 because that is what JavaScript's `charCodeAt`
    walks, and the browser computes the hashes that end up in a link.
    """
    hash_ = seed & 0xFFFFFFFF
    data = text.encode("utf-16-le")
    for i in range(0, len(data), 2):
        hash_ ^= data[i] | (data[i + 1] << 8)
        hash_ = (hash_ * 0x01000193) & 0xFFFFFFFF
    return f"{hash_:08x}"


def type_of(session: dict[str, Any]) -> str:
    return session.get("type") or UNSPECIFIED_TYPE


def slot_key(session: dict[str, Any]) -> str:
    """Type, day, times, room, stream and weeks: what a sitting is."""
    weeks = session.get("weeks")
    return "|".join(
        [
            session.get("type") or "",
            session.get("day") or "",
            session.get("startTime") or "",
            session.get("endTime") or "",
            session.get("room") or "",
            session.get("streamLabel") or "",
            ",".join(str(w) for w in sorted(set(weeks))) if isinstance(weeks, list) else "",
        ]
    )


def slot_hash(session: dict[str, Any]) -> str:
    return fnv1a_hex(slot_key(session))


def _same_time(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return (
        a.get("day") == b.get("day")
        and a.get("startTime") == b.get("startTime")
        and a.get("endTime") == b.get("endTime")
        and (a.get("streamLabel") or "") == (b.get("streamLabel") or "")
    )


def resolve_slot(
    old: dict[str, Any] | None,
    old_of_type: list[dict[str, Any]],
    new_of_type: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """
    The session a choice made in an older publication now means, or None.

    The rules of `resolveSlot` in slot-identity.js, in its order: the same
    slot; the only class at the same day and time; the one class that arrived
    when ours was the one that went; the type's only class. Anything else is
    None, because a guess puts a student in the wrong room.
    """
    if old is None:
        return None
    key = slot_key(old)
    for session in new_of_type:
        if slot_key(session) == key:
            return session

    same_time = [s for s in new_of_type if _same_time(s, old)]
    if len(same_time) == 1:
        return same_time[0]

    new_keys = {slot_key(s) for s in new_of_type}
    old_keys = {slot_key(s) for s in old_of_type}
    gone = [s for s in old_of_type if slot_key(s) not in new_keys]
    arrived = [s for s in new_of_type if slot_key(s) not in old_keys]
    if len(gone) == 1 and len(arrived) == 1 and slot_key(gone[0]) == key:
        return arrived[0]

    if len(new_of_type) == 1:
        return new_of_type[0]
    return None


# The token


class TokenError(ValueError):
    """A subscription link that is not one this server can read."""


@dataclass(frozen=True)
class TokenCourse:
    code: str
    picks: tuple[str, ...]
    dismissed: tuple[str, ...] = ()


@dataclass(frozen=True)
class Token:
    publication_id: int
    courses: tuple[TokenCourse, ...]


def encode_token(token: Token) -> str:
    """The inverse of `decode_token`, for tests; the browser makes real ones."""
    parts = []
    for course in token.courses:
        part = f"{course.code}:{','.join(course.picks)}"
        if course.dismissed:
            part += "!" + ",".join(course.dismissed)
        parts.append(part)
    payload = f"{TOKEN_VERSION}|{token.publication_id}|{';'.join(parts)}"
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def decode_token(raw: str) -> Token:
    """
    Read a subscription token, refusing anything malformed.

    Strict on purpose. The link is public and arbitrary text arrives on it, so
    every field is checked for shape and every list is bounded before any of
    it reaches a query.
    """
    if not raw or len(raw) > MAX_TOKEN_LENGTH:
        raise TokenError("token is empty or too long")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", raw):
        raise TokenError("token is not base64url")
    try:
        payload = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise TokenError("token does not decode") from exc

    head = payload.split("|", 2)
    if len(head) != 3:
        raise TokenError("token has no version or publication")
    version, publication, body = head
    if version != str(TOKEN_VERSION):
        raise TokenError(f"token version {version!r} is not {TOKEN_VERSION}")
    if not publication.isdigit() or len(publication) > 12:
        raise TokenError("token publication is not a number")

    courses = []
    seen = set()
    for part in body.split(";") if body else []:
        code, sep, rest = part.partition(":")
        code = code.strip()
        if not sep or not code or len(code) > 64 or code in seen:
            raise TokenError("token course is malformed")
        seen.add(code)
        picks_text, _, dismissed_text = rest.partition("!")
        picks = tuple(p for p in picks_text.split(",") if p)
        dismissed = tuple(d for d in dismissed_text.split(",") if d)
        if len(picks) > MAX_PICKS_PER_COURSE or len(dismissed) > MAX_PICKS_PER_COURSE:
            raise TokenError("token course has too many classes")
        if not all(_HASH.match(p) for p in picks):
            raise TokenError("token class is not a slot hash")
        if any(len(d) > 64 for d in dismissed):
            raise TokenError("token type is too long")
        courses.append(TokenCourse(code, picks, dismissed))

    if not courses or len(courses) > MAX_TOKEN_COURSES:
        raise TokenError("token names no courses, or too many")
    return Token(int(publication), tuple(courses))


# The plan of a feed


@dataclass
class Note:
    """
    An all-day reminder in place of a class that could not be resolved.

    The feed never guesses, so what it cannot place it says, in the calendar
    the student is actually looking at.
    """

    code: str
    kind: str
    summary: str
    detail: str
    type: str | None = None


@dataclass
class FeedPlan:
    #: Weekly classes as event dicts: the session's fields plus `courseKey`,
    #: `code`, `courseTitle`, the same shape the browser exports.
    weekly: list[dict[str, Any]] = field(default_factory=list)
    #: Every dated one-off on the courses, each sitting listed.
    dated: list[dict[str, Any]] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)
    #: How many picks resolved by each rule, for the log.
    resolved: int = 0
    followed: int = 0


_DAY_SHORT = {
    "Monday": "Mon", "Tuesday": "Tue", "Wednesday": "Wed", "Thursday": "Thu",
    "Friday": "Fri", "Saturday": "Sat", "Sunday": "Sun",
}

_RESUBSCRIBE = (
    "Open your timetable to choose, then subscribe again with the new link. "
    "Until then this calendar leaves it out rather than guess."
)


def _when(session: dict[str, Any]) -> str:
    day = _DAY_SHORT.get(session.get("day") or "", session.get("day") or "")
    return f"{day} {session.get('startTime') or ''}".strip()


def _event(course: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
    return {
        **session,
        "courseKey": course["code"],
        "code": course["code"],
        "courseTitle": course.get("title") or course["code"],
    }


def plan_feed(
    token: Token,
    current: dict[str, dict[str, Any]],
    previous: dict[str, list[dict[str, Any]]] | None,
) -> FeedPlan:
    """
    What a subscribed calendar should hold now.

    `current` maps each published code to its course as `sessions_for_courses`
    shapes it. `previous` maps codes to their sessions in the token's own
    publication, or is None when that publication is not held; without it only
    picks whose slot is still published, or whose type has one class left, can
    resolve.

    Re-resolution only, never re-optimising: a class the token did not choose
    is placed only when there is a single one to place.
    """
    plan = FeedPlan()
    previous = previous or {}

    for wanted in token.courses:
        course = current.get(wanted.code)
        if course is None:
            plan.notes.append(
                Note(
                    wanted.code,
                    "course",
                    f"{wanted.code} is not in UWI's latest timetable",
                    "It may have been renamed or withdrawn. Open your timetable to check.",
                )
            )
            continue

        sessions = course.get("sessions") or []
        by_hash = {slot_hash(s): s for s in sessions}
        old_sessions = previous.get(wanted.code) or []
        old_by_hash = {slot_hash(s): s for s in old_sessions}

        covered: set[str] = set()
        placed: set[Any] = set()
        # A pick whose type is unknown already says to open the timetable;
        # announcing its type as new as well would say it twice.
        unknown = False

        def place(session: dict[str, Any]) -> None:
            if session.get("sessionId") in placed:
                return
            placed.add(session.get("sessionId"))
            plan.weekly.append(_event(course, session))

        for pick in wanted.picks:
            exact = by_hash.get(pick)
            if exact is not None and type_of(exact) not in DATED_TYPES:
                covered.add(type_of(exact))
                plan.resolved += 1
                place(exact)
                continue

            old = old_by_hash.get(pick)
            if old is None:
                unknown = True
                plan.notes.append(
                    Note(
                        wanted.code,
                        f"pick:{pick}",
                        f"One of your {wanted.code} classes changed",
                        _RESUBSCRIBE,
                    )
                )
                continue

            kind = type_of(old)
            covered.add(kind)
            nxt = resolve_slot(
                old,
                [s for s in old_sessions if type_of(s) == kind],
                [s for s in sessions if type_of(s) == kind],
            )
            if nxt is None:
                plan.notes.append(
                    Note(
                        wanted.code,
                        f"pick:{pick}",
                        f"Your {wanted.code} {kind} changed",
                        f"It was {_when(old)}. " + _RESUBSCRIBE,
                        type=kind,
                    )
                )
                continue
            plan.resolved += 1
            plan.followed += 1
            place(nxt)

        dismissed = set(wanted.dismissed)
        for kind in sorted({type_of(s) for s in sessions}):
            if kind in DATED_TYPES or kind in covered or kind in dismissed:
                continue
            of_kind = [s for s in sessions if type_of(s) == kind]
            if len(of_kind) == 1:
                place(of_kind[0])
            elif not unknown:
                plan.notes.append(
                    Note(
                        wanted.code,
                        f"choose:{kind}",
                        f"{wanted.code} has a {kind} to choose",
                        "Open your timetable to pick a time, then subscribe again "
                        "with the new link.",
                        type=kind,
                    )
                )

        plan.dated.extend(
            _event(course, s) for s in sessions if type_of(s) in DATED_TYPES
        )

    return plan
