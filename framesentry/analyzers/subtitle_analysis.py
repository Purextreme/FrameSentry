from __future__ import annotations

import base64
import difflib
import hashlib
import json
import math
import time
import urllib.request
from pathlib import Path
from typing import Any

from framesentry.analysis import BaseAnalyzer, ModuleResult, VideoContext
from framesentry.config import ApiConfig, load_api_config
from framesentry.metadata import read_metadata


SAMPLE_INTERVAL_SECONDS = 0.5
LOCAL_SAMPLE_WIDTH = 1280
PIXEL_STABILITY_TOLERANCE = 8
LOCAL_CONTRAST_THRESHOLD = 6
MIN_STABLE_COMPONENT_AREA = 3
MIN_STABLE_CLUSTER_PIXELS = 100
WHOLE_FRAME_STABLE_RATIO = 0.90
STABLE_MASK_IOU_THRESHOLD = 0.55
UPLOAD_MAX_EDGE = 1920
JPEG_QUALITY = 88
TEXT_SIMILARITY_THRESHOLD = 0.9

OCR_PROMPT = """忠实识别图片中全部可见文字。不要纠正错别字，不要根据语义补全；保留大小写、数字、标点和换行；看不清的字符写作 [?]；没有文字时返回空结果。只返回 JSON：{\"text\":\"\",\"lines\":[],\"has_text\":false}。如可用，可额外返回 bbox 和 confidence。"""
REVIEW_PROMPT = """检查当前文字是否存在疑似错别字、基础语法问题、明显歧义或与前后文字明显不一致。不要改写 OCR 原文；无法判断是原文错误还是 OCR 错误时使用 error_type=ocr_uncertain。AI 结论均为疑似。只返回 JSON：{\"suspected_error\":false,\"error_type\":\"\",\"reason\":\"\",\"suggestion\":\"\",\"severity\":\"info\",\"confidence\":0.0}。"""


class SubtitleAnalysisAnalyzer(BaseAnalyzer):
    module_id = "subtitle_analysis"
    module_name = "Subtitle Analysis"

    def __init__(self, api_client: "SiliconFlowClient | None" = None) -> None:
        self.api_client = api_client

    def run(self, context: VideoContext) -> ModuleResult:
        config_path = context.settings.get("api_config_path", "config/api_config.json")
        client = self.api_client or SiliconFlowClient(load_api_config(config_path))
        metadata = context.metadata or read_metadata(context.video_path)
        context.metadata = metadata
        records, filter_stats, warnings = sample_and_ocr(context.video_path, metadata.fps, client)
        segments = merge_ocr_records(records)
        duration = float(metadata.duration or 0)
        if not duration and metadata.fps:
            duration = float((metadata.frame_count or 0) / metadata.fps)
        overlay_lines = mark_persistent_overlays(segments, duration)
        screenshot_assets = save_representative_frames(segments, context.artifact_dir / "subtitle_screenshots")

        reviewed = 0
        events = []
        for index, segment in enumerate(segments):
            review_text = segment.get("text_without_overlays", segment["text"])
            if not review_text or segment["persistent_overlay"]:
                continue
            previous_text = segments[index - 1].get("text_without_overlays", segments[index - 1]["text"]) if index else ""
            next_text = segments[index + 1].get("text_without_overlays", segments[index + 1]["text"]) if index + 1 < len(segments) else ""
            try:
                review = client.review(previous_text, review_text, next_text)
                segment["review"] = review
                reviewed += 1
            except Exception as exc:
                warnings.append({"stage": "text_review", "start_time": segment["start_time"], "message": str(exc)})
                continue
            if review.get("suspected_error"):
                events.append(_review_event(segment, review))

        latencies = [record["latency_ms"] for record in records if record.get("latency_ms") is not None]
        summary = {
            "sampled_frames": filter_stats["sampled_frames"],
            "ocr_candidate_frames": filter_stats["ocr_candidate_frames"],
            "ocr_api_calls": filter_stats["ocr_api_calls"],
            "skipped_by_local_filter": filter_stats["skipped_by_local_filter"],
            "detected_segments": len([segment for segment in segments if segment["text"]]),
            "persistent_overlays": sum(bool(segment["persistent_overlay"]) for segment in segments),
            "reviewed_segments": reviewed,
            "suspected_errors": len(events),
            "total_uploaded_bytes": sum(record.get("uploaded_bytes", 0) for record in records),
            "average_ocr_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
        }
        severity = "warning" if events or warnings else "info"
        return ModuleResult(
            module_id=self.module_id,
            module_name=self.module_name,
            severity=severity,
            summary=summary,
            events=events,
            assets=screenshot_assets,
            data={
                "segments": [_public_segment(segment) for segment in segments],
                "ocr_records": [_public_record(record) for record in records],
                "local_filter": filter_stats,
                "persistent_overlay_lines": overlay_lines,
            },
            warnings=warnings,
        )


