"""Nemotron LLM provider using NVIDIA NIM vision API for timetable extraction."""

from __future__ import annotations

import io
import json
import logging
from base64 import b64encode
from typing import Any

import httpx
from pdf2image import convert_from_path

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
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            raw = "\n".join(lines).strip()
        return json.loads(raw)

    async def extract_timetable(self, pdf_path: str) -> dict[str, Any]:
        """Phase 1: Extract course code + timetable entries from PDF images.

        Args:
            pdf_path: Path to the PDF file on disk.

        Returns:
            dict with keys: course_code, course_name, semester, entries, layout_notes
        """
        try:
            images = convert_from_path(pdf_path, first_page=1, last_page=2, dpi=200)
        except Exception as e:
            raise RuntimeError(f"Failed to convert PDF to images: {e}") from e

        if not images:
            raise RuntimeError(f"No pages found in PDF: {pdf_path}")

        image_contents: list[str] = []
        for img in images:
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG")
            b64 = b64encode(buffer.getvalue()).decode("utf-8")
            image_contents.append(f"data:image/jpeg;base64,{b64}")

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
