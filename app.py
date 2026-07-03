from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from tkinter import Tk, filedialog

import pandas as pd
import streamlit as st

from framesentry.cache import find_cached_report
from framesentry.presentation import EVENT_TYPE_LABELS, event_type_label, summary_label
from framesentry.scanner import scan_video


st.set_page_config(page_title="FrameSentry 视频自审", layout="wide")

ISSUE_EVENT_TYPES = {
    "black_frame",
    "blank_frame",
    "duplicate_frame",
    "transient_outlier",
}


def main() -> None:
    st.title("FrameSentry 视频自审")
    load_report_from_query()

    with st.sidebar:
        st.header("分析设置")
        if "video_path" not in st.session_state:
            st.session_state["video_path"] = ""
        if st.button("选择视频文件", use_container_width=True):
            selected_path = choose_video_file()
            if selected_path:
                st.session_state["video_path"] = selected_path
                st.session_state["output_dir"] = default_output_dir(selected_path)
        video_path = st.text_input("视频文件路径", key="video_path")
        if "output_dir" not in st.session_state:
            st.session_state["output_dir"] = "output/reports"
        output_dir = st.text_input("记录输出目录", key="output_dir")
        sample_scale = st.number_input("分析缩略尺寸", min_value=160, max_value=1080, value=480, step=40)
        max_outlier_frames = st.number_input("瞬时异常最大持续帧数", min_value=1, max_value=5, value=2, step=1)
        save_screenshots = st.checkbox("保存异常截图", value=True)
        use_cache = st.checkbox("同文件未变化时读取缓存", value=True)
        show_debug = st.checkbox("显示调试信息", value=False)
        run_scan = st.button("开始分析", type="primary", use_container_width=True)

        st.divider()
        st.header("打开已有报告")
        if "existing_report" not in st.session_state:
            st.session_state["existing_report"] = ""
        if st.button("选择 report.json", use_container_width=True):
            selected_report = choose_report_file()
            if selected_report:
                st.session_state["existing_report"] = selected_report
        existing_report = st.text_input("report.json 路径", key="existing_report")
        load_report = st.button("读取报告", use_container_width=True)

    if run_scan:
        if not video_path.strip():
            st.error("请先填写视频文件路径。")
        elif not Path(video_path).exists():
            st.error("视频文件不存在，请检查路径。")
        else:
            cached_report = None
            if use_cache:
                cached_report = find_cached_report(
                    video_path,
                    output_root="output",
                    sample_scale=int(sample_scale),
                    max_outlier_frames=int(max_outlier_frames),
                    save_screenshots=save_screenshots,
                )
            if cached_report:
                load_report_file(cached_report)
                st.session_state["cache_message"] = f"已读取缓存报告：{cached_report}"
                st.success("检测到同文件未变化，已直接读取缓存报告。")
            else:
                with st.spinner("正在分析视频，请稍候..."):
                    report = scan_video(
                        video_path,
                        output_dir,
                        sample_scale=int(sample_scale),
                        max_outlier_frames=int(max_outlier_frames),
                        save_screenshots=save_screenshots,
                        write_json=True,
                        write_html=False,
                    )
                st.session_state["report"] = report
                st.session_state["report_dir"] = str(Path(output_dir))
                st.session_state["cache_message"] = "未命中缓存，已完成重新分析。"
                st.success("分析完成。")

    if load_report:
        report_path = Path(existing_report)
        if not report_path.exists():
            st.error("报告文件不存在，请检查路径。")
        else:
            load_report_file(report_path)
            st.success("报告已读取。")

    report = st.session_state.get("report")
    if not report:
        st.info("请在左侧指定视频并开始分析，或读取已有 report.json。")
        return

    render_report(report, Path(st.session_state.get("report_dir", ".")), show_debug=show_debug)