class SiliconFlowClient:
    def __init__(self, config: ApiConfig, timeout: float = 60.0) -> None:
        self.config = config
        self.timeout = timeout

    def ocr(self, jpeg: bytes) -> dict[str, Any]:
        if not self.config.ocr_model:
            raise ValueError("ocr_model is empty in API config")
        data_url = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")
        return self._chat(
            self.config.ocr_model,
            [{"role": "user", "content": [{"type": "text", "text": OCR_PROMPT}, {"type": "image_url", "image_url": {"url": data_url}}]}],
        )

    def review(self, previous_text: str, current_text: str, next_text: str) -> dict[str, Any]:
        if not self.config.text_model:
            raise ValueError("text_model is empty in API config")
        content = f"{REVIEW_PROMPT}\nprevious_text: {previous_text}\ncurrent_text: {current_text}\nnext_text: {next_text}"
        return self._chat(self.config.text_model, [{"role": "user", "content": content}])

    def _chat(self, model: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
        endpoint = self.config.base_url.rstrip("/")
        if not endpoint.endswith("/chat/completions"):
            endpoint += "/chat/completions"
        body = json.dumps({"model": model, "messages": messages, "response_format": {"type": "json_object"}}).encode("utf-8")
        request = urllib.request.Request(endpoint, data=body, headers={"Authorization": f"Bearer {self.config.api_key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = json.load(response)
        content = payload["choices"][0]["message"]["content"]
        parsed = _parse_json_content(content)
        parsed["raw_usage"] = payload.get("usage")
        return parsed


def sample_and_ocr(video_path: Path, fps: float, client: SiliconFlowClient) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    import cv2
    import numpy as np

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")
    effective_fps = fps or float(capture.get(cv2.CAP_PROP_FPS) or 0)
    step = max(1, round(effective_fps * SAMPLE_INTERVAL_SECONDS)) if effective_fps else 1
    previous_previous_sample = None
    previous_sample = None
    previous_frame = None
    previous_timestamp = None
    previous_stable_mask = None
    stable_streak = 0
    stable_cycle_ocr = False
    cache: dict[str, dict[str, Any]] = {}
    records: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    stats = {"sampled_frames": 0, "ocr_candidate_frames": 0, "ocr_api_calls": 0, "skipped_by_local_filter": 0, "samples": []}
    frame_index = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if frame_index % step:
                frame_index += 1
                continue
            timestamp = frame_index / effective_fps if effective_fps else 0.0
            small = _small_gray(frame, LOCAL_SAMPLE_WIDTH)
            stability, stable_mask = calculate_pixel_stability(previous_previous_sample, previous_sample, small)
            mask_iou = _mask_iou(previous_stable_mask, stable_mask)
            has_text_like_clusters = stability["stable_cluster_pixels"] >= stability["stable_cluster_threshold"]
            same_stable_shape = has_text_like_clusters and mask_iou >= STABLE_MASK_IOU_THRESHOLD
            if stability["whole_frame_stable"] and not has_text_like_clusters:
                same_stable_shape = previous_stable_mask is not None and not bool(previous_stable_mask.any())
            stable_streak = stable_streak + 1 if same_stable_shape else (1 if stability["has_stable_clusters"] else 0)
            if not stability["has_stable_clusters"] or (
                previous_stable_mask is not None
                and has_text_like_clusters
                and mask_iou < STABLE_MASK_IOU_THRESHOLD
            ):
                stable_cycle_ocr = False
            candidate = previous_sample is None or (stable_streak >= 1 and not stable_cycle_ocr)
            if candidate:
                stable_cycle_ocr = True
            candidate_frame = previous_frame if previous_sample is not None and previous_frame is not None else frame
            candidate_timestamp = previous_timestamp if previous_timestamp is not None else timestamp
            stats["sampled_frames"] += 1
            stats["samples"].append({"time": round(timestamp, 3), **stability, "stable_mask_iou": round(mask_iou, 4), "stable_streak": stable_streak, "candidate": candidate, "candidate_frame_time": round(candidate_timestamp, 3) if candidate else None})
            if candidate:
                stats["ocr_candidate_frames"] += 1
                jpeg, upload_size = encode_upload_jpeg(candidate_frame)
                image_hash = hashlib.sha256(jpeg).hexdigest()
                started = time.perf_counter()
                try:
                    if image_hash in cache:
                        result = cache[image_hash]
                        latency_ms = 0.0
                        cached = True
                    else:
                        result = client.ocr(jpeg)
                        latency_ms = (time.perf_counter() - started) * 1000
                        cache[image_hash] = result
                        stats["ocr_api_calls"] += 1
                        cached = False
                    text = str(result.get("text", "")) if result.get("has_text", bool(result.get("text"))) else ""
                    records.append({"time": round(candidate_timestamp, 3), "text": text, "response": result, "latency_ms": round(latency_ms, 2), "upload_size": upload_size, "uploaded_bytes": len(jpeg), "image_hash": image_hash, "cached": cached, "change": {"mean_diff": stability["mean_diff"]}, "_frame": candidate_frame.copy()})
                except Exception as exc:
                    warnings.append({"stage": "ocr", "time": round(candidate_timestamp, 3), "message": str(exc)})
            else:
                stats["skipped_by_local_filter"] += 1
            previous_previous_sample = previous_sample
            previous_sample = small
            previous_frame = frame.copy()
            previous_timestamp = timestamp
            previous_stable_mask = stable_mask
            frame_index += 1
    finally:
        capture.release()
    return records, stats, warnings


def calculate_pixel_stability(before, previous, current) -> tuple[dict[str, Any], Any]:
    if before is None or previous is None:
        threshold = max(20, round(MIN_STABLE_CLUSTER_PIXELS * (current.shape[1] / LOCAL_SAMPLE_WIDTH) ** 2))
        return {"stable_ratio": 0.0, "mean_diff": 255.0, "stable_cluster_pixels": 0, "stable_components": 0, "whole_frame_stable": False, "stable_cluster_threshold": threshold, "has_stable_clusters": False}, None
    import cv2
    import numpy as np

    first_diff = cv2.absdiff(before, previous)
    second_diff = cv2.absdiff(previous, current)
    stable = (first_diff <= PIXEL_STABILITY_TOLERANCE) & (second_diff <= PIXEL_STABILITY_TOLERANCE)
    contrast = cv2.absdiff(previous, cv2.GaussianBlur(previous, (5, 5), 0)) > LOCAL_CONTRAST_THRESHOLD
    candidate = (stable & contrast).astype(np.uint8)
    count, labels, component_stats, _ = cv2.connectedComponentsWithStats(candidate, connectivity=8)
    kept = np.zeros_like(candidate)
    components = 0
    for label in range(1, count):
        if component_stats[label, cv2.CC_STAT_AREA] >= MIN_STABLE_COMPONENT_AREA:
            kept[labels == label] = 1
            components += 1
    cluster_pixels = int(np.count_nonzero(kept))
    scaled_cluster_threshold = max(
        20,
        round(MIN_STABLE_CLUSTER_PIXELS * (current.shape[1] / LOCAL_SAMPLE_WIDTH) ** 2),
    )
    stable_ratio = float(np.count_nonzero(stable) / stable.size)
    whole_frame_stable = stable_ratio >= WHOLE_FRAME_STABLE_RATIO
    return {
        "stable_ratio": stable_ratio,
        "mean_diff": float(np.mean(second_diff)),
        "stable_cluster_pixels": cluster_pixels,
        "stable_components": components,
        "whole_frame_stable": whole_frame_stable,
        "stable_cluster_threshold": scaled_cluster_threshold,
        "has_stable_clusters": whole_frame_stable or cluster_pixels >= scaled_cluster_threshold,
    }, kept


def _mask_iou(left, right) -> float:
    if left is None or right is None:
        return 0.0
    import numpy as np

    union = np.count_nonzero((left > 0) | (right > 0))
    if not union:
        return 0.0
    return float(np.count_nonzero((left > 0) & (right > 0)) / union)


def _small_gray(frame, width: int):
    import cv2

    height, source_width = frame.shape[:2]
    target_width = min(width, source_width)
    target_height = max(1, round(height * target_width / source_width))
    resized = cv2.resize(frame, (target_width, target_height), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)


def encode_upload_jpeg(frame) -> tuple[bytes, list[int]]:
    import cv2

    height, width = frame.shape[:2]
    scale = min(1.0, UPLOAD_MAX_EDGE / max(width, height))
    upload = frame if scale == 1 else cv2.resize(frame, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)
    ok, encoded = cv2.imencode(".jpg", upload, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if not ok:
        raise RuntimeError("Failed to encode OCR upload image as JPEG")
    return encoded.tobytes(), [int(upload.shape[1]), int(upload.shape[0])]


def merge_ocr_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for record in records:
        text = record.get("text", "")
        if segments and texts_similar(segments[-1]["text"], text):
            segment = segments[-1]
            segment["end_time"] = record["time"]
            segment["source_frame_times"].append(record["time"])
            segment["_records"].append(record)
        else:
            segments.append({"start_time": record["time"], "end_time": record["time"], "text": text, "representative_frame": None, "source_frame_times": [record["time"]], "persistent_overlay": False, "_records": [record]})
    return segments


def texts_similar(left: str, right: str) -> bool:
    if left == right:
        return True
    normalized_left = "".join(left.split())
    normalized_right = "".join(right.split())
    if normalized_left == normalized_right:
        return True
    if not normalized_left or not normalized_right:
        return False
    return difflib.SequenceMatcher(None, normalized_left, normalized_right).ratio() >= TEXT_SIMILARITY_THRESHOLD


def _text_lines(result: dict[str, Any], text: str) -> list[str]:
    raw_lines = result.get("lines")
    lines = [str(line).strip() for line in raw_lines if isinstance(line, str) and line.strip()] if isinstance(raw_lines, list) else []
    if not lines:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines


def _normalized_line(line: str) -> str:
    return "".join(line.casefold().split())


def _same_line_set(left: list[str], right: list[str]) -> bool:
    return {_normalized_line(line) for line in left} == {_normalized_line(line) for line in right}


def mark_persistent_overlays(segments: list[dict[str, Any]], video_duration: float) -> list[dict[str, Any]]:
    threshold = max(15.0, video_duration * 0.6)
    observations: dict[str, dict[str, Any]] = {}
    record_count = 0
    for segment in segments:
        records = segment.get("_records", [])
        if records:
            for record in records:
                record_count += 1
                lines = _text_lines(record.get("response", {}), record.get("text", ""))
                seen_in_record: set[str] = set()
                for line in lines:
                    key = _normalized_line(line)
                    if key in seen_in_record:
                        continue
                    seen_in_record.add(key)
                    item = observations.setdefault(key, {"text": line, "times": []})
                    item["times"].append(float(record["time"]))

    minimum_occurrences = max(3, math.ceil(record_count * 0.2))
    overlay_keys = {
        key for key, item in observations.items()
        if len(item["times"]) >= minimum_occurrences and max(item["times"]) - min(item["times"]) >= threshold
    }
    for segment in segments:
        lines = [line.strip() for line in segment.get("text", "").splitlines() if line.strip()]
        overlay_lines = [line for line in lines if _normalized_line(line) in overlay_keys]
        dynamic_lines = [line for line in lines if _normalized_line(line) not in overlay_keys]
        segment["persistent_overlay_lines"] = overlay_lines
        segment["text_without_overlays"] = "\n".join(dynamic_lines)
        whole_segment_persistent = bool(
            not segment.get("_records")
            and segment["text"]
            and segment["end_time"] - segment["start_time"] >= threshold
        )
        segment["persistent_overlay"] = whole_segment_persistent or bool(lines and not dynamic_lines)
    return [
        {
            "text": item["text"],
            "first_time": min(item["times"]),
            "last_time": max(item["times"]),
            "occurrences": len(item["times"]),
        }
        for key, item in observations.items() if key in overlay_keys
    ]


def save_representative_frames(segments: list[dict[str, Any]], directory: Path) -> list[dict[str, str]]:
    import cv2

    assets = []
    for index, segment in enumerate(segments):
        if not segment["text"]:
            continue
        records = segment["_records"]
        middle = (segment["start_time"] + segment["end_time"]) / 2
        representative = min(records, key=lambda item: (item["change"]["mean_diff"], abs(item["time"] - middle)))
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"segment_{index:04d}.jpg"
        if cv2.imwrite(str(path), representative["_frame"]):
            relative = str(Path("subtitle_screenshots") / path.name).replace("\\", "/")
            segment["representative_frame"] = relative
            assets.append({"type": "screenshot", "path": relative})
    return assets


def _review_event(segment: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    screenshot = segment.get("representative_frame")
    return {
        "type": "subtitle_suspected_error",
        "event_type": "suspected_" + str(review.get("error_type") or "text_error"),
        "start_time": segment["start_time"], "end_time": segment["end_time"], "text": segment["text"],
        "suggestion": review.get("suggestion", ""), "reason": review.get("reason", ""),
        "severity": review.get("severity", "info"), "confidence": review.get("confidence", 0.0),
        "screenshot": screenshot, "screenshots": {"representative": screenshot} if screenshot else {},
    }


def _public_segment(segment: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in segment.items() if not key.startswith("_")}


def _public_record(record: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if not key.startswith("_")}


def _parse_json_content(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    text = str(content).strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("API response content is not a JSON object")
    return parsed
