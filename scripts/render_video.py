from __future__ import annotations

import argparse
import json
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any


DEFAULT_FFMPEG = Path(sys.executable).parent / "Library" / "bin" / "ffmpeg.exe"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Burn ASS subtitles into a video with ffmpeg.")
    parser.add_argument("input", type=Path, help="Path to input video.")
    parser.add_argument("--ass", required=True, type=Path, help="Path to ASS subtitle file.")
    parser.add_argument("--json", type=Path, help="Translated .zh.json file for drawtext fallback.")
    parser.add_argument(
        "--mode",
        choices=["chinese", "bilingual"],
        default="chinese",
        help="Subtitle burn-in mode for drawtext fallback. Default: chinese",
    )
    parser.add_argument(
        "--subtitle-position",
        choices=["upper", "center", "lower"],
        default="center",
        help="Target-language subtitle vertical position. Default: center",
    )
    parser.add_argument(
        "--subtitle-y",
        type=float,
        help="Exact target-language subtitle vertical fraction from 0.05 to 0.90. Overrides --subtitle-position.",
    )
    parser.add_argument(
        "--source-y",
        type=float,
        help="Exact source-language subtitle vertical fraction from 0.05 to 0.90 for bilingual mode.",
    )
    parser.add_argument("--output", type=Path, help="Output video path. Default: output/<stem>_bilingual_subs.mp4")
    parser.add_argument("--ffmpeg", default=str(DEFAULT_FFMPEG), help="Path to ffmpeg executable.")
    parser.add_argument("--crf", default="18", help="libx264 CRF quality. Default: 18")
    parser.add_argument("--preset", default="veryfast", help="libx264 preset. Default: veryfast")
    parser.add_argument("--watermark", help="Optional floating watermark text. Use an empty value to disable.")
    parser.add_argument("--watermark-opacity", type=float, default=0.14, help="Watermark opacity. Default: 0.14")
    parser.add_argument("--watermark-fontsize", type=int, default=22, help="Watermark font size. Default: 22")
    return parser.parse_args()


def filter_path(path: Path) -> str:
    try:
        rel = path.resolve().relative_to(Path.cwd().resolve())
        value = rel.as_posix()
    except ValueError:
        value = path.resolve().as_posix()
    return value.replace(":", "\\:")


def has_filter(ffmpeg: str, name: str) -> bool:
    completed = subprocess.run([ffmpeg, "-hide_banner", "-filters"], check=False, capture_output=True, text=True)
    return completed.returncode == 0 and f" {name} " in completed.stdout


def drawtext_escape(path: Path) -> str:
    return path.resolve().as_posix().replace(":", "\\:")


def load_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    segments = payload.get("segments")
    if not isinstance(segments, list):
        raise ValueError(f"Invalid translated transcript JSON: {path}")
    return payload


def target_language(payload: dict[str, Any]) -> str:
    return str(payload.get("metadata", {}).get("target_language", "zh"))


def target_text_key(language: str) -> str:
    return "en_text" if language == "en" else "zh_text"


def write_text_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip(), encoding="utf-8")


def wrap_source(text: str) -> str:
    return "\n".join(textwrap.wrap(text.strip(), width=30, break_long_words=False, break_on_hyphens=False))


