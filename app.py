from __future__ import annotations

import json
import logging
from datetime import datetime
from html import escape
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from framesentry.presentation import EVENT_TYPE_LABELS, event_type_label, summary_label
from framesentry.scanner import RUNTIME_CACHE_KEY, scan_video


LOGGER = logging.getLogger(__name__)

st.set_page_config(page_title="FrameSentry 视频自审", layout="wide")

ISSUE_EVENT_TYPES = {
    "black_frame",
    "blank_frame",
    "duplicate_frame",
    "transient_outlier",
}

COLOR_METRIC_HELP = {
    "hsv": "HSV 主色来自每个采样帧的主色聚类：H 色相单位为度，范围 0-360；S 饱和度和 V 亮度单位为百分比，范围 0-100%。",
    "color_dispersion": "色彩离散度是 B/G/R 三个颜色通道标准差的平均值，并归一化为 0-100%。数值越高，画面颜色分布越分散。",
    "brightness_dispersion": "亮度离散度是灰度亮度标准差，并归一化为 0-100%。数值越高，画面明暗分布越分散。",
    "contrast_score": "对比度使用灰度亮度第 95 百分位与第 5 百分位的差值，并归一化为 0-100%。",
    "warmth_score": "冷暖倾向 = 平均红色通道减平均蓝色通道，并归一化到 -100 到 100；正值偏暖，负值偏冷，接近 0 更中性。",
}

MOTION_METRIC_HELP = {
    "motion_intensity": "运动强度基于相邻采样帧的稠密光流位移。平均运动量反映画面整体运动，P95 运动量更偏向画面中运动最明显的区域。",
    "p95_motion": "P95 是第 95 百分位：把画面里所有像素的运动量从小到大排序后，取 95% 位置的值，用来观察运动较明显区域，避免被极少数异常点影响。",
    "motion_variability": "运动波动度是各采样点平均运动量的标准差。数值越高，说明运动节奏越不稳定，越可能出现时快时慢或突然加速。",
    "moving_area": "运动覆盖面积表示光流位移不低于 0.5 像素的缩略图像素占比。数值越高，说明运动覆盖范围越接近全画面。",
}

MOTION_LEVEL_LABELS = {
    "still": "基本静止",
    "low": "较慢",
    "medium": "中等",
    "high": "较快",
}

MOTION_RHYTHM_LABELS = {
    "mostly_still": "整体基本静止",
    "steady": "整体较平稳",
    "variable": "快慢变化明显",
    "bursty": "存在明显运动峰值",
}


def main() -> None:
    st.title("FrameSentry 视频自审")
    load_report_from_query()

    with st.sidebar:
        st.header("分析设置")
        if "video_path" not in st.session_state:
            st.session_state["video_path"] = ""
        if st.button("选择视频文件", width="stretch"):
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
        use_cache = st.checkbox("同文件未变化时读取缓存", value=True)
        run_scan = st.button("开始分析", type="primary", width="stretch")

        st.divider()
        st.header("打开已有报告")
        if "existing_report" not in st.session_state:
            st.session_state["existing_report"] = ""
        if st.button("选择 report.json", width="stretch"):
            selected_report = choose_report_file()
            if selected_report:
                st.session_state["existing_report"] = selected_report
        existing_report = st.text_input("report.json 路径", key="existing_report")
        load_report = st.button("读取报告", width="stretch")

    if run_scan:
        if not video_path.strip():
            st.error("请先填写视频文件路径。")
        elif not Path(video_path).exists():
            st.error("视频文件不存在，请检查路径。")
        else:
            with st.spinner("正在分析视频，请稍候..."):
                report = scan_video(
                    video_path,
                    output_dir,
                    sample_scale=int(sample_scale),
                    max_outlier_frames=int(max_outlier_frames),
                    use_cache=use_cache,
                )
            cache_info = report.pop(RUNTIME_CACHE_KEY, {})
            report_path = Path(cache_info.get("report_path", Path(output_dir) / "report.json"))
            st.session_state["report"] = report
            st.session_state["report_dir"] = str(report_path.parent.resolve())
            if cache_info.get("cache_hit"):
                st.session_state["cache_message"] = f"已读取缓存报告：{report_path}"
                st.success("检测到同文件未变化，已直接读取缓存报告。")
            else:
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

    render_report(report, Path(st.session_state.get("report_dir", ".")))


