from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


DEFAULT_FFMPEG = Path(sys.executable).parent / "Library" / "bin" / "ffmpeg.exe"
DEFAULT_FFPROBE = Path(sys.executable).parent / "Library" / "bin" / "ffprobe.exe"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean a phone screen recording by cropping fixed top/bottom UI and padding back without distortion.")
    parser.add_argument("input", type=Path, help="Path to source screen recording.")
    parser.add_argument("--output", type=Path, help="Output path. Default: input/<stem>_clean.mp4")
    parser.add_argument("--top", type=int, default=80, help="Pixels to crop from top. Default: 80")
    parser.add_argument("--bottom", type=int, default=140, help="Pixels to crop from bottom. Default: 140")
    parser.add_argument("--pad-color", default="white", help="Padding color. Default: white")
    parser.add_argument("--ffmpeg", default=str(DEFAULT_FFMPEG), help="Path to ffmpeg executable.")
    parser.add_argument("--ffprobe", default=str(DEFAULT_FFPROBE), help="Path to ffprobe executable.")
    return parser.parse_args()


def video_size(path: Path, ffprobe: str) -> tuple[int, int]:
    command = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "json",
        str(path),
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr)
    payload = json.loads(completed.stdout)
    stream = payload["streams"][0]
    return int(stream["width"]), int(stream["height"])


def main() -> int:
    args = parse_args()
    input_path = args.input.expanduser().resolve()
    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        return 2

    width, height = video_size(input_path, args.ffprobe)
    crop_height = height - args.top - args.bottom
    if crop_height <= 0:
        print("Invalid crop: top + bottom must be smaller than video height.", file=sys.stderr)
        return 2

    output_path = args.output or input_path.with_name(f"{input_path.stem}_clean.mp4")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    video_filter = f"crop={width}:{crop_height}:0:{args.top},pad={width}:{height}:0:{args.top}:color={args.pad_color}"
    command = [
        args.ffmpeg,
        "-y",
        "-i",
        str(input_path),
        "-vf",
        video_filter,
        "-c:v",
        "libx264",
        "-crf",
        "18",
        "-preset",
        "veryfast",
        "-c:a",
        "copy",
        str(output_path),
    ]
    print(f"Cleaning recording: crop top={args.top}px bottom={args.bottom}px")
    completed = subprocess.run(command, check=False)
    if completed.returncode != 0:
        return completed.returncode
    print(f"Wrote: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
