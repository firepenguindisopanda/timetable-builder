"""
Generates human-readable, structured reports from the LLM calibration process
for admin review and audit trails.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from timetable_extractor.config.models import CalibrationSession, CourseConfig


def _fmt(val: Any) -> str:
    """Format a value for markdown display."""
    if val is None:
        return "_None_"
    return str(val)


class ReportGenerator:
    """Generates human-readable calibration reports from LLM analysis."""

    @staticmethod
    def generate_pattern_report(
        course_code: str,
        extraction_result: dict[str, Any],
        llm_extraction: dict[str, Any],
        config: CourseConfig,
    ) -> str:
        """Build a markdown report summarising the LLM's layout analysis.

        Args:
            course_code: The course identifier.
            extraction_result: Raw output from Phase 1 extraction
                (entries, layout_notes, etc.).
            llm_extraction: Raw output from Phase 2 config analysis.
            config: The final generated CourseConfig.

        Returns:
            A formatted markdown string.
        """
        lines: list[str] = []
        now = datetime.now().isoformat(timespec="seconds")

        # ── Course Overview ──────────────────────────────────────────
        lines.append("# Pattern Analysis Report")
        lines.append("")
        lines.append(f"**Course Code:** `{course_code}`")
        lines.append(f"**Generated At:** {now}")
        lines.append("")

        # ── Layout Analysis ──────────────────────────────────────────
        lines.append("## Layout Analysis")
        lines.append("")
        layout_notes = (extraction_result.get("layout_notes") or
                        llm_extraction.get("layout_notes", ""))
        lines.append(layout_notes if layout_notes else "_No layout notes available._")
        lines.append("")

        # ── Detected Patterns ────────────────────────────────────────
        lines.append("## Detected Patterns")
        lines.append("")

        day_columns = config.day_columns.model_dump()
        present_days = {k: v for k, v in day_columns.items() if v is not None}
        lines.append(f"- **Day columns found:** {len(present_days)} "
                      f"({', '.join(d.capitalize() for d in present_days)})")
        for day, col in present_days.items():
            lines.append(f"  - `{day.capitalize()}`: left={col['left']:.4f}, "
                          f"right={col['right']:.4f}")

        time_slots = config.time_slot_map
        lines.append(f"- **Time slots identified:** {len(time_slots)}")
        for ts in time_slots[:6]:
            lines.append(f"  - `{ts.label}`: top={ts.top:.4f}, bottom={ts.bottom:.4f}")
        if len(time_slots) > 6:
            lines.append(f"  - _… and {len(time_slots) - 6} more_")

        tp = config.text_patterns
        lines.append(f"- **Module code regex:** `{_fmt(tp.module_code_regex)}`")
        lines.append(f"- **Room pattern:** `{_fmt(tp.room_pattern)}`")
        lines.append(f"- **Activity types:** {tp.activity_types or '[]'}")
        lines.append(f"- **Staff pattern:** `{_fmt(tp.staff_pattern)}`")
        lines.append("")

        # ── Extraction Summary ───────────────────────────────────────
        lines.append("## Extraction Summary")
        lines.append("")
        entries = extraction_result.get("entries", [])
        lines.append(f"- **Entries extracted:** {len(entries)}")
        confidence = config.confidence
        lines.append(f"- **Confidence score:** {confidence:.2f}")
        sig = config.layout_signature
        if sig:
            lines.append(f"- **Layout signature:** `{sig}`")
        lines.append("")

        # ── Generated Configuration ──────────────────────────────────
        lines.append("## Generated Configuration")
        lines.append("")
        lines.append("### Page Regions")
        lines.append("")
        lines.append("```json")
        lines.append(config.page_regions.model_dump_json(indent=2))
        lines.append("```")
        lines.append("")

        lines.append("### Day Column X-Positions")
        lines.append("")
        lines.append("```json")
        lines.append(config.day_columns.model_dump_json(indent=2, exclude_none=True))
        lines.append("```")
        lines.append("")

        lines.append("### Time Slot Counts")
        lines.append("")
        lines.append(f"- Total time slots in map: **{len(time_slots)}**")
        if time_slots:
            first = time_slots[0]
            last = time_slots[-1]
            lines.append(f"- Range: `{first.label}` to `{last.label}`")
        lines.append("")

        lines.append("### Text Patterns")
        lines.append("")
        lines.append("```json")
        lines.append(tp.model_dump_json(indent=2))
        lines.append("```")
        lines.append("")

        # ── Recommendations ──────────────────────────────────────────
        lines.append("## Recommendations")
        lines.append("")
        recs: list[str] = []

        if confidence < 0.5:
            recs.append(
                "- ⚠️ **Low confidence** — review the generated config "
                "carefully against the source PDF before activating."
            )
        elif confidence < 0.8:
            recs.append(
                "- ℹ️ **Moderate confidence** — spot-check against a "
                "handful of entries before activating."
            )
        else:
            recs.append("- ✅ **High confidence** — config is ready for staging.")

        if not present_days:
            recs.append(
                "- ⚠️ **No day columns** were detected — verify the PDF "
                "contains a recognisable timetable layout."
            )

        if not time_slots:
            recs.append(
                "- ⚠️ **No time slots** were mapped — extraction will "
                "not identify session times."
            )

        anomalies = llm_extraction.get("anomalies", [])
        if anomalies:
            recs.append("- **LLM-reported anomalies:**")
            for a in anomalies:
                recs.append(f"  - {_fmt(a)}")

        recs.append(
            "- Enable the config on a **single course first** and verify "
            "extraction output before rolling out."
        )

        lines.extend(recs)
        lines.append("")

        return "\n".join(lines)

    @staticmethod
    def generate_comparison_report(
        course_code: str,
        config_a: CourseConfig,
        config_b: CourseConfig,
        label_a: str = "LLM Config",
        label_b: str = "Previous Config",
    ) -> str:
        """Compare two CourseConfigs side by side as markdown.

        Args:
            course_code: The course identifier.
            config_a: The first config to compare.
            config_b: The second config to compare.
            label_a: Display label for config_a (default "LLM Config").
            label_b: Display label for config_b (default "Previous Config").

        Returns:
            A formatted markdown string showing differences.
        """
        lines: list[str] = []
        lines.append(f"# Config Comparison — `{course_code}`")
        lines.append("")
        lines.append(f"- **{label_a}** confidence: {config_a.confidence:.2f}")
        lines.append(f"- **{label_b}** confidence: {config_b.confidence:.2f}")
        lines.append("")

        # ── Page Regions ─────────────────────────────────────────────
        lines.append("## Page Regions")
        lines.append("")
        lines.append(f"| Property | {label_a} | {label_b} | Δ |")
        lines.append("|---|---|---|---|")
        pr_a = config_a.page_regions
        pr_b = config_b.page_regions
        for attr in ("header_top", "header_bottom", "table_top",
                      "table_bottom", "footer_bottom"):
            va = getattr(pr_a, attr, None)
            vb = getattr(pr_b, attr, None)
            delta = f"{va - vb:+.4f}" if va is not None and vb is not None else "—"
            lines.append(f"| `{attr}` | {va} | {vb} | {delta} |")
        lines.append("")

        # ── Day Columns ──────────────────────────────────────────────
        lines.append("## Day Columns")
        lines.append("")
        dc_a = config_a.day_columns.model_dump()
        dc_b = config_b.day_columns.model_dump()
        all_days = sorted(set(dc_a) | set(dc_b))
        lines.append(f"| Day | {label_a} | {label_b} | Changed |")
        lines.append("|---|---|---|---|")
        for day in all_days:
            ca = dc_a.get(day)
            cb = dc_b.get(day)
            if ca and cb:
                changed = ca != cb
                lines.append(
                    f"| {day.capitalize()} | "
                    f"L={ca['left']:.4f} R={ca['right']:.4f} | "
                    f"L={cb['left']:.4f} R={cb['right']:.4f} | "
                    f"{'⚠️ Yes' if changed else '—'} |"
                )
            elif ca and not cb:
                lines.append(
                    f"| {day.capitalize()} | "
                    f"L={ca['left']:.4f} R={ca['right']:.4f} | _absent_ | "
                    f"⚠️ Removed |"
                )
            elif not ca and cb:
                lines.append(
                    f"| {day.capitalize()} | _absent_ | "
                    f"L={cb['left']:.4f} R={cb['right']:.4f} | "
                    f"➕ Added |"
                )
            else:
                lines.append(f"| {day.capitalize()} | _absent_ | _absent_ | — |")
        lines.append("")

        # ── Time Slot Counts ─────────────────────────────────────────
        lines.append("## Time Slot Counts")
        lines.append("")
        n_a = len(config_a.time_slot_map)
        n_b = len(config_b.time_slot_map)
        lines.append(f"- **{label_a}**: {n_a} slots")
        lines.append(f"- **{label_b}**: {n_b} slots")
        if n_a != n_b:
            lines.append(f"- ⚠️ **Difference**: {abs(n_a - n_b)} slots "
                          f"{'added' if n_a > n_b else 'removed'}")
        lines.append("")

        # ── Text Patterns ────────────────────────────────────────────
        lines.append("## Text Patterns")
        lines.append("")
        lines.append(f"| Pattern | {label_a} | {label_b} |")
        lines.append("|---|---|---|")
        tp_a = config_a.text_patterns
        tp_b = config_b.text_patterns
        for attr in ("module_code_regex", "room_pattern", "staff_pattern",
                      "activity_types"):
            va = _fmt(getattr(tp_a, attr, None))
            vb = _fmt(getattr(tp_b, attr, None))
            lines.append(f"| `{attr}` | `{va}` | `{vb}` |")
        lines.append("")

        # ── Summary ──────────────────────────────────────────────────
        lines.append("## Summary")
        lines.append("")
        changed_items: list[str] = []

        pr_keys = ("header_top", "header_bottom", "table_top",
                    "table_bottom", "footer_bottom")
        if any(getattr(pr_a, k) != getattr(pr_b, k) for k in pr_keys):
            changed_items.append("page regions")

        if dc_a != dc_b:
            changed_items.append("day columns")

        if n_a != n_b:
            changed_items.append("time slot count")

        if any(
            getattr(tp_a, attr) != getattr(tp_b, attr)
            for attr in ("module_code_regex", "room_pattern",
                          "staff_pattern", "activity_types")
        ):
            changed_items.append("text patterns")

        if changed_items:
            lines.append("⚠️ **Changes detected in:** " + ", ".join(changed_items))
        else:
            lines.append("✅ **No differences — configs are identical.**")
        lines.append("")

        return "\n".join(lines)

    @staticmethod
    def generate_session_summary(session: CalibrationSession) -> str:
        """Produce a markdown summary of an entire calibration session.

        Args:
            session: A populated CalibrationSession instance.

        Returns:
            A formatted markdown string.
        """
        lines: list[str] = []
        lines.append("# Calibration Session Summary")
        lines.append("")
        lines.append(f"**Session ID:** `{session._id or 'N/A'}`")
        lines.append(f"**Course Code:** `{session.course_code}`")
        lines.append(f"**PDF:** `{session.pdf_filename}`")
        lines.append(f"**Provider:** {session.llm_provider}")
        lines.append(f"**Model:** {session.llm_model or '_Not specified_'}")
        lines.append(f"**Prompt Version:** `{session.prompt_template_version}`")
        lines.append("")

        # ── Timelines ────────────────────────────────────────────────
        lines.append("## Timeline")
        lines.append("")
        lines.append(f"- **Phase 1 (Extraction):** "
                      f"{'✅ Complete' if session.phase1_response else '⏳ Pending'}")
        lines.append(f"- **Phase 2 (Config):** "
                      f"{'✅ Complete' if session.phase2_response else '⏳ Pending'}")
        lines.append("")

        # ── Results ──────────────────────────────────────────────────
        lines.append("## Results")
        lines.append("")
        config_generated = session.generated_config_id is not None
        if config_generated:
            lines.append(f"- **Config generated:** ✅  `{session.generated_config_id}`")
        else:
            lines.append("- **Config generated:** ❌ No")

        acc = session.accuracy_score
        if acc is not None:
            lines.append(f"- **Accuracy score:** {acc:.2f}")
        lines.append("")

        # ── Confidence ──────────────────────────────────────────────
        lines.append("## Confidence & Status")
        lines.append("")
        phase2 = session.phase2_response
        confidence: float = 0.0
        if isinstance(phase2, dict):
            confidence = phase2.get("confidence", 0.0) or 0.0
        elif isinstance(phase2, str):
            confidence = 0.0

        if confidence >= 0.8:
            bar = "████████░░"
            level = "High"
        elif confidence >= 0.5:
            bar = "████▒▒▒░░░"
            level = "Moderate"
        else:
            bar = "██▒▒▒▒▒▒░░"
            level = "Low"

        lines.append(f"- **Confidence:** {level} ({confidence:.2f})")
        lines.append(f"  `{bar}`")
        lines.append("")

        # ── Admin Feedback ───────────────────────────────────────────
        feedback = session.admin_feedback
        if feedback:
            lines.append("## Admin Feedback")
            lines.append("")
            lines.append(feedback)
            lines.append("")

        # ── Reports & Anomalies ──────────────────────────────────────
        report = session.pattern_report
        if report:
            lines.append("## Pattern Report Data")
            lines.append("")
            lines.append("```json")
            lines.append(str(report))
            lines.append("```")
            lines.append("")

        anomalies: list[str] | None = None
        if isinstance(phase2, dict):
            anomalies = phase2.get("anomalies")
        if anomalies:
            lines.append("## Anomalies")
            lines.append("")
            for a in anomalies:
                lines.append(f"- {a}")
            lines.append("")

        lines.append("---")
        lines.append("")
        now = datetime.now().isoformat(timespec="seconds")
        lines.append(f"_Report generated at {now}_")
        lines.append("")

        return "\n".join(lines)
