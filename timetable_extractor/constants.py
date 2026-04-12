"""
Constants used throughout the timetable extraction package.
"""

# Day names are rendered rotated/reversed in CELCAT PDFs
REVERSED_DAYS: dict[str, str] = {
    "yadnoM": "Monday",
    "yadseuT": "Tuesday",
    "yadsendew": "Wednesday",  # full
    "eW": "Wednesday",  # abbreviated (as seen on page)
    "yadsruhT": "Thursday",
    "uhT": "Thursday",  # abbreviated
    "yadirF": "Friday",
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

# For blocks.py
MAX_BLOCK_HEIGHT: int = 130
Y_TOLERANCE: int = 50
