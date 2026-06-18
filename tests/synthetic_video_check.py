from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "synthetic_checks"
FPS = 25
SIZE = (160, 90)


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    cases = {
        "black_blank": (make_black_blank_video, {"black_frame", "blank_frame"}),
        "duplicate": (make_duplicate_video, {"duplicate_frame"}),
        "single_outlier": (make_single_outlier_video, {"transient_outlier"}),
        "double_outlier": (make_double_outlier_video, {"transient_outlier"}),
        "local_fast_motion": (make_local_fast_motion_video, set()),
        "rapid_cut": (make_rapid_cut_video, {"rapid_change_review"}),
    }

    failures: list[str] = []
    for name, (factory, expected_types) in cases.items():
        video_path = OUTPUT / f"{name}.mp4"
        report_dir = OUTPUT / f"{name}_report"
        factory(video_path)
        run_scan(video_path, report_dir)
        report = json.loads((report_dir / "report.json").read_text(encoding="utf-8"))
        event_types = {event["type"] for event in report["events"]}
        high_conf_transients = [
            event
            for event in report["events"]
            if event["type"] == "transient_outlier" and event.get("confidence", 0) >= 0.7
        ]
        missing = expected_types - event_types
        print(f"{name}: events={sorted(event_types)} expected={sorted(expected_types)}")
        if missing:
            failures.append(f"{name} missing {sorted(missing)}")
        if name == "local_fast_motion" and high_conf_transients:
            failures.append(f"{name} has high confidence transient false positive")

    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    return 0


def run_scan(video_path: Path, report_dir: Path) -> None:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "framesentry",
            "scan",
            str(video_path),
            "--output",
            str(report_dir),
            "--save-screenshots",
            "--json",
            "--html",
        ],
        cwd=ROOT,
        check=True,
    )


def make_black_blank_video(path: Path) -> None:
    frames = []
    frames.extend(motion_frames(8, start=0))
    frames.extend(solid_frames((0, 0, 0), 3))
    frames.extend(motion_frames(8, start=8))
    frames.extend(solid_frames((128, 128, 128), 3))
    frames.extend(motion_frames(8, start=16))
    write_video(path, frames)


def make_duplicate_video(path: Path) -> None:
    frames = motion_frames(18, start=0)
    frames[10] = frames[9].copy()
    write_video(path, frames)


def make_single_outlier_video(path: Path) -> None:
    frames = []
    frames.extend(textured_frames((35, 90, 170), 10))
    frames.extend(textured_frames((210, 40, 40), 1))
    frames.extend(textured_frames((40, 160, 85), 10))
    write_video(path, frames)


def make_double_outlier_video(path: Path) -> None:
    frames = []
    frames.extend(textured_frames((35, 90, 170), 10))
    frames.extend(textured_frames((210, 40, 40), 2))
    frames.extend(textured_frames((40, 160, 85), 10))
    write_video(path, frames)


def make_local_fast_motion_video(path: Path) -> None:
    frames = []
    for index in range(24):
        frame = np.full((SIZE[1], SIZE[0], 3), (42, 88, 140), dtype=np.uint8)
        x = 8 + (index * 17) % 120
        cv2.rectangle(frame, (x, 24), (x + 34, 66), (245, 245, 245), -1)
        cv2.line(frame, (0, 12), (SIZE[0] - 1, 12), (45, 150, 90), 2)
        frames.append(frame)
    write_video(path, frames)


def make_rapid_cut_video(path: Path) -> None:
    frames = []
    colors = [(30, 80, 170), (170, 50, 40), (40, 160, 80), (180, 160, 30), (80, 40, 170)]
    for color in colors * 2:
        frames.extend(textured_frames(color, 1))
    write_video(path, frames)


def solid_frames(color: tuple[int, int, int], count: int) -> list[np.ndarray]:
    return [np.full((SIZE[1], SIZE[0], 3), color, dtype=np.uint8) for _ in range(count)]


def textured_frames(color: tuple[int, int, int], count: int) -> list[np.ndarray]:
    frames = []
    base = np.full((SIZE[1], SIZE[0], 3), color, dtype=np.uint8)
    for index in range(count):
        frame = base.copy()
        cv2.line(frame, (0, 12), (SIZE[0] - 1, 12), (255, 255, 255), 2)
        cv2.rectangle(frame, (20, 30), (80, 70), (20, 20, 20), 2)
        cv2.circle(frame, (120, 45), 14, (245, 245, 245), -1)
        if index % 2:
            cv2.circle(frame, (120, 45), 8, (30, 30, 30), -1)
        frames.append(frame)
    return frames


def motion_frames(count: int, start: int = 0) -> list[np.ndarray]:
    frames = []
    for offset in range(count):
        index = start + offset
        frame = np.full((SIZE[1], SIZE[0], 3), (30, 70, 110), dtype=np.uint8)
        x = 8 + (index * 7) % 120
        cv2.rectangle(frame, (x, 20), (x + 28, 62), (235, 235, 235), -1)
        cv2.line(frame, (0, 75), (SIZE[0] - 1, 75), (20 + index * 3 % 200, 180, 80), 3)
        frames.append(frame)
    return frames


def write_video(path: Path, frames: list[np.ndarray]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, SIZE)
    if not writer.isOpened():
        raise RuntimeError(f"Cannot create synthetic video: {path}")
    for frame in frames:
        writer.write(frame)
    writer.release()


if __name__ == "__main__":
    raise SystemExit(main())
