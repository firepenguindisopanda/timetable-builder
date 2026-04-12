"""
timetable_extractor - CELCAT Timetable PDF Extractor

A modular package for extracting structured class data from CELCAT-generated
timetable PDFs. Supports extraction, downloading, and header evaluation.

Usage:
    from timetable_extractor import extract_timetable

    result = extract_timetable("timetable.pdf")
"""

from timetable_extractor.extract import extract_timetable
from timetable_extractor.download import download_timetables, filter_resources
from timetable_extractor.evaluate import evaluate_headers, scan_all_pdfs

__all__ = [
    "extract_timetable",
    "download_timetables",
    "filter_resources",
    "evaluate_headers",
    "scan_all_pdfs",
]

__version__ = "1.0.0"
