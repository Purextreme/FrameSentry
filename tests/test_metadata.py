from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from framesentry.metadata import _mp4_audio_stream_exists


class MetadataAudioTests(unittest.TestCase):
    def test_mp4_audio_stream_detects_soun_handler(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "with_audio.mp4"
            video.write_bytes(_box(b"ftyp", b"isom") + _box(b"moov", _track(b"vide") + _track(b"soun")))

            self.assertTrue(_mp4_audio_stream_exists(video))

    def test_mp4_audio_stream_returns_false_without_audio_handler(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "video_only.mp4"
            video.write_bytes(_box(b"ftyp", b"isom") + _box(b"moov", _track(b"vide")))

            self.assertFalse(_mp4_audio_stream_exists(video))


def _track(handler_type: bytes) -> bytes:
    return _box(b"trak", _box(b"mdia", _handler(handler_type)))


def _handler(handler_type: bytes) -> bytes:
    return _box(b"hdlr", b"\x00\x00\x00\x00" + b"\x00\x00\x00\x00" + handler_type + b"\x00" * 12)


def _box(box_type: bytes, payload: bytes) -> bytes:
    return (len(payload) + 8).to_bytes(4, "big") + box_type + payload


if __name__ == "__main__":
    unittest.main()
