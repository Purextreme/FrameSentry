from __future__ import annotations

import base64
import json
import time
import urllib.request
from pathlib import Path
from typing import Any

from framesentry.analysis import BaseAnalyzer, ModuleResult, VideoContext
from framesentry.config import ApiConfig, load_api_config


SAMPLE_INTERVAL_SECONDS = 1.0
MAX_SAMPLE_FRAMES = 60
UPLOAD_MAX_WIDTH = 1280
JPEG_QUALITY = 88

DETECTION_PROMPT = """你正在检查按时间顺序排列的视频采样帧，每帧前标有精确时间。
请忠实抄录叙事字幕和随镜头出现的中心标题卡，并判断其中是否存在疑似错别字、基础语法问题、明显歧义或前后不一致。
不要把品牌 Logo、产品表面丝印、接口标识、型号参数、画面边缘长期免责声明或其他固定 Overlay 当作字幕。
不要纠正或改写原文，不要根据语义补全看不清的字；无法判断是原文错误还是识别错误时使用 error_type=ocr_uncertain。
相同文字跨连续帧出现时必须合并成一个时间段，不要为每一帧重复输出。忽略纯装饰图形。所有错误结论只能视为“疑似”。
只返回 JSON 对象：
{
  "processed_frame_times": [0.0],
  "segments": [{
    "start_time": 0.0,
    "end_time": 0.0,
    "text": "",
    "suspected_error": false,
    "error_type": "",
    "reason": "",
    "suggestion": "",
    "severity": "info",
    "confidence": 0.0
  }]
}
没有文字时 segments 返回空数组。processed_frame_times 必须逐项返回实际处理的输入帧时间。"""


class LlmSubtitleDetectionAnalyzer(BaseAnalyzer):
    module_id = "llm_subtitle_detection"
    module_name = "LLM字幕检测"

    def __init__(self, api_client: "MiMoClient | None" = None) -> None:
        self.api_client = api_client

    def run(self, context: VideoContext) -> ModuleResult:
        duration = get_video_duration(context.video_path)
        if duration > MAX_SAMPLE_FRAMES:
            return ModuleResult(
                module_id=self.module_id,
                module_name=self.module_name,
                status="skipped",
                severity="info",
                summary={"video_duration_seconds": round(duration, 3), "maximum_duration_seconds": MAX_SAMPLE_FRAMES},
                warnings=[{"message": "视频超过 60 秒，未进行 LLM 字幕检测。"}],
            )
        client = self.api_client or MiMoClient(
            load_api_config(context.settings.get("api_config_path", "config/api_config.json"))
        )
        samples = sample_video(context.video_path)
        if not samples:
            raise RuntimeError(f"No frames could be sampled from video: {context.video_path}")

        started = time.perf_counter()
        response = client.detect(samples)
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        sample_times = [sample["time"] for sample in samples]
        segments, processed_times = validate_detection_response(response, sample_times)
        processed_time_set = {round(value, 3) for value in processed_times}
        missing_times = [value for value in sample_times if round(value, 3) not in processed_time_set]
        warnings = []
        if missing_times:
            warnings.append(
                {
                    "message": "MiMo 未报告全部已提交帧的处理时间，检测结果可能不完整。",
                    "missing_frame_times": missing_times,
                }
            )
        assets = save_representative_frames(segments, samples, context.artifact_dir / "llm_subtitle_screenshots")
        events = [_suspected_error_event(segment) for segment in segments if segment["suspected_error"]]
        usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
        uploaded_bytes = sum(sample["uploaded_bytes"] for sample in samples)

        return ModuleResult(
            module_id=self.module_id,
            module_name=self.module_name,
            severity="warning" if events else "info",
            summary={
                "sampled_frames": len(samples),
                "model_api_calls": 1,
                "total_uploaded_bytes": uploaded_bytes,
                "model_latency_ms": latency_ms,
                "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
                "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
                "total_tokens": int(usage.get("total_tokens", 0) or 0),
                "detected_segments": len(segments),
                "suspected_errors": len(events),
                "missing_processed_frames": len(missing_times),
            },
            events=events,
            assets=assets,
            warnings=warnings,
            data={
                "sample_times": sample_times,
                "processed_frame_times": processed_times,
                "missing_processed_frame_times": missing_times,
                "uploads": [
                    {
                        "time": sample["time"],
                        "upload_size": sample["upload_size"],
                        "uploaded_bytes": sample["uploaded_bytes"],
                    }
                    for sample in samples
                ],
                "segments": segments,
                "model": response.get("model", ""),
                "usage": usage,
            },
        )


