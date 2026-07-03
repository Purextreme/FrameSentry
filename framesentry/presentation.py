from __future__ import annotations


EVENT_TYPE_LABELS = {
    "metadata_warning": "基础信息提示",
    "black_frame": "疑似黑帧",
    "blank_frame": "疑似灰帧 / 空画面",
    "duplicate_frame": "疑似重复帧",
    "transient_outlier": "疑似瞬时异常帧",
}


SUMMARY_LABELS = {
    "metadata_warnings": "基础信息提示",
    "black_frames": "疑似黑帧",
    "blank_frames": "疑似灰帧 / 空画面",
    "duplicate_frames": "疑似重复帧",
    "transient_outliers": "疑似瞬时异常帧",
}


def event_type_label(event_type: str) -> str:
    return EVENT_TYPE_LABELS.get(event_type, event_type)


def summary_label(summary_key: str) -> str:
    return SUMMARY_LABELS.get(summary_key, summary_key)