def render_report(report: dict, report_dir: Path) -> None:
    modules = report.get("modules", {})
    metadata_module = modules.get("metadata", {})
    frame_issue_module = modules.get("frame_issues", {})
    color_module = modules.get("color_analysis", {})
    motion_module = modules.get("motion_analysis", {})
    video = _module_data(metadata_module).get("video") or report.get("video", {})
    summary = report.get("summary", {})
    metadata_events = metadata_module.get("events", [])
    events = frame_issue_module.get("events", [])

    st.subheader("视频基础信息")
    cols = st.columns(4)
    cols[0].metric("分辨率", f"{video.get('width')} x {video.get('height')}")
    cols[1].metric("帧率", video.get("fps"))
    cols[2].metric("时长（秒）", _format_number(video.get("duration")))
    cols[3].metric("事件总数", len(metadata_events) + len(events))
    st.caption(str(video.get("path", "")))
    cache_message = st.session_state.get("cache_message")
    if cache_message:
        st.info(cache_message)

    overview_tab, metadata_tab, frame_tab, color_tab, motion_tab = st.tabs(
        ["总览", "元数据", "画面异常", "色彩分析", "运动分析"]
    )

    with overview_tab:
        st.subheader("异常摘要")
        summary_cols = st.columns(3)
        for index, (key, value) in enumerate(summary.items()):
            summary_cols[index % 3].metric(summary_label(key), value)

    with metadata_tab:
        if metadata_module:
            st.caption(_module_status_text(metadata_module))
        render_module_errors(metadata_module)
        render_metadata_details(video)
        if metadata_events:
            render_event_table(metadata_events)
        else:
            st.info("没有基础信息提示。")

    with frame_tab:
        if frame_issue_module:
            st.caption(_module_status_text(frame_issue_module))
        render_module_errors(frame_issue_module)

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
        log_debug_info(filtered, report_dir)

    with color_tab:
        render_color_analysis(color_module)

    with motion_tab:
        render_motion_analysis(motion_module)


def render_module_errors(module: dict) -> None:
    if module.get("status") != "failed":
        return
    errors = module.get("errors") or []
    message = errors[0].get("message") if errors and isinstance(errors[0], dict) else "模块运行失败。"
    st.error(f"{module.get('module_name', 'Analyzer')}: {message}")


