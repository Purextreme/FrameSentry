from __future__ import annotations

from html import escape
from pathlib import Path

from ..presentation import event_type_label, summary_label


def write_html_report(report: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render(report), encoding="utf-8")


def _render(report: dict) -> str:
    video = report["video"]
    summary = report["summary"]
    events = report["events"]
    rows = "\n".join(_event_row(event) for event in events) or "<tr><td colspan=\"8\">未发现疑似异常事件。</td></tr>"
    summary_items = "\n".join(f"<li>{escape(summary_label(key))}: {value}</li>" for key, value in summary.items())

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>FrameSentry 检测报告</title>
  <style>
    body {{ font-family: Arial, "Microsoft YaHei", sans-serif; margin: 32px; color: #202124; background: #f7f8fa; }}
    main {{ max-width: 1200px; margin: 0 auto; }}
    section {{ margin: 24px 0; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid #e5e7eb; text-align: left; vertical-align: top; }}
    th {{ background: #eef2f7; }}
    code {{ background: #eef2f7; padding: 2px 4px; border-radius: 4px; }}
    .shot {{ max-width: 180px; margin: 4px 6px 4px 0; border: 1px solid #d1d5db; }}
    .severity-warning {{ color: #9a3412; font-weight: 600; }}
    .severity-info {{ color: #1d4ed8; font-weight: 600; }}
  </style>
</head>
<body>
<main>
  <h1>FrameSentry 检测报告</h1>

  <section>
    <h2>视频基础信息</h2>
    <table>
      <tr><th>路径</th><td><code>{escape(str(video.get("path")))}</code></td></tr>
      <tr><th>分辨率</th><td>{video.get("width")} x {video.get("height")}</td></tr>
      <tr><th>帧率</th><td>{video.get("fps")}</td></tr>
      <tr><th>时长</th><td>{video.get("duration")}</td></tr>
      <tr><th>帧数</th><td>{video.get("frame_count")}</td></tr>
      <tr><th>编码</th><td>{escape(str(video.get("codec")))}</td></tr>
      <tr><th>音频轨</th><td>{video.get("audio_stream_exists")}</td></tr>
    </table>
  </section>

  <section>
    <h2>异常摘要</h2>
    <ul>{summary_items}</ul>
  </section>

  <section>
    <h2>异常列表</h2>
    <table>
      <thead>
        <tr>
          <th>类型</th>
          <th>级别</th>
          <th>开始帧</th>
          <th>结束帧</th>
          <th>时间码</th>
          <th>持续帧数</th>
          <th>置信度</th>
          <th>原因 / 截图</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </section>
</main>
</body>
</html>
"""


def _event_row(event: dict) -> str:
    severity = escape(str(event.get("severity", "")))
    reason = escape(str(event.get("reason") or event.get("message") or ""))
    screenshots = _screenshots_html(event.get("screenshots", {}))
    return f"""<tr>
  <td>{escape(event_type_label(str(event.get("type", ""))))}</td>
  <td class="severity-{severity}">{severity}</td>
  <td>{event.get("start_frame", "")}</td>
  <td>{event.get("end_frame", "")}</td>
  <td>{escape(str(event.get("start_timecode", "")))}</td>
  <td>{event.get("duration_frames", "")}</td>
  <td>{event.get("confidence", "")}</td>
  <td>{reason}{screenshots}</td>
</tr>"""


def _screenshots_html(screenshots: dict) -> str:
    if not screenshots:
        return ""
    images = "".join(
        f'<img class="shot" src="{escape(path)}" alt="{escape(label)}">'
        for label, path in screenshots.items()
    )
    return f"<div>{images}</div>"
