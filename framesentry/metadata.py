from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


COMMON_LANDSCAPE = {(1920, 1080), (3840, 2160), (2560, 1440), (1280, 720)}
COMMON_PORTRAIT = {(1080, 1920), (2160, 3840)}
COMMON_NON_INTEGER_FPS = (29.97, 59.94)
UNCOMMON_AD_FPS = (23.976, 24.0)
MP4_CONTAINER_BOXES = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"edts", b"udta", b"meta"}


@dataclass(frozen=True)
class VideoMetadata:
    width: int | None
    height: int | None
    fps: float
    duration: float | None
    codec: str | None
    frame_count: int | None
    audio_stream_exists: bool

    def to_report(self, path: Path) -> dict:
        return {
            "path": str(path),
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "duration": self.duration,
            "codec": self.codec,
            "frame_count": self.frame_count,
            "audio_stream_exists": self.audio_stream_exists,
        }


def read_metadata(path: Path) -> VideoMetadata:
    try:
        return _read_metadata_ffprobe(path)
    except (FileNotFoundError, subprocess.CalledProcessError, json.JSONDecodeError, KeyError, ValueError):
        return _read_metadata_opencv(path)


def _read_metadata_ffprobe(path: Path) -> VideoMetadata:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    payload = json.loads(result.stdout)
    streams = payload.get("streams", [])
    video_stream = next(stream for stream in streams if stream.get("codec_type") == "video")
    audio_stream_exists = any(stream.get("codec_type") == "audio" for stream in streams)

    duration = _as_float(video_stream.get("duration")) or _as_float(payload.get("format", {}).get("duration"))
    frame_count = _as_int(video_stream.get("nb_frames"))
    fps = _parse_rate(video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate"))

    return VideoMetadata(
        width=_as_int(video_stream.get("width")),
        height=_as_int(video_stream.get("height")),
        fps=fps,
        duration=duration,
        codec=video_stream.get("codec_name"),
        frame_count=frame_count,
        audio_stream_exists=audio_stream_exists,
    )


def _read_metadata_opencv(path: Path) -> VideoMetadata:
    try:
        import cv2
    except ModuleNotFoundError as exc:
        raise RuntimeError("ffprobe failed and OpenCV is not installed. Install FFmpeg or run `pip install -r requirements.txt`.") from exc

    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open video: {path}")
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = frame_count / fps if fps else None
    metadata = VideoMetadata(
        width=int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0),
        height=int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0),
        fps=fps,
        duration=duration,
        codec=None,
        frame_count=frame_count or None,
        audio_stream_exists=_mp4_audio_stream_exists(path),
    )
    capture.release()
    return metadata


def _mp4_audio_stream_exists(path: Path) -> bool:
    if path.suffix.lower() not in {".mp4", ".m4v", ".mov"}:
        return False
    try:
        with path.open("rb") as video_file:
            return _mp4_boxes_include_audio_handler(video_file, path.stat().st_size)
    except OSError:
        return False


def _mp4_boxes_include_audio_handler(video_file, end_offset: int) -> bool:
    position = video_file.tell()
    while position + 8 <= end_offset:
        video_file.seek(position)
        header = video_file.read(8)
        if len(header) < 8:
            return False

        size = int.from_bytes(header[:4], "big")
        box_type = header[4:8]
        header_size = 8
        if size == 1:
            extended_size = video_file.read(8)
            if len(extended_size) < 8:
                return False
            size = int.from_bytes(extended_size, "big")
            header_size = 16
        elif size == 0:
            size = end_offset - position

        box_end = position + size
        content_start = position + header_size
        if size < header_size or box_end > end_offset:
            return False

        if box_type == b"hdlr":
            video_file.seek(content_start)
            handler_header = video_file.read(12)
            if len(handler_header) >= 12 and handler_header[8:12] == b"soun":
                return True

        if box_type in MP4_CONTAINER_BOXES:
            child_start = content_start + (4 if box_type == b"meta" else 0)
            video_file.seek(child_start)
            if _mp4_boxes_include_audio_handler(video_file, box_end):
                return True

        position = box_end
    return False


def inspect_metadata(metadata: VideoMetadata, fps_normal: set[float]) -> list[dict]:
    events: list[dict] = []
    if metadata.width and metadata.height:
        resolution = (metadata.width, metadata.height)
        if resolution not in COMMON_LANDSCAPE and resolution not in COMMON_PORTRAIT:
            events.append(
                {
                    "type": "metadata_warning",
                    "severity": "warning",
                    "message": f"分辨率 {metadata.width}x{metadata.height} 非常规，建议检查导出设置。",
                }
            )

    fps = metadata.fps
    if fps:
        if _matches_any(fps, fps_normal):
            pass
        elif _matches_any(fps, COMMON_NON_INTEGER_FPS):
            events.append(
                {
                    "type": "metadata_warning",
                    "severity": "info",
                    "message": f"帧率 {fps:.3f} 是常见非整数帧率，建议确认交付规格。",
                }
            )
        elif _matches_any(fps, UNCOMMON_AD_FPS):
            events.append(
                {
                    "type": "metadata_warning",
                    "severity": "info",
                    "message": f"帧率 {fps:.3f} 属于非常规广告交付帧率，建议人工复核。",
                }
            )
        else:
            events.append(
                {
                    "type": "metadata_warning",
                    "severity": "warning",
                    "message": f"帧率 {fps:.3f} 不在常见交付帧率范围内，建议检查导出设置。",
                }
            )

    if metadata.audio_stream_exists is False:
        events.append(
            {
                "type": "metadata_warning",
                "severity": "info",
                "message": "未检测到音频轨，如交付物应包含声音，请人工复核。",
            }
        )
    return events


def _parse_rate(raw: str | None) -> float:
    if not raw or raw == "0/0":
        return 0.0
    if "/" in raw:
        numerator, denominator = raw.split("/", 1)
        denominator_value = float(denominator)
        return float(numerator) / denominator_value if denominator_value else 0.0
    return float(raw)


def _as_float(value: object) -> float | None:
    if value in (None, "N/A"):
        return None
    return float(value)


def _as_int(value: object) -> int | None:
    if value in (None, "N/A"):
        return None
    return int(float(value))


def _matches_any(value: float, candidates: set[float] | tuple[float, ...], tolerance: float = 0.02) -> bool:
    return any(abs(value - candidate) <= tolerance for candidate in candidates)
