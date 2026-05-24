#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="timetable-calibrate",
        description="LLM-powered calibration for CELCAT timetable extraction",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    cal_parser = subparsers.add_parser("calibrate", help="Run full calibration on a PDF")
    cal_parser.add_argument("pdf_path", type=str, help="Path to the PDF file")
    cal_parser.add_argument("--course", "-c", required=True, help="Course code")
    cal_parser.add_argument("--session-id", help="Existing session ID to continue")

    ls_parser = subparsers.add_parser("list-sessions", help="List calibration sessions")
    ls_parser.add_argument("--course", "-c", help="Filter by course code")
    ls_parser.add_argument("--limit", "-l", type=int, default=20, help="Max results (default: 20)")

    gs_parser = subparsers.add_parser("get-session", help="Get session details")
    gs_parser.add_argument("session_id", type=str, help="Session ID")

    lc_parser = subparsers.add_parser("list-configs", help="List course configs")
    lc_parser.add_argument("--course", "-c", help="Filter by course code")
    lc_parser.add_argument("--status", "-s", choices=["draft", "active"], help="Filter by status")

    ac_parser = subparsers.add_parser("activate-config", help="Activate a draft config")
    ac_parser.add_argument("config_id", type=str, help="Configuration ID")

    args = parser.parse_args()

    if args.command == "calibrate":
        asyncio.run(_cmd_calibrate(args))
    elif args.command == "list-sessions":
        asyncio.run(_cmd_list_sessions(args))
    elif args.command == "get-session":
        asyncio.run(_cmd_get_session(args))
    elif args.command == "list-configs":
        _cmd_list_configs(args)
    elif args.command == "activate-config":
        _cmd_activate_config(args)


async def _cmd_calibrate(args: argparse.Namespace) -> None:
    pdf_path = Path(args.pdf_path)
    if not pdf_path.exists():
        print(f"Error: PDF not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    from timetable_extractor.calibration.providers.nemotron import NemotronProvider
    from timetable_extractor.calibration.orchestrator import CalibrationOrchestrator

    provider = NemotronProvider()
    if not provider.api_key:
        print("Error: NVIDIA_API_KEY environment variable not set", file=sys.stderr)
        sys.exit(1)

    orchestrator = CalibrationOrchestrator(provider=provider)

    print(f"Running calibration for course {args.course}...", flush=True)
    try:
        result = await orchestrator.calibrate(str(pdf_path), args.course, args.session_id)
    except Exception as e:
        print(f"Error during calibration: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"\nCalibration complete!")
    print(f"  Session ID: {result['session_id']}")
    print(f"  Config ID:  {result['config_id']}")
    print(f"  Confidence:  {result['confidence']:.2f}")
    print(f"  Entries:     {result['entries_count']}")

    report_path = Path(f"{args.course}_calibration_report.md")
    report_path.write_text(result["report"])
    print(f"\nReport saved to: {report_path}")


async def _cmd_list_sessions(args: argparse.Namespace) -> None:
    from timetable_extractor.calibration.orchestrator import CalibrationOrchestrator
    from timetable_extractor.calibration.providers.nemotron import NemotronProvider

    provider = NemotronProvider()
    orchestrator = CalibrationOrchestrator(provider=provider)

    try:
        sessions = await orchestrator.list_sessions(
            course_code=args.course,
            limit=args.limit,
        )
    except Exception as e:
        print(f"Error listing sessions: {e}", file=sys.stderr)
        sys.exit(1)

    if not sessions:
        print("No sessions found.")
        return

    print(f"{'Session ID':<28} {'Course':<10} {'Status':<14} {'Confidence':<12} {'Created'}")
    print("-" * 80)
    for s in sessions:
        sid = s.get("_id", "?")
        course = s.get("course_code", "?")
        status = s.get("status", "?")
        conf = s.get("confidence", 0.0) or 0.0
        created = str(s.get("created_at", "")).split(".")[0] if s.get("created_at") else "?"
        print(f"{sid:<28} {course:<10} {status:<14} {conf:<12.2f} {created}")


async def _cmd_get_session(args: argparse.Namespace) -> None:
    from timetable_extractor.calibration.orchestrator import CalibrationOrchestrator
    from timetable_extractor.calibration.providers.nemotron import NemotronProvider

    provider = NemotronProvider()
    orchestrator = CalibrationOrchestrator(provider=provider)

    try:
        session = await orchestrator.get_session(args.session_id)
    except Exception as e:
        print(f"Error retrieving session: {e}", file=sys.stderr)
        sys.exit(1)

    if session is None:
        print(f"Session not found: {args.session_id}", file=sys.stderr)
        sys.exit(1)

    print(f"Session ID:   {session.get('_id', '?')}")
    print(f"Course Code:  {session.get('course_code', '?')}")
    print(f"Status:       {session.get('status', '?')}")
    print(f"Confidence:   {session.get('confidence', 0.0):.2f}")
    print(f"Config ID:    {session.get('config_id', '?')}")
    print(f"Created At:   {session.get('created_at', '?')}")
    print()

    phases = session.get("phases", {})
    if phases:
        print("Phases:")
        for phase, info in phases.items():
            status = info.get("status", "?")
            print(f"  {phase}: {status}")
            if "error" in info:
                print(f"    Error: {info['error']}")
            if "confidence" in info:
                print(f"    Confidence: {info['confidence']:.2f}")
            if "config_id" in info:
                print(f"    Config ID: {info['config_id']}")


def _cmd_list_configs(args: argparse.Namespace) -> None:
    from timetable_extractor.config.loader import list_configs

    try:
        configs = list_configs(status=args.status, course_code=args.course)
    except Exception as e:
        print(f"Error listing configs: {e}", file=sys.stderr)
        sys.exit(1)

    if not configs:
        print("No configs found.")
        return

    print(f"{'Config ID':<28} {'Course':<10} {'Status':<12} {'Version':<8} {'Created'}")
    print("-" * 75)
    for c in configs:
        cid = str(c.get("_id", "?"))
        course = c.get("course_code", "?")
        status = c.get("status", "?")
        version = c.get("version", "?")
        created = str(c.get("created_at", "")).split(".")[0] if c.get("created_at") else "?"
        print(f"{cid:<28} {course:<10} {status:<12} {str(version):<8} {created}")


def _cmd_activate_config(args: argparse.Namespace) -> None:
    from timetable_extractor.config.loader import activate_config

    try:
        ok = activate_config(args.config_id)
    except Exception as e:
        print(f"Error activating config: {e}", file=sys.stderr)
        sys.exit(1)

    if not ok:
        print(f"Config not found: {args.config_id}", file=sys.stderr)
        sys.exit(1)

    print(f"Config {args.config_id} activated.")


if __name__ == "__main__":
    main()
