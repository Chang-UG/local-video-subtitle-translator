from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from faster_whisper import WhisperModel


SUPPORTED_LANGUAGES = {
    "auto",
    "ar",
    "de",
    "en",
    "es",
    "fr",
    "hi",
    "it",
    "ja",
    "ko",
    "nl",
    "pt",
    "ru",
    "zh",
}


@dataclass
class TranscriptSegment:
    index: int
    start: float
    end: float
    text: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Transcribe an audio/video file with faster-whisper and export TXT, SRT, and JSON."
    )
    parser.add_argument("input", type=Path, help="Path to an audio or video file.")
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=Path("transcript"),
        help="Directory for transcript files. Default: transcript",
    )
    parser.add_argument(
        "--language",
        choices=sorted(SUPPORTED_LANGUAGES),
        default="auto",
        help="Input language hint. Use auto for detection. Default: auto",
    )
    parser.add_argument(
        "--model",
        default="small",
        help="Whisper model size or local model path. Good starters: tiny, base, small, medium, large-v3.",
    )
    parser.add_argument(
        "--device",
        default="cpu",
        choices=["auto", "cpu", "cuda"],
        help="Inference device. Default: cpu",
    )
    parser.add_argument(
        "--compute-type",
        default="int8",
        help="faster-whisper compute type. CPU starter: int8. GPU starter: float16. Default: int8",
    )
    parser.add_argument(
        "--beam-size",
        type=int,
        default=5,
        help="Beam size for decoding. Default: 5",
    )
    return parser.parse_args()


def format_timestamp(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def write_txt(path: Path, segments: Iterable[TranscriptSegment]) -> None:
    text = "\n".join(segment.text.strip() for segment in segments if segment.text.strip())
    path.write_text(text + "\n", encoding="utf-8")


def write_srt(path: Path, segments: Iterable[TranscriptSegment]) -> None:
    blocks: list[str] = []
    for segment in segments:
        blocks.append(
            "\n".join(
                [
                    str(segment.index),
                    f"{format_timestamp(segment.start)} --> {format_timestamp(segment.end)}",
                    segment.text.strip(),
                ]
            )
        )
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


def write_json(path: Path, metadata: dict, segments: list[TranscriptSegment]) -> None:
    payload = {
        "metadata": metadata,
        "segments": [asdict(segment) for segment in segments],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_output_stem(input_path: Path, output_dir: Path) -> Path:
    return output_dir / input_path.stem


def main() -> int:
    args = parse_args()
    input_path = args.input.expanduser().resolve()

    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        return 2

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_stem = build_output_stem(input_path, args.output_dir)
    language = None if args.language == "auto" else args.language
    compute_type = args.compute_type

    print(f"Loading faster-whisper model: {args.model} ({args.device}, {compute_type})")
    model = WhisperModel(args.model, device=args.device, compute_type=compute_type)

    print(f"Transcribing: {input_path}")
    raw_segments, info = model.transcribe(
        str(input_path),
        language=language,
        beam_size=args.beam_size,
        vad_filter=True,
    )

    segments = [
        TranscriptSegment(index=index, start=segment.start, end=segment.end, text=segment.text.strip())
        for index, segment in enumerate(raw_segments, start=1)
    ]

    metadata = {
        "input": str(input_path),
        "model": args.model,
        "language": info.language,
        "language_probability": info.language_probability,
        "duration": info.duration,
    }

    write_txt(output_stem.with_suffix(".txt"), segments)
    write_srt(output_stem.with_suffix(".srt"), segments)
    write_json(output_stem.with_suffix(".segments.json"), metadata, segments)

    print(f"Detected language: {info.language} ({info.language_probability:.2%})")
    print(f"Wrote: {output_stem.with_suffix('.txt')}")
    print(f"Wrote: {output_stem.with_suffix('.srt')}")
    print(f"Wrote: {output_stem.with_suffix('.segments.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