def render_color_analysis(module: dict) -> None:
    if not module:
        st.info("当前报告没有颜色分析数据。关闭缓存并重新分析可生成颜色趋势图。")
        return

    st.caption(_module_status_text(module))
    render_module_errors(module)
    if module.get("status") == "failed":
        return

    data = _module_data(module)
    samples = data.get("samples") or []
    if not samples:
        st.info("当前报告没有颜色分析数据。")
        return

    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    metric_cols = st.columns(4)
    metric_cols[0].metric("采样点", summary.get("sample_count", len(samples)))
    metric_cols[1].metric("平均色相（度）", _format_number(summary.get("average_hue")))
    metric_cols[2].metric("平均饱和度（%）", _format_number(summary.get("average_saturation")))
    metric_cols[3].metric("平均亮度（%）", _format_number(summary.get("average_value")))

    detail_cols = st.columns(3)
    detail_cols[0].metric("平均色彩离散度（%）", _format_number(summary.get("average_color_dispersion")))
    detail_cols[1].metric("平均对比度（%）", _format_number(summary.get("average_contrast")))
    detail_cols[2].metric("平均冷暖倾向（-100 到 100）", _format_number(summary.get("average_warmth")))
    st.caption(COLOR_METRIC_HELP["color_dispersion"])
    st.caption(COLOR_METRIC_HELP["brightness_dispersion"])
    st.caption(COLOR_METRIC_HELP["warmth_score"])

    frame = pd.DataFrame(samples).sort_values("frame_index")
    render_hue_chart(frame)
    render_single_metric_chart(
        frame,
        "主色饱和度趋势",
        "dominant_saturation",
        "S 饱和度（%）",
        [0, 100],
        COLOR_METRIC_HELP["hsv"],
        "#8a8a8a",
        "#1f77ff",
    )
    render_single_metric_chart(
        frame,
        "主色亮度趋势",
        "dominant_value",
        "V 亮度（%）",
        [0, 100],
        COLOR_METRIC_HELP["hsv"],
        "#111111",
        "#f2f2f2",
    )
    render_warmth_chart(frame)
    render_contrast_chart(frame)
    render_dispersion_chart(frame)

    with st.expander("采样数据", expanded=False):
        columns = [
            "timecode",
            "frame_index",
            "timestamp",
            "dominant_color_hex",
            "dominant_hue",
            "dominant_saturation",
            "dominant_value",
            "color_dispersion",
            "brightness_dispersion",
            "contrast_score",
            "warmth_score",
            "dominant_coverage",
        ]
        visible_columns = [column for column in columns if column in frame.columns]
        st.dataframe(
            frame[visible_columns],
            width="stretch",
            hide_index=True,
            column_config={
                "timecode": st.column_config.TextColumn("时间码"),
                "timestamp": st.column_config.NumberColumn("时间（秒）", format="%.3f"),
                "dominant_hue": st.column_config.NumberColumn("H 色相（度）", format="%.2f"),
                "dominant_saturation": st.column_config.NumberColumn("S 饱和度（%）", format="%.2f"),
                "dominant_value": st.column_config.NumberColumn("V 亮度（%）", format="%.2f"),
                "color_dispersion": st.column_config.NumberColumn("色彩离散度（%）", format="%.2f"),
                "brightness_dispersion": st.column_config.NumberColumn("亮度离散度（%）", format="%.2f"),
                "contrast_score": st.column_config.NumberColumn("对比度（%）", format="%.2f"),
                "warmth_score": st.column_config.NumberColumn("冷暖倾向（-100 到 100）", format="%.2f"),
                "dominant_coverage": st.column_config.NumberColumn("主色覆盖率", format="%.3f"),
            },
        )


def render_motion_analysis(module: dict) -> None:
    if not module:
        st.info("当前报告没有运动分析数据。关闭缓存并重新分析可生成运动趋势图。")
        return

    st.caption(_module_status_text(module))
    render_module_errors(module)
    if module.get("status") == "failed":
        return

    data = _module_data(module)
    samples = data.get("samples") or []
    if not samples:
        st.info("当前报告没有运动分析数据。")
        return

    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    metric_cols = st.columns(4)
    metric_cols[0].metric("采样点", summary.get("sample_count", len(samples)))
    metric_cols[1].metric("平均运动量（px）", _format_number(summary.get("average_mean_motion_px")))
    metric_cols[2].metric("峰值 P95 运动量（px）", _format_number(summary.get("peak_p95_motion_px")))
    metric_cols[3].metric("平均运动覆盖（%）", _format_number(summary.get("average_moving_area_percent")))

    detail_cols = st.columns(3)
    detail_cols[0].metric("运动波动度", _format_number(summary.get("motion_variability")))
    detail_cols[1].metric("整体运动等级", _motion_level_label(summary.get("motion_level")))
    detail_cols[2].metric("节奏判断", _motion_rhythm_label(summary.get("rhythm_label")))
    st.caption(MOTION_METRIC_HELP["motion_intensity"])
    st.caption(MOTION_METRIC_HELP["p95_motion"])
    st.caption(MOTION_METRIC_HELP["motion_variability"])
    st.caption(MOTION_METRIC_HELP["moving_area"])

    frame = pd.DataFrame(samples).sort_values("frame_index")
    render_motion_intensity_chart(frame)
    render_motion_area_chart(frame)

    with st.expander("采样数据", expanded=False):
        columns = [
            "timecode",
            "frame_index",
            "timestamp",
            "mean_motion_px",
            "p95_motion_px",
            "moving_area_percent",
        ]
        visible_columns = [column for column in columns if column in frame.columns]
        st.dataframe(
            frame[visible_columns],
            width="stretch",
            hide_index=True,
            column_config={
                "timecode": st.column_config.TextColumn("时间码"),
                "timestamp": st.column_config.NumberColumn("时间（秒）", format="%.3f"),
                "mean_motion_px": st.column_config.NumberColumn("平均运动量（px）", format="%.4f"),
                "p95_motion_px": st.column_config.NumberColumn("P95 运动量（px）", format="%.4f"),
                "moving_area_percent": st.column_config.NumberColumn("运动覆盖面积（%）", format="%.2f"),
            },
        )


