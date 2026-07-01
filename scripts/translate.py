from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def default_llama_cli() -> str:
    env_bin = Path(sys.executable).parent / "Library" / "bin" / "llama-cli.exe"
    if env_bin.exists():
        return str(env_bin)
    return "llama-cli"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Translate transcript segments with local llama.cpp llama-cli and write aligned bilingual files."
    )
    parser.add_argument("input", type=Path, help="Path to a .segments.json file from transcribe.py.")
    parser.add_argument(
        "--model",
        required=True,
        type=Path,
        help="Path to a local GGUF translation-capable chat model.",
    )
    parser.add_argument(
        "--llama-cli",
        default=default_llama_cli(),
        help="Path to llama.cpp llama-cli executable. Default: llama-cli from PATH",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=4,
        help="Segments per llama-cli request. Smaller is more reliable; larger gives more context. Default: 4",
    )
    parser.add_argument(
        "--ctx-size",
        type=int,
        default=4096,
        help="llama.cpp context size. Default: 4096",
    )
    parser.add_argument(
        "--threads",
        type=int,
        help="llama.cpp CPU threads. Default: llama-cli decides",
    )
    parser.add_argument(
        "--gpu-layers",
        default="0",
        help="llama.cpp GPU offload layers. Use auto to enable GPU offload. Default: 0",
    )
    parser.add_argument(
        "--target-language",
        choices=["zh", "en"],
        default="zh",
        help="Translation target language. Use zh for Simplified Chinese or en for English. Default: zh",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        help="Output translated transcript JSON path. Default: transcript/<stem>.<target>.json",
    )
    parser.add_argument(
        "--output-txt",
        type=Path,
        help="Output bilingual TXT path. Default: transcript/<stem>.bilingual.txt",
    )
    return parser.parse_args()


