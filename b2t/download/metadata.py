"""Fetch Bilibili video metadata"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

import httpx

from b2t.download.bilibili_categories import (
    get_bilibili_parent_tid,
    get_bilibili_parent_tname,
    get_bilibili_tname,
)
from b2t.download.platform import PlatformMetadata

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VideoMetadata:
    """Bilibili video metadata"""

    bvid: str
    title: str
    author: str
    author_uid: int
    pubdate: str  # ISO date string (YYYY-MM-DD HH:MM:SS)
    pubdate_timestamp: int  # Unix timestamp
    description: str
    aid: int = 0
    tid: int = 0
    duration_seconds: int = 0

    @property
    def tname(self) -> str:
        """Resolve the video's partition name from the local taxonomy."""
        return get_bilibili_tname(self.tid)

    @property
    def parent_tid(self) -> int:
        """Resolve the video's parent partition ID from the local taxonomy."""
        return get_bilibili_parent_tid(self.tid)

    @property
    def parent_tname(self) -> str:
        """Resolve the video's parent partition name from the local taxonomy."""
        return get_bilibili_parent_tname(self.tid)

    @classmethod
    def from_platform_metadata(cls, pm: PlatformMetadata) -> VideoMetadata:
        """Create a VideoMetadata-compatible object from PlatformMetadata.

        Uses the platform-prefixed ID as bvid for backward compatibility
        with existing code that expects a BV-style identifier.
        """
        bvid = f"{pm.platform.value}_{pm.platform_id}"
        author_uid = 0
        try:
            author_uid = int(pm.author_uid)
        except (ValueError, TypeError):
            pass
        return cls(
            bvid=bvid,
            title=pm.title,
            author=pm.author,
            author_uid=author_uid,
            pubdate=pm.pubdate,
            pubdate_timestamp=pm.pubdate_timestamp,
            description=pm.description,
        )


async def get_video_metadata_async(bvid: str) -> VideoMetadata:
    """Asynchronously fetch video metadata

    Args:
        bvid: Bilibili video BV ID

    Returns:
        VideoMetadata: Video metadata

    Raises:
        ValueError: Invalid BV ID format
        httpx.HTTPError: API request failed
        RuntimeError: API returned an error
    """
    if not bvid or not bvid.startswith("BV"):
        raise ValueError(f"Invalid BV ID: {bvid}")

    url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Referer": "https://www.bilibili.com",
    }

    logger.debug("Fetching metadata for video %s...", bvid)

    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()

        data = response.json()

        if data.get("code") != 0:
            error_msg = data.get("message", "未知错误")
            raise RuntimeError(f"API returned error: {error_msg}")

        video_data = data.get("data")
        if not video_data:
            raise RuntimeError("API returned empty data")

        # Extract key information
        owner = video_data.get("owner", {})
        pubdate_timestamp = video_data.get("pubdate", 0)

        # Convert timestamp to readable format
        pubdate_readable = ""
        if pubdate_timestamp:
            pubdate_readable = datetime.fromtimestamp(pubdate_timestamp).strftime(
                "%Y-%m-%d %H:%M:%S"
            )

        metadata = VideoMetadata(
            bvid=video_data.get("bvid", bvid),
            title=video_data.get("title", ""),
            author=owner.get("name", ""),
            author_uid=owner.get("mid", 0),
            pubdate=pubdate_readable,
            pubdate_timestamp=pubdate_timestamp,
            description=video_data.get("desc", ""),
            aid=int(video_data.get("aid", 0) or 0),
            tid=int(video_data.get("tid", 0) or 0),
            duration_seconds=int(video_data.get("duration", 0) or 0),
        )

        logger.info(
            "Successfully fetched video metadata: %s (author: %s, publish date: %s)",
            metadata.title,
            metadata.author,
            metadata.pubdate,
        )

        return metadata


def get_video_metadata(bvid: str) -> VideoMetadata:
    """Synchronously fetch video metadata

    Args:
        bvid: Bilibili video BV ID

    Returns:
        VideoMetadata: Video metadata

    Raises:
        ValueError: Invalid BV ID format
        httpx.HTTPError: API request failed
        RuntimeError: API returned an error or event loop is already running
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # 当前线程没有运行中的事件循环，直接使用 asyncio.run()
        return asyncio.run(get_video_metadata_async(bvid))
    # 当前线程已有运行中的事件循环（如 ThreadPoolExecutor 中某些库隐式创建了循环），
    # 改用 new_event_loop + run_until_complete 绕过 asyncio.run() 的校验。
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(get_video_metadata_async(bvid))
    finally:
        loop.close()


__all__ = [
    "VideoMetadata",
    "get_video_metadata",
    "get_video_metadata_async",
]
