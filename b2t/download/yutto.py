"""Default download implementation: yutto CLI subprocess.

使用 CLI subprocess 而非 yutto Python API，因为 yutto 库调用路径
硬编码了 fnval=4048（仅 DASH），对老视频会报"尚不支持 DASH 格式"。
CLI subprocess 的下载路径能处理更多视频格式。
"""

from b2t.download.yutto_cli import download_audio

__all__ = ["download_audio"]