def render_metadata_details(video: dict) -> None:
    if not video:
        st.info("当前报告没有视频基础信息。")
        return

    st.subheader("视频基础信息")
    metric_cols = st.columns(4)
    metric_cols[0].metric("分辨率", f"{video.get('width')} x {video.get('height')}")
    metric_cols[1].metric("帧率", video.get("fps"))
    metric_cols[2].metric("时长（秒）", _format_number(video.get("duration")))
    metric_cols[3].metric("总帧数", video.get("frame_count", ""))

    detail_cols = st.columns(2)
    detail_cols[0].metric("编码", video.get("codec") or "未知")
    detail_cols[1].metric("音轨", _audio_stream_text(video.get("audio_stream_exists")))
    if video.get("path"):
        st.caption(f"文件路径：{video.get('path')}")


def render_hue_chart(frame: pd.DataFrame) -> None:
    if "dominant_hue" not in frame.columns:
        return

    st.subheader("主色色相趋势")
    st.caption(COLOR_METRIC_HELP["hsv"])
    tooltips = _chart_tooltips("dominant_hue", "H 色相（度）")
    base = alt.Chart(frame).encode(
        x=alt.X("timestamp:Q", title="时间（秒）"),
        y=alt.Y("dominant_hue:Q", title="H 色相（度）", scale=alt.Scale(domain=[0, 360])),
    )
    line = base.mark_line(color="#56616f", opacity=0.65).encode(tooltip=tooltips)
    points = base.mark_circle(size=52, stroke="#333333", strokeWidth=0.4).encode(
        color=alt.Color(
            "dominant_hue:Q",
            title="色相 H（度）",
            scale=alt.Scale(
                domain=[0, 60, 120, 180, 240, 300, 360],
                range=["#ff3b30", "#ffcc00", "#34c759", "#32ade6", "#007aff", "#af52de", "#ff3b30"],
            ),
            legend=None,
        ),
        tooltip=tooltips,
    )
    render_chart_with_color_axis(
        (line + points).properties(height=280),
        "色相 H（度）",
        [0, 60, 120, 180, 240, 300, 360],
        ["#ff3b30", "#ffcc00", "#34c759", "#32ade6", "#007aff", "#af52de", "#ff3b30"],
        [0, 60, 120, 180, 240, 300, 360],
    )