def load_transcript(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    if "segments" not in payload or not isinstance(payload["segments"], list):
        raise ValueError(f"Invalid transcript JSON: {path}")
    return payload


def output_stem(input_path: Path) -> Path:
    name = input_path.name
    suffix = ".segments.json"
    if name.endswith(suffix):
        return input_path.with_name(name[: -len(suffix)])
    return input_path.with_suffix("")


def chunked(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def extract_json_array(text: str) -> list[dict[str, Any]]:
    stripped = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", stripped, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        stripped = fenced.group(1).strip()

    decoder = json.JSONDecoder()
    candidates: list[list[dict[str, Any]]] = []
    for match in re.finditer(r"\[", stripped):
        try:
            parsed, _ = decoder.raw_decode(stripped[match.start() :])
        except json.JSONDecodeError:
            continue
        if (
            isinstance(parsed, list)
            and parsed
            and all(isinstance(item, dict) for item in parsed)
            and all("index" in item and "translation" in item for item in parsed)
        ):
            candidates.append(parsed)

    if not candidates:
        raise ValueError("Translation response did not contain a JSON translation array.")
    return candidates[-1]


def target_spec(target_language: str) -> tuple[str, str, str]:
    if target_language == "en":
        return ("English", "natural, faithful English subtitle text suitable for reading aloud", "English")
    return ("Simplified Chinese", "natural Simplified Chinese suitable for reading aloud", "Chinese")


def target_text_key(target_language: str) -> str:
    return "en_text" if target_language == "en" else "zh_text"


def build_prompt(source_language: str, target_language: str, segments: list[dict[str, Any]]) -> str:
    source_payload = [
        {
            "index": segment["index"],
            "start": segment["start"],
            "end": segment["end"],
            "text": segment["text"],
        }
        for segment in segments
    ]
    target_name, target_instruction, example_translation = target_spec(target_language)
    examples = ""
    if target_language == "en":
        examples = (
            "Faithful Chinese-to-English examples:\n"
            "[{\"index\":1,\"text\":\"这个进球非常漂亮。\"}] -> "
            "[{\"index\":1,\"translation\":\"That was a beautiful goal.\"}]\n"
            "[{\"index\":2,\"text\":\"大家好，欢迎来到今天的比赛现场。\"}] -> "
            "[{\"index\":2,\"translation\":\"Hello everyone, welcome to today's match.\"}]\n"
        )
    return (
        "You are a subtitle and voice-over translator.\n"
        f"Translate transcript segments into {target_instruction}.\n"
        "Keep translations concise and fluent. Preserve names, places, numbers, and factual meaning.\n"
        "Translate the source meaning faithfully; do not answer the speaker, summarize loosely, or invent new content.\n"
        "Keep each output aligned to its input segment index.\n"
        "If the source is already close to the target language, rewrite it into clean subtitle wording instead of copying errors.\n"
        "Return only valid JSON. Do not add markdown.\n"
        f'The JSON must be an array of objects like {{"index": 1, "translation": "{example_translation}"}}.\n'
        f"Source language hint: {source_language}\n"
        f"Target language: {target_name}\n"
        f"{examples}"
        "Segments:\n"
        + json.dumps(source_payload, ensure_ascii=False)
    )


def run_llama_cli(
    *,
    llama_cli: str,
    model: Path,
    prompt: str,
    ctx_size: int,
    threads: int | None,
    gpu_layers: str,
) -> str:
    command = [
        llama_cli,
        "-m",
        str(model),
        "-p",
        prompt,
        "-n",
        "2048",
        "--ctx-size",
        str(ctx_size),
        "--temp",
        "0.2",
        "--no-display-prompt",
        "--single-turn",
        "--simple-io",
        "--gpu-layers",
        gpu_layers,
    ]
    if threads:
        command.extend(["--threads", str(threads)])

    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "llama-cli failed with exit code "
            f"{completed.returncode}\nSTDERR:\n{completed.stderr}\nSTDOUT:\n{completed.stdout}"
        )
    return completed.stdout


def translate_batch(
    *,
    llama_cli: str,
    model: Path,
    source_language: str,
    target_language: str,
    segments: list[dict[str, Any]],
    ctx_size: int,
    threads: int | None,
    gpu_layers: str,
) -> list[dict[str, Any]]:
    prompt = build_prompt(source_language, target_language, segments)
    output = run_llama_cli(
        llama_cli=llama_cli,
        model=model,
        prompt=prompt,
        ctx_size=ctx_size,
        threads=threads,
        gpu_layers=gpu_layers,
    )
    translated = extract_json_array(output)
    if len(segments) == 1 and len(translated) == 1:
        translated[0]["index"] = segments[0]["index"]
    return translated


def repair_mojibake(text: str) -> str:
    markers = ("Ã", "Â", "â", "æ", "ç", "è", "é", "ä", "å", "ï")
    if not any(marker in text for marker in markers):
        return text
    try:
        repaired = text.encode("cp1252").decode("utf-8")
    except UnicodeError:
        return text
    return repaired if repaired else text


def merge_translations(
    source_segments: list[dict[str, Any]],
    translated_items: list[dict[str, Any]],
    target_language: str,
) -> list[dict[str, Any]]:
    translations_by_index = {
        int(item["index"]): repair_mojibake(str(item["translation"]).strip())
        for item in translated_items
        if "index" in item and "translation" in item
    }

    missing = [segment["index"] for segment in source_segments if segment["index"] not in translations_by_index]
    if missing:
        raise ValueError(f"Translation response is missing segment indexes: {missing}")

    field_name = target_text_key(target_language)
    merged_segments: list[dict[str, Any]] = []
    for segment in source_segments:
        item = {
            "index": segment["index"],
            "start": segment["start"],
            "end": segment["end"],
            "source_text": segment["text"],
        }
        item[field_name] = translations_by_index[segment["index"]]
        merged_segments.append(item)
    return merged_segments


def write_outputs(
    *,
    source_payload: dict[str, Any],
    translated_segments: list[dict[str, Any]],
    json_path: Path,
    txt_path: Path,
    model: Path,
    target_language: str,
) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    txt_path.parent.mkdir(parents=True, exist_ok=True)

    field_name = target_text_key(target_language)
    target_label = "EN" if target_language == "en" else "ZH"
    payload = {
        "metadata": {
            **source_payload.get("metadata", {}),
            "translation_backend": "llama-cli",
            "translation_model": str(model),
            "target_language": target_language,
        },
        "segments": translated_segments,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines: list[str] = []
    for segment in translated_segments:
        lines.extend(
            [
                f"[{segment['index']:05}] {segment['start']:.2f} --> {segment['end']:.2f}",
                f"SRC: {segment['source_text']}",
                f"{target_label} : {segment[field_name]}",
                "",
            ]
        )
    txt_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    input_path = args.input.expanduser().resolve()
    model_path = args.model.expanduser().resolve()

    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        return 2
    if not model_path.exists():
        print(f"Model file not found: {model_path}", file=sys.stderr)
        return 2
    if args.batch_size < 1:
        print("--batch-size must be at least 1", file=sys.stderr)
        return 2
    if shutil.which(args.llama_cli) is None and not Path(args.llama_cli).exists():
        print(
            "llama-cli was not found. Install llama.cpp or pass --llama-cli path\\to\\llama-cli.exe",
            file=sys.stderr,
        )
        return 2

    source_payload = load_transcript(input_path)
    source_segments = source_payload["segments"]
    language = source_payload.get("metadata", {}).get("language", "auto")

    all_translated_items: list[dict[str, Any]] = []
    batches = chunked(source_segments, args.batch_size)
    for batch_index, batch in enumerate(batches, start=1):
        print(f"Translating batch {batch_index}/{len(batches)} ({len(batch)} segments)")
        all_translated_items.extend(
            translate_batch(
                llama_cli=args.llama_cli,
                model=model_path,
                source_language=language,
                target_language=args.target_language,
                segments=batch,
                ctx_size=args.ctx_size,
                threads=args.threads,
                gpu_layers=args.gpu_layers,
            )
        )

    translated_segments = merge_translations(source_segments, all_translated_items, args.target_language)
    stem = output_stem(input_path)
    json_path = args.output_json or stem.with_suffix(f".{args.target_language}.json")
    txt_path = args.output_txt or stem.with_suffix(".bilingual.txt")
    write_outputs(
        source_payload=source_payload,
        translated_segments=translated_segments,
        json_path=json_path,
        txt_path=txt_path,
        model=model_path,
        target_language=args.target_language,
    )

    print(f"Wrote: {json_path}")
    print(f"Wrote: {txt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
