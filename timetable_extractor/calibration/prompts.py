"""
Prompt templates for two-phase LLM calibration.
"""

# Phase 1: Extract timetable data from CELCAT PDF
EXTRACTION_SYSTEM_PROMPT = """\
You are a timetable extraction expert. Analyze the attached PDF page images \
of a CELCAT university timetable. Return ONLY valid JSON with:

{
  "course_code": "string — the course/module code found in the PDF header",
  "course_name": "string — full course name",
  "semester": "string or null — semester/term if detectable",
  "entries": [
    {
      "day": "Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday",
      "start_time": "HH:MM",
      "end_time": "HH:MM",
      "room": "string — room code",
      "activity_type": "Lecture|Tutorial|Lab|Workshop|Exam|Other",
      "staff": "string or null — instructor name"
    }
  ],
  "layout_notes": "string — observations about the page layout structure"
}"""

EXTRACTION_USER_PROMPT = "Extract the timetable data from this CELCAT PDF."

# Phase 2: Generate config from layout analysis
CONFIG_SYSTEM_PROMPT = """\
Based on the extracted timetable and the PDF page layout, generate a \
configuration map for a deterministic CELCAT parser. Return ONLY valid JSON.

Respond with:
{
  "page_regions": {
    "header_top": float (0-1),
    "header_bottom": float,
    "table_top": float,
    "table_bottom": float,
    "footer_bottom": float
  },
  "day_columns": {
    "monday":  { "left": float, "right": float },
    ... all detected days
  },
  "time_slot_map": [
    { "label": "HH:MM", "top": float, "bottom": float }
  ],
  "text_patterns": {
    "module_code_regex": "string — regex pattern",
    "room_pattern": "string — regex",
    "activity_types": ["string"],
    "staff_pattern": "string — regex"
  },
  "anomalies": ["string — description of each anomaly found"],
  "confidence": float (0-1),
  "layout_signature": "string — identifier for this layout type"
}"""

CONFIG_USER_PROMPT = "Analyze the layout of this CELCAT PDF and generate a parser configuration."