def render_single_metric_chart(
    frame: pd.DataFrame,
    title: str,
    column: str,
    label: str,
    domain: list[int],
    help_text: str,
    low_color: str,
    high_color: str,
) -> None:
    if column not in frame.columns:
        return

    st.subheader(title)
    if help_text:
        st.caption(help_text)
    tooltips = _chart_tooltips(column, label)
    base = alt.Chart(frame).encode(
        x=alt.X("timestamp:Q", title="时间（秒）"),
        y=alt.Y(f"{column}:Q", title=label, scale=alt.Scale(domain=domain)),
    )
    line = base.mark_line(color="#4c78a8").encode(tooltip=tooltips)
    points = base.mark_circle(size=46, stroke="#333333", strokeWidth=0.35).encode(
        color=alt.Color(
            f"{column}:Q",
            title=label,
            scale=alt.Scale(domain=domain, range=[low_color, high_color]),
            legend=None,
        ),
        tooltip=tooltips,
    )
    render_chart_with_color_axis(
        (line + points).properties(height=280),
        label,
        domain,
        [low_color, high_color],
        [domain[0], (domain[0] + domain[1]) / 2, domain[1]],
    )


def render_dispersion_chart(frame: pd.DataFrame) -> None:
    columns = [column for column in ["color_dispersion", "brightness_dispersion"] if column in frame.columns]
    if not columns:
        return

    st.subheader("离散度趋势")
    st.caption(f"{COLOR_METRIC_HELP['color_dispersion']} {COLOR_METRIC_HELP['brightness_dispersion']}")
    labels = {
        "color_dispersion": "色彩离散度（%）",
        "brightness_dispersion": "亮度离散度（%）",
    }
    chart_frame = frame[["timestamp", "timecode", "frame_index", *columns]].melt(
        id_vars=["timestamp", "timecode", "frame_index"],
        value_vars=columns,
        var_name="metric",
        value_name="value",
    )
    chart_frame["metric_label"] = chart_frame["metric"].map(labels)
    chart = (
        alt.Chart(chart_frame)
        .mark_line(point=True)
        .encode(
            x=alt.X("timestamp:Q", title="时间（秒）"),
            y=alt.Y("value:Q", title="离散度（%）", scale=alt.Scale(domain=[0, 100])),
            color=alt.Color("metric_label:N", title="指标"),
            tooltip=[
                alt.Tooltip("timecode:N", title="时间码"),
                alt.Tooltip("frame_index:Q", title="帧", format=".0f"),
                alt.Tooltip("metric_label:N", title="指标"),
                alt.Tooltip("value:Q", title="数值", format=".2f"),
            ],
        )
        .properties(height=280)
    )
    st.altair_chart(chart, width="stretch")


def render_contrast_chart(frame: pd.DataFrame) -> None:
    if "contrast_score" not in frame.columns:
        return

    st.subheader("对比度趋势")
    st.caption(COLOR_METRIC_HELP["contrast_score"])
    tooltips = _chart_tooltips("contrast_score", "对比度（%）")
    base = alt.Chart(frame).encode(
        x=alt.X("timestamp:Q", title="时间（秒）"),
        y=alt.Y("contrast_score:Q", title="对比度（%）", scale=alt.Scale(domain=[0, 100])),
    )
    line = base.mark_line(color="#4c78a8").encode(tooltip=tooltips)
    points = base.mark_circle(size=46, color="#4c78a8", stroke="#333333", strokeWidth=0.35).encode(
        tooltip=tooltips,
    )
    st.altair_chart((line + points).properties(height=280), width="stretch")


def render_warmth_chart(frame: pd.DataFrame) -> None:
    if "warmth_score" not in frame.columns:
        return

    st.subheader("冷暖倾向趋势")
    st.caption(COLOR_METRIC_HELP["warmth_score"])
    tooltips = _chart_tooltips("warmth_score", "冷暖倾向")
    base = alt.Chart(frame).encode(
        x=alt.X("timestamp:Q", title="时间（秒）"),
        y=alt.Y("warmth_score:Q", title="冷暖倾向（-100 到 100）", scale=alt.Scale(domain=[-100, 100])),
    )
    line = base.mark_line(color="#d95f02").encode(tooltip=tooltips)
    points = base.mark_circle(size=44, stroke="#333333", strokeWidth=0.35).encode(
        color=alt.Color(
            "warmth_score:Q",
            title="冷暖倾向",
            scale=alt.Scale(domain=[-100, 0, 100], range=["#2f80ed", "#d9d9d9", "#f2994a"]),
            legend=None,
        ),
        tooltip=tooltips,
    )
    zero_rule = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color="#555555", strokeDash=[4, 4]).encode(y="y:Q")
    render_chart_with_color_axis(
        (line + points + zero_rule).properties(height=280),
        "冷暖倾向",
        [-100, 0, 100],
        ["#2f80ed", "#d9d9d9", "#f2994a"],
        [-100, -50, 0, 50, 100],
    )


