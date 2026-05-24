"""Nemotron LLM provider using NVIDIA NIM vision API for timetable extraction."""

from __future__ import annotations

import json
import logging
from base64 import b64encode
from typing import Any

import fitz  # PyMuPDF (no poppler dependency)
import httpx

from timetable_extractor.calibration.prompts import (
    CONFIG_SYSTEM_PROMPT,
    CONFIG_USER_PROMPT,
    EXTRACTION_SYSTEM_PROMPT,
    EXTRACTION_USER_PROMPT,
)
from timetable_extractor.config.db import NemotronSettings
from timetable_extractor.config.models import CourseConfig

logger = logging.getLogger(__name__)


class NemotronProvider:
    """LLM provider using NVIDIA Nemotron via the NIM API.

    Converts PDF pages to images, sends them to a vision-capable model,
    and returns structured timetable data and parser configurations.
    """

    name: str = "nemotron"

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        settings = NemotronSettings()
        self.api_key: str = settings.nvidia_api_key
        self.base_url: str = settings.nvidia_base_url
        self.model: str = settings.nvidia_model
        self.max_tokens: int = settings.nvidia_max_tokens
        self.temperature: float = settings.nvidia_temperature
        self._http_client = http_client

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=60.0)
        return self._http_client

    async def _call_api(self, messages: list[dict]) -> dict[str, Any]:
        client = await self._get_client()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        try:
            response = await client.post(self.base_url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"NVIDIA NIM API HTTP error {e.response.status_code}: {e.response.text}"
            ) from e
        except httpx.TimeoutException as e:
            raise RuntimeError("NVIDIA NIM API request timed out") from e
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"Failed to decode NVIDIA NIM API response: {e}"
            ) from e
        return data

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        """Parse JSON from LLM response, handling markdown fences and text wrappers."""
        raw = raw.strip()

        # Strategy 1: Strip markdown code fences (```json ... ``` or ``` ... ```)
        if "```" in raw:
            lines = raw.splitlines()
            cleaned: list[str] = []
            in_fence = False
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("```"):
                    in_fence = not in_fence
                    continue
                if not in_fence:
                    continue
                cleaned.append(line)
            if cleaned:
                candidate = "\n".join(cleaned).strip()
                if candidate.startswith("{"):
                    return json.loads(candidate)

        # Strategy 2: Find first { and last } anywhere in the text
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = raw[start : end + 1]
            return json.loads(candidate)

        # Strategy 3: Direct parse (may fail with a descriptive error)
        return json.loads(raw)

    async def extract_timetable(self, pdf_path: str) -> dict[str, Any]:
        """Phase 1: Extract course code + timetable entries from PDF images.

        Args:
            pdf_path: Path to the PDF file on disk.

        Returns:
            dict with keys: course_code, course_name, semester, entries, layout_notes
        """
        try:
            doc = fitz.open(pdf_path)
        except Exception as e:
            raise RuntimeError(f"Failed to open PDF: {e}") from e

        if doc.page_count == 0:
            raise RuntimeError(f"No pages found in PDF: {pdf_path}")

        max_pages = min(doc.page_count, 2)
        image_contents: list[str] = []
        for page_num in range(max_pages):
            page = doc[page_num]
            pix = page.get_pixmap(dpi=200)
            img_bytes = pix.tobytes("jpeg")
            b64 = b64encode(img_bytes).decode("utf-8")
            image_contents.append(f"data:image/jpeg;base64,{b64}")

        doc.close()

        content: list[dict[str, Any]] = [
            {"type": "text", "text": EXTRACTION_USER_PROMPT}
        ]
        for img_data in image_contents:
            content.append({"type": "image_url", "image_url": {"url": img_data}})

        messages = [
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ]

        data = await self._call_api(messages)
        raw_content = data["choices"][0]["message"]["content"]
        return self._parse_json(raw_content)

    async def generate_config(self, pdf_path: str, extraction: dict) -> dict[str, Any]:
        """Phase 2: Analyze layout and generate parser configuration.

        Args:
            pdf_path: Path to the PDF file on disk.
            extraction: The result from extract_timetable().

        Returns:
            dict with keys: page_regions, day_columns, time_slot_map,
                          text_patterns, anomalies, confidence, layout_signature
        """
        course_code = extraction.get("course_code", "UNKNOWN")
        extraction_json = json.dumps(extraction, indent=2)

        user_text = CONFIG_USER_PROMPT.format(
            course_code=course_code,
            extraction_json=extraction_json,
        )

        messages = [
            {"role": "system", "content": CONFIG_SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ]

        data = await self._call_api(messages)
        raw_content = data["choices"][0]["message"]["content"]
        parsed = self._parse_json(raw_content)

        config = CourseConfig(**parsed)
        return config.model_dump()
