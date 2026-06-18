from __future__ import annotations


def frame_to_timecode(frame_index: int, fps: float) -> str:
    if fps <= 0:
        return "00:00:00:00"

    timecode_fps = max(1, round(fps))
    total_seconds = int(frame_index // fps)
    frame_number = int(round(frame_index - total_seconds * fps))

    if frame_number >= timecode_fps:
        total_seconds += 1
        frame_number = 0

    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frame_number:02d}"
