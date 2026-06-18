from __future__ import annotations

from pathlib import Path


def save_event_screenshots(video_path: Path, events: list[dict], screenshot_dir: Path) -> None:
    try:
        import cv2
    except ModuleNotFoundError as exc:
        raise RuntimeError("OpenCV is required to save screenshots. Install dependencies with `pip install -r requirements.txt`.") from exc

    screenshot_dir.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open video for screenshots: {video_path}")

    for event in events:
        if "start_frame" not in event:
            continue
        start = int(event["start_frame"])
        end = int(event.get("end_frame", start))
        targets = {
            "before": max(0, start - 1),
            "current": start,
            "after": end + 1,
        }
        saved: dict[str, str] = {}
        for label, frame_index in targets.items():
            output_path = screenshot_dir / f"{event['type']}_{start:06d}_{label}.jpg"
            if _save_frame(capture, frame_index, output_path):
                saved[label] = str(Path("screenshots") / output_path.name).replace("\\", "/")
        if saved:
            event["screenshots"] = saved

    capture.release()


def _save_frame(capture, frame_index: int, output_path: Path) -> bool:
    import cv2

    capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
    ok, frame = capture.read()
    if not ok:
        return False
    encoded_ok, encoded = cv2.imencode(".jpg", frame)
    if not encoded_ok:
        return False
    encoded.tofile(str(output_path))
    return output_path.exists() and output_path.stat().st_size > 0
