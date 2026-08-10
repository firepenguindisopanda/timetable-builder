"""
A cache-busting stamp for the static assets, derived from the assets.

Browsers are told to keep `/assets` for four hours and not to revalidate, which
is right for files that rarely change and wrong on the day they do. A deploy
that changes a script without changing the URL asking for it leaves a returning
student running new HTML against stale JavaScript.

That is not theoretical. It stranded saved timetables: the grouping rules moved,
the URL stayed `?v=3`, so a cached copy of the old rules computed option group
ids that no saved placement matched, and the calendar rendered nothing at all.
The code written to recover from exactly that lived in the same stale file, so
it never ran either.

Hand-typed version numbers failed because they are a step someone has to
remember at the moment they are thinking about something else. This is computed
from the file contents instead, so changing an asset changes every URL that
asks for one, and forgetting is not possible.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

ASSETS_DIR = Path(__file__).resolve().parent / "assets"

#: Only the files a template can reference by URL. The favicon and the audio
#: are not worth reading on every boot, and neither has ever needed busting.
VERSIONED_SUFFIXES = {".js", ".css"}

_stamp: str | None = None


def _compute() -> str:
    digest = hashlib.sha256()
    for path in sorted(ASSETS_DIR.rglob("*")):
        if path.is_file() and path.suffix in VERSIONED_SUFFIXES:
            # The name goes in too, so that renaming a file is a change even
            # when its contents are not.
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def asset_version() -> str:
    """
    A short hash of the versioned assets, computed once per process.

    Assets do not change under a running server, so this is read at first use
    and kept. A deployment starts a new process, which is exactly when it
    should be recomputed.
    """
    global _stamp
    if _stamp is None:
        _stamp = _compute() if ASSETS_DIR.is_dir() else "dev"
    return _stamp
