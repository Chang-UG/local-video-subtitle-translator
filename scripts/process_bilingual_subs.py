from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = PROJECT_ROOT / "models" / "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf"
DEFAULT_FFPROBE = Path(sys.executable).parent / "Library" / "bin" / "ffprobe.exe"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="One-step pipeline: video -> transcript/SRT -> local translation -> subtitle files -> burned-in video."
    )
    parser.add_argument("input", type=Path, help="Path to source video.")
    parser.add_argument(
        "--language",
        default="auto",
        choices=["auto", "ar", "de", "en", "es", "fr", "hi", "it", "ja", "ko", "nl", "pt", "ru", "zh"],
        help="Source language hint.",
    )
    parser.add_argument("--translation-model", type=Path, default=DEFAULT_MODEL, help="Local GGUF model path.")
    parser.add_argument(
        "--translation-gpu-layers",
        default="0",
        help="llama.cpp GPU offload layers for translation. Use auto to enable GPU offload. Default: 0",
    )
    parser.add_argument(
        "--translation-batch-size",
        type=int,
        default=4,
        help="Segments per local translation request. Default: 4",
    )
    parser.add_argument(
        "--target-language",
        choices=["zh", "en"],
        default="zh",
        help="Translation target language. Use zh for Chinese subtitles or en for English subtitles. Default: zh",
    )
    parser.add_argument("--force", action="store_true", help="Rebuild all intermediate files.")
    parser.add_argument("--skip-render", action="store_true", help="Build subtitle files but do not render video.")
    parser.add_argument(
        "--subtitle-source",
        choices=["audio", "external-srt"],
        default="audio",
        help="Source for the original-language transcript. Default: audio",
    )
    parser.add_argument("--source-srt", type=Path, help="External source-language SRT file used with --subtitle-source external-srt.")
    parser.add_argument("--clean-recording", action="store_true", help="Crop fixed phone UI before processing.")
    parser.add_argument("--clean-top", type=int, default=80, help="Pixels to crop from top when --clean-recording is used.")
    parser.add_argument("--clean-bottom", type=int, default=140, help="Pixels to crop from bottom when --clean-recording is used.")
    parser.add_argument("--watermark", default="上北下南的东", help="Floating watermark text. Use an empty value to disable.")
    parser.add_argument("--watermark-opacity", type=float, default=0.14, help="Watermark opacity. Default: 0.14")
    parser.add_argument("--watermark-fontsize", type=int, default=22, help="Watermark font size. Default: 22")
    parser.add_argument(
        "--subtitle-mode",
        choices=["chinese", "bilingual"],
        default="chinese",
        help="Burn-in subtitle mode. Default: chinese",
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
    parser.add_argument("--ffprobe", default=str(DEFAULT_FFPROBE), help="Path to ffprobe executable.")
    return parser.parse_args()


def run(command: list[str]) -> None:
    print(" ".join(command))
    completed = subprocess.run(command, check=False, cwd=PROJECT_ROOT)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def subtitle_streams(input_path: Path, ffprobe: str) -> list[dict[str, Any]]:
    command = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "s",
        "-show_entries",
        "stream=index,codec_name:stream_tags=language,title",
        "-of",
        "json",
        str(input_path),
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        return []
    payload = json.loads(completed.stdout or "{}")
    streams = payload.get("streams", [])
    return streams if isinstance(streams, list) else []


def transcript_matches_external_srt(transcript_json: Path, source_srt: Path) -> bool:
    if not transcript_json.exists():
        return False
    try:
        payload = json.loads(transcript_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    metadata = payload.get("metadata", {})
    return (
        metadata.get("source") == "external_srt"
        and Path(str(metadata.get("source_srt", ""))).resolve() == source_srt.resolve()
    )


def main() -> int:
    args = parse_args()
    input_path = args.input.expanduser().resolve()
    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        return 2

    if args.clean_recording:
        clean_path = PROJECT_ROOT / "input" / f"{input_path.stem}_clean.mp4"
        if args.force or not clean_path.exists():
            run(
                [
                    sys.executable,
                    "scripts/clean_recording.py",
                    str(input_path),
                    "--output",
                    str(clean_path),
                    "--top",
                    str(args.clean_top),
                    "--bottom",
                    str(args.clean_bottom),
                ]
            )
        else:
            print(f"Using existing cleaned recording: {clean_path}")
        input_path = clean_path.resolve()

    stem = input_path.stem
    artifact_dir = PROJECT_ROOT / "output" / stem
    artifact_dir.mkdir(parents=True, exist_ok=True)
    transcript_json = artifact_dir / f"{stem}.segments.json"
    translated_json = artifact_dir / f"{stem}.{args.target_language}.json"
    bilingual_txt = artifact_dir / f"{stem}.bilingual.txt"
    bilingual_srt = artifact_dir / f"{stem}.bilingual.srt"
    bilingual_ass = artifact_dir / f"{stem}.bilingual.ass"
    output_video = artifact_dir / f"{stem}_{args.target_language}_subs.mp4"

    streams = subtitle_streams(input_path, args.ffprobe)
    if streams:
        report = artifact_dir / f"{stem}.subtitle_streams.json"
        report.write_text(json.dumps({"streams": streams}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Detected embedded subtitle streams: {len(streams)}")
        print(f"Wrote subtitle stream report: {report}")
    else:
        print("No embedded subtitle streams detected. Hardcoded visual subtitles are not detectable here.")

    if args.subtitle_source == "external-srt":
        if not args.source_srt:
            print("--source-srt is required when --subtitle-source external-srt", file=sys.stderr)
            return 2
        source_srt = args.source_srt.expanduser().resolve()
        if not source_srt.exists():
            print(f"SRT file not found: {source_srt}", file=sys.stderr)
            return 2
        if args.force or not transcript_matches_external_srt(transcript_json, source_srt):
            run(
                [
                    sys.executable,
                    "scripts/import_srt.py",
                    str(source_srt),
                    "--output-json",
                    str(transcript_json),
                    "--language",
                    args.language,
                    "--media",
                    str(input_path),
                ]
            )
        else:
            print(f"Using existing imported SRT transcript: {transcript_json}")
    elif args.force or not transcript_json.exists():
        command = [sys.executable, "scripts/transcribe.py", str(input_path)]
        command.extend(["--output-dir", str(artifact_dir)])
        if args.language != "auto":
            command.extend(["--language", args.language])
        run(command)
    else:
        print(f"Using existing transcript: {transcript_json}")

    if args.force or not translated_json.exists():
        run(
            [
                sys.executable,
                "scripts/translate.py",
                str(transcript_json),
                "--model",
                str(args.translation_model),
                "--gpu-layers",
                args.translation_gpu_layers,
                "--batch-size",
                str(args.translation_batch_size),
                "--target-language",
                args.target_language,
                "--output-json",
                str(translated_json),
                "--output-txt",
                str(bilingual_txt),
            ]
        )
    else:
        print(f"Using existing translation: {translated_json}")

    if args.force or not bilingual_srt.exists() or not bilingual_ass.exists():
        run(
            [
                sys.executable,
                "scripts/make_srt.py",
                str(translated_json),
                "--output-srt",
                str(bilingual_srt),
                "--output-ass",
                str(bilingual_ass),
            ]
        )
    else:
        print(f"Using existing subtitles: {bilingual_srt}, {bilingual_ass}")

    if not args.skip_render:
        if args.force or not output_video.exists():
            run(
                [
                    sys.executable,
                    "scripts/render_video.py",
                    str(input_path),
                    "--ass",
                    str(bilingual_ass),
                    "--json",
                    str(translated_json),
                    "--mode",
                    args.subtitle_mode,
                    "--subtitle-position",
                    args.subtitle_position,
                    "--output",
                    str(output_video),
                ]
                + (["--subtitle-y", str(args.subtitle_y)] if args.subtitle_y is not None else [])
                + (["--source-y", str(args.source_y)] if args.source_y is not None else [])
                + (
                    [
                        "--watermark",
                        args.watermark,
                        "--watermark-opacity",
                        str(args.watermark_opacity),
                        "--watermark-fontsize",
                        str(args.watermark_fontsize),
                    ]
                    if args.watermark
                    else []
                )
            )
        else:
            print(f"Using existing rendered video: {output_video}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
