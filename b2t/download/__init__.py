"""Download module."""

from b2t.download.platform import (
    Platform,
    PlatformDownloader,
    PlatformMetadata,
    sanitize_filename_component,
)
from b2t.download.url_detect import detect_platform, extract_platform_id
from b2t.download.xiaoyuzhou import XiaoyuzhouDownloader
from b2t.download.ximalaya import XimalayaDownloader

# `b2t.download.yutto` is the default download implementation. On this fork it
# delegates to the yutto CLI subprocess (`yutto_cli`) instead of the yutto
# Python API (`yutto_api`), which is pinned against an older yutto release and
# cannot handle videos that only offer non-DASH formats.
from b2t.download.yutto import download_audio

__all__ = [
    "Platform",
    "PlatformDownloader",
    "PlatformMetadata",
    "XiaoyuzhouDownloader",
    "XimalayaDownloader",
    "detect_platform",
    "download_audio",
    "extract_platform_id",
    "sanitize_filename_component",
]
