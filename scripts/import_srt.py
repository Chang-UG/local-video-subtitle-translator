from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


TIMESTAMP_RE = re.compile(
    r"(?P<start>\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(?P<end>\d{2}:\d{2}:\d{2}[,.]\d{3})"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert an external SRT file into transcript segments JSON.")
    parser.add_argument("input", type=Path, help="Path to source .srt file.")
    parser.add_argument("--output-json", required=True, type=Path, help="Output .segments.json path.")
    parser.add_argument("--language", default="auto", help="Source subtitle language hint.")
    parser.add_argument("--media", type=Path, help="Optional source media path for metadata.")
    return parser.parse_args()


def timestamp_seconds(value: str) -> float:
    hours, minutes, rest = value.replace(",", ".").split(":")
    seconds, millis = rest.split(".")
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000


def read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "gb18030"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def parse_srt(text: str) -> list[dict]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n{2,}", normalized.strip())
    segments: list[dict] = []

    for block in blocks:
        lines = [line.strip("\ufeff ") for line in block.split("\n") if line.strip()]
        if not lines:
            continue

        time_index = next((index for index, line in enumerate(lines) if TIMESTAMP_RE.search(line)), None)
        if time_index is None:
            continue

        match = TIMESTAMP_RE.search(lines[time_index])
        if not match:
            continue

        text_lines = lines[time_index + 1 :]
        subtitle_text = " ".join(text_lines).strip()
        if not subtitle_text:
            continue

        segments.append(
            {
                "index": len(segments) + 1,
                "start": timestamp_seconds(match.group("start")),
                "end": timestamp_seconds(match.group("end")),
                "text": subtitle_text,
            }
        )

    if not segments:
        raise ValueError("No valid SRT subtitle blocks found.")
    return segments


def main() -> int:
    args = parse_args()
    input_path = args.input.expanduser().resolve()
    output_path = args.output_json.expanduser().resolve()
    if not input_path.exists():
        print(f"SRT file not found: {input_path}", file=sys.stderr)
        return 2

    try:
        segments = parse_srt(read_text(input_path))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    payload = {
        "metadata": {
            "source": "external_srt",
            "source_srt": str(input_path),
            "media": str(args.media.expanduser().resolve()) if args.media else None,
            "language": args.language,
        },
        "segments": segments,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Imported external SRT: {input_path}")
    print(f"Wrote: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