def render_report(report: dict, report_dir: Path, *, show_debug: bool = False) -> None:
    modules = report.get("modules", {})
    metadata_module = modules.get("metadata", {})
    frame_issue_module = modules.get("frame_issues", {})
    video = _module_data(metadata_module).get("video") or report.get("video", {})
    summary = report.get("summary", {})
    all_events = report.get("events", [])
    metadata_events = metadata_module.get("events") or [event for event in all_events if event.get("type") == "metadata_warning"]
    events = frame_issue_module.get("events") or [event for event in all_events if event.get("type") in ISSUE_EVENT_TYPES]

    st.subheader("视频基础信息")
    cols = st.columns(4)
    cols[0].metric("分辨率", f"{video.get('width')} x {video.get('height')}")
    cols[1].metric("帧率", video.get("fps"))
    cols[2].metric("时长（秒）", _format_number(video.get("duration")))
    cols[3].metric("事件总数", len(all_events) if all_events else len(metadata_events) + len(events))
    st.caption(str(video.get("path", "")))
    cache_message = st.session_state.get("cache_message")
    if cache_message:
        st.info(cache_message)
    render_module_errors(metadata_module)
    render_module_errors(frame_issue_module)

    st.subheader("异常摘要")
    summary_cols = st.columns(3)
    for index, (key, value) in enumerate(summary.items()):
        summary_cols[index % 3].metric(summary_label(key), value)

    with st.expander("Metadata", expanded=bool(metadata_events)):
        if metadata_module:
            st.caption(_module_status_text(metadata_module))
        if metadata_events:
            render_event_table(metadata_events)
        else:
            st.info("没有基础信息提示。")

    st.subheader("Frame Issues")
    if frame_issue_module:
        st.caption(_module_status_text(frame_issue_module))

    st.subheader("筛选")
    confidence = st.slider("最低置信度", min_value=0.0, max_value=1.0, value=0.7, step=0.05)
    labels = [
        "全部异常",
        event_type_label("duplicate_frame"),
        event_type_label("black_frame"),
        event_type_label("blank_frame"),
        event_type_label("transient_outlier"),
    ]
    selected_label = st.selectbox("异常类型", labels, index=0)
    selected_type = _event_type_from_label(selected_label)
    filtered = []
    for event in events:
        event_confidence = float(event.get("confidence", 1.0))
        event_type = event.get("type", "")
        if event_confidence < confidence:
            continue
        if selected_label == "全部异常" and event_type not in ISSUE_EVENT_TYPES:
            continue
        if selected_type and event_type != selected_type:
            continue
        filtered.append(event)

    st.subheader("事件概览")
    st.caption(f"当前显示 {len(filtered)} / {len(events)} 个事件。")
    render_event_table(filtered)
    render_event_review_list(filtered, report_dir)
    render_debug_info(filtered, report_dir, expanded=show_debug)


def render_module_errors(module: dict) -> None:
    if module.get("status") != "failed":
        return
    errors = module.get("errors") or []
    message = errors[0].get("message") if errors and isinstance(errors[0], dict) else "模块运行失败。"
    st.error(f"{module.get('module_name', 'Analyzer')}: {message}")


def render_event_table(events: list[dict]) -> None:
    if not events:
        st.info("当前筛选条件下没有事件。")
        return

    rows = []
    for event in events:
        rows.append(
            {
                "帧": _frame_range(event),
                "时间码": _timecode_range(event),
                "问题": event_type_label(event.get("type", "")),
                "置信度": event.get("confidence", ""),
                "错误": event.get("reason") or event.get("message") or "",
            }
        )
    st.dataframe(
        pd.DataFrame(rows),
        use_container_width=True,
        hide_index=True,
        height=_event_table_height(len(rows)),
        column_config={
            "帧": st.column_config.TextColumn("帧", width="small"),
            "时间码": st.column_config.TextColumn("时间码", width="medium"),
            "问题": st.column_config.TextColumn("问题", width="medium"),
            "置信度": st.column_config.NumberColumn("置信度", format="%.2f", width="small"),
            "错误": st.column_config.TextColumn("错误", width="large"),
        },
    )


def render_event_review_list(events: list[dict], report_dir: Path) -> None:
    review_events = [event for event in events if event.get("screenshots")]
    if not review_events:
        if events:
            st.info("当前筛选结果没有截图记录。请确认本次分析勾选了“保存异常截图”，或重新分析生成截图。")
        return

    st.subheader("截图复核")
    for index, event in enumerate(review_events):
        label = (
            f"{index + 1}. {event_type_label(event.get('type', ''))} | "
            f"{_timecode_range(event)} | 帧 {_frame_range(event)} | "
            f"置信度 {event.get('confidence', '')}"
        )
        with st.expander(label, expanded=index == 0):
            render_event_detail(event, report_dir)


def render_event_detail(event: dict, report_dir: Path) -> None:
    metric_cols = st.columns([1.2, 1.6, 1.6, 1])
    metric_cols[0].caption("问题")
    metric_cols[0].markdown(f"**{event_type_label(event.get('type', ''))}**")
    metric_cols[1].caption("时间码")
    metric_cols[1].markdown(f"**{_timecode_range(event)}**")
    metric_cols[2].caption("帧")
    metric_cols[2].markdown(f"**{_frame_range(event)}**")
    metric_cols[3].caption("置信度")
    metric_cols[3].markdown(f"**{event.get('confidence', '')}**")

    st.write(event.get("reason") or event.get("message") or "")
    render_screenshots(event, report_dir)

    diagnostic = _diagnostic_fields(event)
    if diagnostic:
        with st.expander("诊断指标", expanded=False):
            st.json(diagnostic, expanded=False)


def render_screenshots(event: dict, report_dir: Path) -> None:
    screenshots = event.get("screenshots", {})
    if not screenshots:
        if event.get("type") == "metadata_warning":
            st.info("基础信息提示没有对应截图。请在上方选择具体异常事件查看截图。")
        else:
            st.info("该事件没有截图记录。请确认分析时勾选了“保存异常截图”。")
        return

    image_items = []
    for label, screenshot_path in screenshots.items():
        resolved = _resolve_screenshot_path(report_dir, screenshot_path)
        if resolved.exists():
            image_items.append((label, resolved))

    if not image_items:
        st.warning(f"没有找到截图文件。当前报告目录：{report_dir}")
        return

    label_map = {"before": "前一帧", "current": "当前帧", "after": "后一帧"}
    cols = st.columns(len(image_items))
    for col, (label, path) in zip(cols, image_items):
        col.image(str(path), caption=label_map.get(label, label), use_container_width=True)