def render_motion_intensity_chart(frame: pd.DataFrame) -> None:
    columns = [column for column in ["mean_motion_px", "p95_motion_px"] if column in frame.columns]
    if not columns:
        return

    st.subheader("运动强度趋势")
    st.caption(MOTION_METRIC_HELP["motion_intensity"])
    labels = {
        "mean_motion_px": "平均运动量（px）",
        "p95_motion_px": "P95 运动量（px）",
    }
    chart_frame = frame[["timestamp", "timecode", "frame_index", *columns]].melt(
        id_vars=["timestamp", "timecode", "frame_index"],
        value_vars=columns,
        var_name="metric",
        value_name="value",
    )
    chart_frame["metric_label"] = chart_frame["metric"].map(labels)
    chart = (
        alt.Chart(chart_frame)
        .mark_line(point=True)
        .encode(
            x=alt.X("timestamp:Q", title="时间（秒）"),
            y=alt.Y("value:Q", title="运动量（px）"),
            color=alt.Color("metric_label:N", title="指标"),
            tooltip=[
                alt.Tooltip("timecode:N", title="时间码"),
                alt.Tooltip("frame_index:Q", title="帧", format=".0f"),
                alt.Tooltip("metric_label:N", title="指标"),
                alt.Tooltip("value:Q", title="数值", format=".4f"),
            ],
        )
        .properties(height=280)
    )
    st.altair_chart(chart, width="stretch")


def render_motion_area_chart(frame: pd.DataFrame) -> None:
    if "moving_area_percent" not in frame.columns:
        return

    st.subheader("运动覆盖面积趋势")
    st.caption(MOTION_METRIC_HELP["moving_area"])
    tooltips = _motion_chart_tooltips("moving_area_percent", "运动覆盖面积（%）")
    base = alt.Chart(frame).encode(
        x=alt.X("timestamp:Q", title="时间（秒）"),
        y=alt.Y("moving_area_percent:Q", title="运动覆盖面积（%）", scale=alt.Scale(domain=[0, 100])),
    )
    area = base.mark_area(color="#4c78a8", opacity=0.28).encode(tooltip=tooltips)
    line = base.mark_line(color="#4c78a8").encode(tooltip=tooltips)
    points = base.mark_circle(size=42, color="#4c78a8", stroke="#333333", strokeWidth=0.35).encode(
        tooltip=tooltips,
    )
    st.altair_chart((area + line + points).properties(height=280), width="stretch")


def render_chart_with_color_axis(
    chart: alt.Chart,
    title: str,
    color_domain: list[float],
    color_range: list[str],
    axis_values: list[float],
) -> None:
    chart_col, axis_col = st.columns([1, 0.075], gap="small")
    with chart_col:
        st.altair_chart(chart, width="stretch")
    with axis_col:
        st.markdown(
            continuous_color_axis_html(title, color_domain, color_range, axis_values),
            unsafe_allow_html=True,
        )


