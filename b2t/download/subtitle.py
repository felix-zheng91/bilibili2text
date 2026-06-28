"""Fetch Bilibili native subtitles using the ``bili`` CLI."""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BilibiliSubtitle:
    """Plain subtitle text returned by Bilibili."""

    text: str


def fetch_bilibili_subtitle(
    target: str, *, timeout_seconds: int = 60
) -> BilibiliSubtitle | None:
    """Return native Bilibili subtitle text when available.

    Missing subtitles, CLI failures, and malformed output are treated as cache misses so
    callers can fall back to ASR without failing the whole pipeline.
    """
    cleaned_target = target.strip()
    if not cleaned_target:
        return None

    cmd = ["bili", "video", cleaned_target, "--subtitle", "--json"]
    try:
        result = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError:
        logger.warning("bili CLI not found, falling back to ASR")
        return None
    except subprocess.TimeoutExpired:
        logger.warning("Fetching Bilibili subtitle timed out, falling back to ASR")
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Fetching Bilibili subtitle failed: %s", exc)
        return None

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        logger.info("Bilibili subtitle unavailable, falling back to ASR: %s", detail)
        return None

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse Bilibili subtitle JSON: %s", exc)
        return None

    subtitle = payload.get("subtitle")
    if not isinstance(subtitle, dict) or not subtitle.get("available"):
        logger.info("Bilibili subtitle is not available")
        return None

    text = subtitle.get("text")
    if not isinstance(text, str) or not text.strip():
        logger.info("Bilibili subtitle is empty")
        return None

    return BilibiliSubtitle(text=text.strip())