class MiMoClient:
    def __init__(self, config: ApiConfig, timeout: float = 180.0) -> None:
        self.config = config
        self.timeout = timeout

    def detect(self, samples: list[dict[str, Any]]) -> dict[str, Any]:
        content: list[dict[str, Any]] = [{"type": "text", "text": DETECTION_PROMPT}]
        for sample in samples:
            content.append({"type": "text", "text": f"frame_time_seconds={sample['time']:.3f}"})
            data_url = "data:image/jpeg;base64," + base64.b64encode(sample["jpeg"]).decode("ascii")
            content.append({"type": "image_url", "image_url": {"url": data_url}})

        endpoint = self.config.base_url.rstrip("/")
        if not endpoint.endswith("/chat/completions"):
            endpoint += "/chat/completions"
        body = json.dumps(
            {
                "model": self.config.multimodal_model,
                "messages": [{"role": "user", "content": content}],
                "response_format": {"type": "json_object"},
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=body,
            headers={"api-key": self.config.api_key, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = json.load(response)
        parsed = _parse_json_content(payload["choices"][0]["message"]["content"])
        parsed["usage"] = payload.get("usage", {})
        parsed["model"] = payload.get("model", self.config.multimodal_model)
        return parsed


def get_video_duration(video_path: Path) -> float:
    import cv2

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
        frame_count = float(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        return frame_count / fps if fps > 0 else 0.0
    finally:
        capture.release()


def sample_video(video_path: Path) -> list[dict[str, Any]]:
    import cv2

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")
    samples: list[dict[str, Any]] = []
    try:
        for second in range(MAX_SAMPLE_FRAMES):
            capture.set(cv2.CAP_PROP_POS_MSEC, second * SAMPLE_INTERVAL_SECONDS * 1000)
            ok, frame = capture.read()
            if not ok:
                break
            jpeg, upload_size = encode_upload_jpeg(frame)
            samples.append(
                {
                    "time": round(second * SAMPLE_INTERVAL_SECONDS, 3),
                    "jpeg": jpeg,
                    "upload_size": upload_size,
                    "uploaded_bytes": len(jpeg),
                    "frame": frame,
                }
            )
    finally:
        capture.release()
    return samples


def encode_upload_jpeg(frame) -> tuple[bytes, list[int]]:
    import cv2

    height, width = frame.shape[:2]
    scale = min(1.0, UPLOAD_MAX_WIDTH / width)
    upload = frame if scale == 1 else cv2.resize(
        frame, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA
    )
    ok, encoded = cv2.imencode(".jpg", upload, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if not ok:
        raise RuntimeError("Failed to encode MiMo upload image as JPEG")
    return encoded.tobytes(), [int(upload.shape[1]), int(upload.shape[0])]


def validate_detection_response(
    response: dict[str, Any], sample_times: list[float]
) -> tuple[list[dict[str, Any]], list[float]]:
    if not isinstance(response.get("processed_frame_times"), list):
        raise ValueError("MiMo response is missing processed_frame_times")
    if not isinstance(response.get("segments"), list):
        raise ValueError("MiMo response is missing segments")
    minimum, maximum = min(sample_times), max(sample_times)
    processed_times = [float(value) for value in response["processed_frame_times"]]

    segments = []
    for raw in response["segments"]:
        if not isinstance(raw, dict) or not str(raw.get("text", "")).strip():
            raise ValueError("MiMo response contains an invalid subtitle segment")
        start_time = max(minimum, min(maximum, float(raw.get("start_time", minimum))))
        end_time = max(start_time, min(maximum, float(raw.get("end_time", start_time))))
        severity = str(raw.get("severity", "info"))
        if severity not in {"info", "low", "medium", "high"}:
            severity = "info"
        segments.append(
            {
                "start_time": round(start_time, 3),
                "end_time": round(end_time, 3),
                "text": str(raw["text"]),
                "suspected_error": bool(raw.get("suspected_error", False)),
                "error_type": str(raw.get("error_type", "")),
                "reason": str(raw.get("reason", "")),
                "suggestion": str(raw.get("suggestion", "")),
                "severity": severity,
                "confidence": max(0.0, min(1.0, float(raw.get("confidence", 0.0) or 0.0))),
                "screenshot": None,
            }
        )
    return segments, processed_times


def save_representative_frames(
    segments: list[dict[str, Any]], samples: list[dict[str, Any]], directory: Path
) -> list[dict[str, str]]:
    import cv2

    assets = []
    if segments:
        directory.mkdir(parents=True, exist_ok=True)
    for index, segment in enumerate(segments):
        middle = (segment["start_time"] + segment["end_time"]) / 2
        sample = min(samples, key=lambda item: abs(item["time"] - middle))
        path = directory / f"segment_{index:04d}.jpg"
        encoded_ok, encoded = cv2.imencode(".jpg", sample["frame"])
        if encoded_ok:
            encoded.tofile(str(path))
        if path.exists() and path.stat().st_size > 0:
            relative = str(Path("llm_subtitle_screenshots") / path.name).replace("\\", "/")
            segment["screenshot"] = relative
            assets.append({"type": "screenshot", "path": relative})
    return assets


def _suspected_error_event(segment: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "subtitle_suspected_error",
        "event_type": "suspected_" + (segment["error_type"] or "text_error"),
        "start_time": segment["start_time"],
        "end_time": segment["end_time"],
        "text": segment["text"],
        "suggestion": segment["suggestion"],
        "reason": "疑似：" + segment["reason"],
        "severity": segment["severity"],
        "confidence": segment["confidence"],
        "screenshot": segment["screenshot"],
    }


def _parse_json_content(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    text = str(content).strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("MiMo response content is not a JSON object")
    return parsed