def continuous_color_axis_html(
    title: str,
    color_domain: list[float],
    color_range: list[str],
    axis_values: list[float],
) -> str:
    start = min(color_domain)
    end = max(color_domain)
    gradient_stops = ", ".join(
        f"{color} {((value - start) / (end - start)) * 100:.2f}%"
        for value, color in zip(color_domain, color_range)
    )

    tick_html = []
    for value in axis_values:
        top = 100 - ((value - start) / (end - start)) * 100
        tick_html.append(
            f'<div class="color-axis-tick" style="top:{top:.2f}%;">'
            f'<span class="color-axis-line"></span><span class="color-axis-label">{value:g}</span></div>'
        )

    return (
        '<div class="color-axis-wrapper">'
        '<div class="color-axis-track-row">'
        f'<div class="color-axis-track" style="background:linear-gradient(to top, {gradient_stops});"></div>'
        '<div class="color-axis-ticks">'
        f'{"".join(tick_html)}'
        "</div>"
        "</div>"
        f'<div class="color-axis-title">{escape(title)}</div>'
        "</div>"
        "<style>"
        ".color-axis-wrapper{height:330px;min-width:74px;padding-top:0;box-sizing:border-box;}"
        ".color-axis-track-row{position:relative;height:205px;width:74px;overflow:visible;}"
        ".color-axis-track{position:absolute;left:0;top:0;width:32px;height:205px;border-radius:2px;}"
        ".color-axis-ticks{position:absolute;left:38px;top:0;height:205px;width:36px;overflow:visible;}"
        ".color-axis-tick{position:absolute;left:0;display:flex;align-items:center;gap:4px;transform:translateY(-50%);}"
        ".color-axis-line{width:5px;height:1px;background:rgba(240,242,246,.55);display:inline-block;}"
        ".color-axis-label{color:#f0f2f6;font-size:13px;line-height:1;white-space:nowrap;}"
        ".color-axis-title{width:74px;margin-top:8px;padding-bottom:18px;color:#f0f2f6;font-size:13px;font-weight:700;line-height:1.2;text-align:center;}"
        "</style>"
    )


def _chart_tooltips(column: str, label: str) -> list:
    return [
        alt.Tooltip("timecode:N", title="时间码"),
        alt.Tooltip("frame_index:Q", title="帧", format=".0f"),
        alt.Tooltip(f"{column}:Q", title=label, format=".2f"),
    ]


def _motion_chart_tooltips(column: str, label: str) -> list:
    return [
        alt.Tooltip("timecode:N", title="时间码"),
        alt.Tooltip("frame_index:Q", title="帧", format=".0f"),
        alt.Tooltip(f"{column}:Q", title=label, format=".2f"),
    ]


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
        width="stretch",
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
            st.info("当前筛选结果没有截图记录。请重新分析生成截图。")
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
            st.info("该事件没有截图记录。请重新分析生成截图。")
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
        col.image(str(path), caption=label_map.get(label, label), width="stretch")


def log_debug_info(events: list[dict], report_dir: Path) -> None:
    with_screenshot_fields = [event for event in events if event.get("screenshots")]
    resolved_files = []
    missing_files = []
    for event in with_screenshot_fields:
        for label, screenshot_path in event.get("screenshots", {}).items():
            resolved = _resolve_screenshot_path(report_dir, screenshot_path)
            item = {
                "event": event_type_label(event.get("type", "")),
                "frames": _frame_range(event),
                "screenshot": label,
                "path": str(resolved),
            }
            if resolved.exists():
                resolved_files.append(item)
            else:
                missing_files.append(item)

    LOGGER.info(
        "report_debug report_dir=%s filtered_events=%s events_with_screenshots=%s resolved_screenshots=%s missing_screenshots=%s",
        report_dir.resolve(),
        len(events),
        len(with_screenshot_fields),
        len(resolved_files),
        len(missing_files),
    )
    if missing_files:
        LOGGER.warning("missing_screenshot_examples=%s", missing_files[:20])


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


def _motion_level_label(value) -> str:
    return MOTION_LEVEL_LABELS.get(value, str(value))


def _motion_rhythm_label(value) -> str:
    return MOTION_RHYTHM_LABELS.get(value, str(value))


def _audio_stream_text(value) -> str:
    if value is True:
        return "有"
    if value is False:
        return "无"
    return "未知"


def choose_video_file() -> str:
    from tkinter import Tk, filedialog

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
    from tkinter import Tk, filedialog

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
