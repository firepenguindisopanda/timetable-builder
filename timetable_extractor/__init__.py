"""
timetable_extractor - CELCAT Timetable PDF Extractor

A modular package for extracting structured class data from CELCAT-generated
timetable PDFs. Supports extraction, downloading, header evaluation, and
LLM-powered calibration for course-specific extraction configs.

Usage:
    from timetable_extractor import extract_timetable

    result = extract_timetable("timetable.pdf")
"""

from timetable_extractor.extract import extract_timetable
from timetable_extractor.download import download_timetables, filter_resources
from timetable_extractor.evaluate import evaluate_headers, scan_all_pdfs

# Conditionally expose calibration components
try:
    from timetable_extractor.calibration.orchestrator import CalibrationOrchestrator
    from timetable_extractor.calibration.providers.nemotron import NemotronProvider
    from timetable_extractor.calibration.config_generator import ConfigGenerator
    from timetable_extractor.calibration.report_generator import ReportGenerator
    __all__ = [
        "extract_timetable",
        "download_timetables",
        "filter_resources",
        "evaluate_headers",
        "scan_all_pdfs",
        "CalibrationOrchestrator",
        "NemotronProvider",
        "ConfigGenerator",
        "ReportGenerator",
    ]
except ImportError:
    __all__ = [
        "extract_timetable",
        "download_timetables",
        "filter_resources",
        "evaluate_headers",
        "scan_all_pdfs",
    ]

__version__ = "1.1.0"
