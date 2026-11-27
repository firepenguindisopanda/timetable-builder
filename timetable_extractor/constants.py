"""
Constants used throughout the timetable extraction package.
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass

# Day names are rendered rotated/reversed in CELCAT PDFs
REVERSED_DAYS: dict[str, str] = {
    "yadnoM": "Monday",
    "noM": "Monday",  # abbreviated (reversed "Mon")
    # Two letters, as the "Inspection Copy" template prints it. PHPP 0301 arrived
    # in that template on 29 Sep 2026; unmatched, its Monday row went unbuilt.
    "oM": "Monday",
    "yadseuT": "Tuesday",
    "euT": "Tuesday",  # abbreviated (reversed "Tue")
    "yadsendeW": "Wednesday",  # full ("Wednesday" reversed - note the capital W)
    # "Wed" reversed. Its absence was silent and expensive: with no Wednesday
    # band, y_to_day fell back to the nearest band above and filed that day's
    # classes under Tuesday, in roughly one PDF in five.
    "deW": "Wednesday",
    "eW": "Wednesday",  # abbreviated (as seen on page)
    "yadsruhT": "Thursday",
    "uhT": "Thursday",  # abbreviated
    "yadirF": "Friday",
    "irF": "Friday",  # abbreviated (reversed "Fri")
    "yadrutaS": "Saturday",
    "taS": "Saturday",  # abbreviated
    "yadnuS": "Sunday",
    "nuS": "Sunday",  # abbreviated
}

# Time header x-positions are consistent across CELCAT PDFs.
# We build this dynamically from the PDF, but this is the expected pattern.
TIME_HEADER_Y_RANGE: tuple[int, int] = (90, 115)  # y band where time headers appear
DAY_LABEL_X_MAX: int = 60  # day labels always appear left of this x

# For evaluate_headers.py
TIME_HEADER_Y_MIN: int = 85
TIME_HEADER_Y_MAX_EVAL: int = 120

EXPECTED_TIMES: list[str] = [
    "08:00AM",
    "09:00AM",
    "10:00AM",
    "11:00AM",
    "12:00PM",
    "01:00PM",
    "02:00PM",
    "03:00PM",
    "04:00PM",
    "05:00PM",
    "06:00PM",
    "07:00PM",
    "08:00PM",
    "09:00PM",
]

# For download.py
BASE_URL: str = "https://mysta.uwi.edu/timetable/"
FINDER_XML: str = BASE_URL + "finder.xml"
DELAY_SEC: float = 1.5  # polite delay between requests


@dataclass(frozen=True)
class Source:
    """
    One CELCAT web publication: an address with its own finder.xml.

    On 26 Nov 2026 UWI published the semester 2 inspection copy at a second
    address beside the live semester 1 timetable. The two share 595 PDF names
    with different contents, so each source keeps its own folder, registry
    and withdrawn folder. SEMESTERS-SPEC.md section 5.
    """

    #: Where its finder.xml, finder.html and PDFs are served from.
    base_url: str
    #: Course PDFs; staff and room PDFs go in its `staff/` and `rooms/`.
    pdf_dir: str
    #: The finder.xml `database.cli load` reads. finder.html is kept beside it.
    registry: str
    #: Where PDFs UWI withdrew are moved to; `sync pull` never deletes.
    withdrawn_dir: str

    @property
    def finder_xml(self) -> str:
        return self.base_url + "finder.xml"

    @property
    def finder_html(self) -> str:
        return self.base_url + "finder.html"

    @property
    def link_prefix(self) -> str:
        """
        The path from the root address to this source's files.

        Stored in front of a PDF's name in `pdf_files.pdf_link` and
        `resources.pdf_link`, which are unique on that column. Empty for the
        root source, so none of its rows changes; for the inspection copy,
        "Inspection Copy/Sem2INSPECTIONCOPY/", so its m1249.pdf is a row of
        its own instead of overwriting semester 1's.
        """
        if not self.base_url.startswith(BASE_URL):
            raise ValueError(f"source outside {BASE_URL}: {self.base_url}")
        return urllib.parse.unquote(self.base_url[len(BASE_URL):])


#: The source a command reads when none is named. Its paths are the ones the
#: corpus, registry and runbook used before there was more than one source.
DEFAULT_SOURCE: str = "root"

#: Every CELCAT publication the warehouse follows. Adding or retiring one is a
#: code change and a runbook line: UWI chose the inspection copy's address for
#: this term, and next year's will differ.
SOURCES: dict[str, Source] = {
    "root": Source(
        base_url=BASE_URL,
        pdf_dir="downloaded_pdfs",
        registry="finder.xml",
        withdrawn_dir="withdrawn_pdfs",
    ),
    "s2-inspection": Source(
        base_url=BASE_URL + "Inspection%20Copy/Sem2INSPECTIONCOPY/",
        pdf_dir="sources/s2-inspection/pdfs",
        registry="sources/s2-inspection/finder.xml",
        withdrawn_dir="sources/s2-inspection/withdrawn",
    ),
}

# For blocks.py
MAX_BLOCK_HEIGHT: int = 130

# Fallback proximity window used only when a page has no grid rules. Blocks
# start at most ~7pt above their day label, so this stays small on purpose:
# a large window lets a block low in a tall row reach into the next day.
Y_TOLERANCE: int = 10

# A grid rule spans the whole timetable; anything narrower is cell decoration.
RULE_MIN_WIDTH_RATIO: float = 0.4

# A block's highlight bar can sit a hair above its row's rule.
ROW_TOP_TOLERANCE: float = 3.0

# Highlight bars are a uniform 8.8pt tall. Stacked bars belonging to one class
# block sit flush against each other (measured gap 0.2pt across the corpus);
# the smallest gap between two *different* blocks is 20pt. Anything in between
# is unobserved, so 5pt splits the two populations with a wide margin.
MAX_HEADER_BAR_GAP: float = 5.0

# For text_parser.py
# Within a block, wrapped continuation lines are 9-11pt apart while a new
# logical group (the header, "Course:", or a free-text note) starts 12-13pt
# below the previous line. Splitting at 12 separates field values from notes.
PARAGRAPH_GAP: float = 12.0

# Activity types CELCAT emits, as the comma-delimited prefix of a block's first
# line ("Lecture, Wks W1-W12 [=12]"). Matching is done on the de-spaced,
# case-folded form so that words split across narrow lines still resolve
# ("Postgradua te" -> "Postgraduate").
ACTIVITY_TYPES: tuple[str, ...] = (
    "Lecture",
    "Lecture Relocated",
    "Lecture & Tutorial",
    "Tutorial",
    "Tutorial (make-up/relocated)",
    "Lab",
    "Practical",
    "Postgraduate",
    "Seminar",
    "Workshop",
    "Field Trip",
    "Project Work",
    "Meeting",
    "Examination",
    "Help Desk",
    "Special Booking",
    "Video Presentation / Screening",
    "Chemistry Review Centre",
    "CLL Certificate Language Courses",
    "Reserved",
)