def wrap_chinese(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return ""
    width = 13
    no_break_before = set("，。！？；：、,.!?;:%）)]》」』”’")
    lines: list[str] = []
    current = ""
    for char in stripped:
        if len(current) >= width and char not in no_break_before:
            lines.append(current)
            current = char
        else:
            current += char
    if current:
        lines.append(current)
    return "\n".join(lines)


def wrap_target(text: str, language: str) -> str:
    if language == "en":
        return wrap_source(text)
    return wrap_chinese(text)


def subtitle_y_expr(position: str, exact_y: float | None = None) -> str:
    if exact_y is not None:
        clamped = min(0.90, max(0.05, exact_y))
        return f"(h-text_h)*{clamped:.3f}"
    if position == "upper":
        return "(h-text_h)*0.38"
    if position == "lower":
        return "(h-text_h)*0.72"
    return "(h-text_h)*0.58"


def build_drawtext_script(
    json_path: Path,
    work_dir: Path,
    mode: str,
    subtitle_position: str = "center",
    subtitle_y: float | None = None,
    source_y: float | None = None,
    watermark: str | None = None,
    watermark_opacity: float = 0.14,
    watermark_fontsize: int = 22,
) -> Path:
    source_font = Path("C:/Windows/Fonts/arial.ttf")
    chinese_font = Path("C:/Windows/Fonts/msyh.ttc")
    payload = load_payload(json_path)
    segments = payload["segments"]
    language = target_language(payload)
    field_name = target_text_key(language)
    text_dir = work_dir / json_path.stem.replace(".zh", "")
    zh_y = subtitle_y_expr(subtitle_position, subtitle_y)
    src_y = subtitle_y_expr("upper", source_y if source_y is not None else 0.34)
    filters: list[str] = []

    for segment in segments:
        index = int(segment["index"])
        start = float(segment["start"])
        end = float(segment["end"])
        target_file = text_dir / f"{index:05}_{language}.txt"
        write_text_file(target_file, wrap_target(segment.get(field_name, ""), language))
        enable = f"gte(t\\,{start:.3f})*lt(t\\,{end:.3f})"
        if mode == "bilingual":
            src_file = text_dir / f"{index:05}_src.txt"
            write_text_file(src_file, wrap_source(segment.get("source_text", "")))
            filters.append(
                "drawtext="
                f"fontfile='{drawtext_escape(source_font)}':"
                f"textfile='{drawtext_escape(src_file)}':"
                "expansion=none:"
                "fontsize=22:fontcolor=white:"
                "borderw=2:bordercolor=black:"
                "line_spacing=-10:"
                f"x=(w-text_w)/2:y={src_y}:"
                f"enable='{enable}'"
            )
        filters.append(
            "drawtext="
            f"fontfile='{drawtext_escape(chinese_font)}':"
            f"textfile='{drawtext_escape(target_file)}':"
            "expansion=none:"
            "fontsize=30:fontcolor=yellow:"
            "borderw=2:bordercolor=black:"
            "line_spacing=-15:"
            f"x=(w-text_w)/2:y={zh_y}:"
            f"enable='{enable}'"
        )

    if watermark:
        watermark_file = work_dir / "watermark.txt"
        write_text_file(watermark_file, watermark)
        filters.append(
            "drawtext="
            f"fontfile='{drawtext_escape(chinese_font)}':"
            f"textfile='{drawtext_escape(watermark_file)}':"
            "expansion=none:"
            f"fontsize={watermark_fontsize}:fontcolor=white:"
            f"alpha={watermark_opacity:.3f}:"
            "borderw=1:bordercolor=black@0.12:"
            "x=(w-text_w)*(0.08+0.84*(0.5+0.5*sin(t*0.17))):"
            "y=(h-text_h)*(0.12+0.72*(0.5+0.5*sin(t*0.23+1.7)))"
        )

    script_path = work_dir / f"{json_path.stem}.drawtext.filter"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(",".join(filters), encoding="utf-8")
    return script_path


def main() -> int:
    args = parse_args()
    input_path = args.input.expanduser().resolve()
    ass_path = args.ass.expanduser().resolve()
    output_path = args.output or Path("output") / f"{input_path.stem}_bilingual_subs.mp4"

    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        return 2
    if not ass_path.exists():
        print(f"ASS file not found: {ass_path}", file=sys.stderr)
        return 2

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if args.json:
        json_path = args.json.expanduser().resolve()
        if not json_path.exists():
            print(f"Translated JSON file not found: {json_path}", file=sys.stderr)
            return 2
        script_path = build_drawtext_script(
            json_path,
            output_path.parent / "_drawtext",
            args.mode,
            subtitle_position=args.subtitle_position,
            subtitle_y=args.subtitle_y,
            source_y=args.source_y,
            watermark=args.watermark,
            watermark_opacity=args.watermark_opacity,
            watermark_fontsize=args.watermark_fontsize,
        )
        filter_args = ["-filter_script:v", str(script_path)]
        print("Using drawtext subtitle burn-in.")
    elif has_filter(args.ffmpeg, "subtitles"):
        filter_args = ["-vf", f"subtitles=filename='{filter_path(ass_path)}'"]
    else:
        print("ffmpeg has no subtitles filter. Pass --json for drawtext fallback.", file=sys.stderr)
        return 2

    command = [args.ffmpeg, "-y", "-i", str(input_path), *filter_args, "-c:v", "libx264", "-crf", args.crf, "-preset", args.preset, "-c:a", "copy", str(output_path)]
    print("Running ffmpeg subtitle burn-in")
    completed = subprocess.run(command, check=False)
    if completed.returncode != 0:
        return completed.returncode
    print(f"Wrote: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
