from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .scanner import scan_video


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="framesentry", description="FrameSentry 本地视频基础自审工具。")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan", help="扫描本地视频文件。")
    scan.add_argument("input", help="输入视频路径，例如 input.mp4 或 input.mov。")
    scan.add_argument("--output", default="output/report", help="报告输出目录。")
    scan.add_argument("--sample-scale", type=int, default=480, help="逐帧分析缩略图目标尺寸。")
    scan.add_argument("--max-outlier-frames", type=int, default=2, help="瞬时异常片段允许的最大持续帧数。")
    scan.add_argument("--fps-normal", default="25,30,50,60", help="逗号分隔的常见交付帧率。")
    scan.add_argument("--save-screenshots", action="store_true", help="保存异常前/中/后截图。")
    scan.add_argument("--html", action="store_true", help="生成 HTML 报告。")
    scan.add_argument("--json", action="store_true", help="生成 JSON 报告。")
    return parser


def scan(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    output_dir = Path(args.output)

    write_json = args.json or not args.html
    write_html = args.html or not args.json

    report = scan_video(
        input_path,
        output_dir,
        sample_scale=args.sample_scale,
        max_outlier_frames=args.max_outlier_frames,
        fps_normal=args.fps_normal,
        save_screenshots=args.save_screenshots,
        write_json=write_json,
        write_html=write_html,
    )

    print(f"已扫描：{input_path}")
    print(f"事件数量：{len(report['events'])}")
    print(f"报告目录：{output_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "scan":
        return scan(args)
    parser.error(f"Unknown command: {args.command}")
    return 2