def render_debug_info(events: list[dict], report_dir: Path, *, expanded: bool) -> None:
    if not expanded:
        return

    with st.expander("调试信息", expanded=True):
        with_screenshot_fields = [event for event in events if event.get("screenshots")]
        resolved_files = []
        missing_files = []
        for event in with_screenshot_fields:
            for label, screenshot_path in event.get("screenshots", {}).items():
                resolved = _resolve_screenshot_path(report_dir, screenshot_path)
                item = {
                    "事件": event_type_label(event.get("type", "")),
                    "帧": _frame_range(event),
                    "截图": label,
                    "路径": str(resolved),
                }
                if resolved.exists():
                    resolved_files.append(item)
                else:
                    missing_files.append(item)

        st.write(
            {
                "报告目录": str(report_dir.resolve()),
                "筛选后事件数": len(events),
                "带截图字段的事件数": len(with_screenshot_fields),
                "已找到截图文件数": len(resolved_files),
                "缺失截图文件数": len(missing_files),
            }
        )
        if missing_files:
            st.write("缺失截图文件示例")
            st.dataframe(pd.DataFrame(missing_files[:20]), use_container_width=True, hide_index=True)


def load_report_file(report_path: Path) -> None:
    st.session_state["report"] = json.loads(report_path.read_text(encoding="utf-8"))
    st.session_state["report_dir"] = str(report_path.parent.resolve())
    st.session_state["loaded_report_path"] = str(report_path.resolve())
    st.session_state["existing_report"] = str(report_path.resolve())


def load_report_from_query() -> None:
    report_param = st.query_params.get("report")
    if not report_param:
        return
    report_path = Path(report_param)
    loaded = st.session_state.get("loaded_report_path")
    if loaded == str(report_path.resolve()):
        return
    if report_path.exists():
        load_report_file(report_path)


def _frame_range(event: dict) -> str:
    start = event.get("start_frame", "")
    end = event.get("end_frame", "")
    if start == end or end == "":
        return str(start)
    return f"{start}-{end}"


def _timecode_range(event: dict) -> str:
    start = event.get("start_timecode", "")
    end = event.get("end_timecode", "")
    if start == end or end == "":
        return str(start)
    return f"{start} - {end}"


def _event_table_height(row_count: int) -> int:
    header_height = 38
    row_height = 35
    padding = 6
    return min(520, header_height + row_count * row_height + padding)


def _diagnostic_fields(event: dict) -> dict:
    keys = {
        "incoming_diff": "进入差异",
        "outgoing_diff": "退出差异",
        "incoming_hist_diff": "进入颜色差异",
        "outgoing_hist_diff": "退出颜色差异",
        "incoming_change_coverage": "进入变化覆盖率",
        "outgoing_change_coverage": "退出变化覆盖率",
        "left_stability": "左侧稳定度",
        "right_stability": "右侧稳定度",
        "diff_to_prev": "与上一帧差异",
        "before_motion": "前侧运动强度",
        "after_motion": "后侧运动强度",
    }
    return {label: event[key] for key, label in keys.items() if key in event}


def _resolve_screenshot_path(report_dir: Path, screenshot_path: str) -> Path:
    path = Path(screenshot_path)
    if path.is_absolute():
        return path
    return report_dir / path


def _event_type_from_label(label: str) -> str | None:
    if label == "全部异常":
        return None
    for event_type, event_label in EVENT_TYPE_LABELS.items():
        if label == event_label:
            return event_type
    return None


def _module_data(module: dict) -> dict:
    data = module.get("data")
    return data if isinstance(data, dict) else {}


def _module_status_text(module: dict) -> str:
    return f"{module.get('module_name', 'Analyzer')} status: {module.get('status', 'unknown')}"


def _format_number(value) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.2f}"
    return str(value)


def choose_video_file() -> str:
    root = Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        path = filedialog.askopenfilename(
            title="选择视频文件",
            filetypes=[
                ("视频文件", "*.mp4 *.mov *.m4v *.avi *.mkv"),
                ("所有文件", "*.*"),
            ],
        )
        return str(path) if path else ""
    finally:
        root.destroy()


def choose_report_file() -> str:
    root = Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        path = filedialog.askopenfilename(
            title="选择历史 report.json",
            initialdir=str(Path("output").resolve()),
            filetypes=[
                ("FrameSentry 报告", "report.json"),
                ("JSON 文件", "*.json"),
                ("所有文件", "*.*"),
            ],
        )
        return str(path) if path else ""
    finally:
        root.destroy()


def default_output_dir(video_path: str) -> str:
    stem = safe_path_name(Path(video_path).stem)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return str(Path("output") / "reports" / f"{stem}_{stamp}")


def safe_path_name(name: str) -> str:
    invalid = '<>:"/\\|?*'
    cleaned = "".join("_" if char in invalid else char for char in name).strip()
    return cleaned or "video"


if __name__ == "__main__":
    main()
