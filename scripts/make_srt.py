from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build bilingual SRT and styled ASS subtitle files.")
    parser.add_argument("input", type=Path, help="Path to a translated .zh.json file.")
    parser.add_argument("--output-srt", type=Path, help="Output SRT path. Default: transcript/<stem>.bilingual.srt")
    parser.add_argument("--output-ass", type=Path, help="Output ASS path. Default: transcript/<stem>.bilingual.ass")
    return parser.parse_args()


def output_stem(input_path: Path) -> Path:
    name = input_path.name
    for suffix in (".zh.json", ".en.json"):
        if name.endswith(suffix):
            return input_path.with_name(name[: -len(suffix)])
    return input_path.with_suffix("")


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


def srt_timestamp(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def ass_timestamp(seconds: float) -> str:
    centiseconds = round(seconds * 100)
    hours, remainder = divmod(centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    secs, centis = divmod(remainder, 100)
    return f"{hours}:{minutes:02}:{secs:02}.{centis:02}"


def ass_escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("{", "\\{")
        .replace("}", "\\}")
        .replace("\n", "\\N")
        .strip()
    )


def write_srt(path: Path, segments: list[dict[str, Any]], language: str) -> None:
    blocks: list[str] = []
    field_name = target_text_key(language)
    for segment in segments:
        source_text = segment.get("source_text", "").strip()
        target_text = segment.get(field_name, "").strip()
        lines = [
            str(segment["index"]),
            f"{srt_timestamp(segment['start'])} --> {srt_timestamp(segment['end'])}",
            source_text,
            target_text,
        ]
        blocks.append("\n".join(line for line in lines if line))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


def write_ass(path: Path, segments: list[dict[str, Any]], language: str) -> None:
    header = """[Script Info]
ScriptType: v4.00+
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Source,Arial,32,&H00FFFFFF,&H00FFFFFF,&H00111111,&H90000000,0,0,0,0,100,100,0,0,1,2,0,8,56,56,120,1
Style: Target,Microsoft YaHei,44,&H0000D7FF,&H0000D7FF,&H00111111,&H90000000,1,0,0,0,100,100,0,0,1,2.4,0,2,56,56,52,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: list[str] = []
    field_name = target_text_key(language)
    for segment in segments:
        start = ass_timestamp(segment["start"])
        end = ass_timestamp(segment["end"])
        source_text = ass_escape(segment.get("source_text", ""))
        target_text = ass_escape(segment.get(field_name, ""))
        if source_text:
            events.append(f"Dialogue: 0,{start},{end},Source,,0,0,0,,{source_text}")
        if target_text:
            events.append(f"Dialogue: 1,{start},{end},Target,,0,0,0,,{target_text}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + "\n".join(events) + "\n", encoding="utf-8-sig")


def main() -> int:
    args = parse_args()
    input_path = args.input.expanduser().resolve()
    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        return 2

    payload = load_payload(input_path)
    segments = payload["segments"]
    language = target_language(payload)
    stem = output_stem(input_path)
    srt_path = args.output_srt or stem.with_suffix(".bilingual.srt")
    ass_path = args.output_ass or stem.with_suffix(".bilingual.ass")
    write_srt(srt_path, segments, language)
    write_ass(ass_path, segments, language)
    print(f"Wrote: {srt_path}")
    print(f"Wrote: {ass_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
