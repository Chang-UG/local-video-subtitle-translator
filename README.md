# Local Video Subtitle Translator

[English](README.md) | [简体中文](README.zh-CN.md)

A local-first tool for transcribing videos, translating subtitles into Chinese or English, reviewing the translated text, and burning translated or bilingual subtitles into the final video.

Current MVP:

```text
audio/video file
-> faster-whisper
-> transcript text
-> srt subtitles
-> segment json for aligned translation review
-> local llama.cpp translation
-> burned-in translated or bilingual subtitles
```

## Project Layout

```text
local_video_subtitle_translator/
+-- input/
+-- models/
+-- transcript/
+-- output/
+-- scripts/
+-- main.py
```

Typical outputs:

- `output/lecture/lecture.segments.json`
- `output/lecture/lecture.zh.json`
- `output/lecture/lecture.bilingual.txt`
- `output/lecture/lecture.bilingual.srt`
- `output/lecture/lecture.bilingual.ass`
- `output/lecture/lecture_zh_subs.mp4`

## Environment

The local Conda environment is:

```powershell
D:\anaconda3\Scripts\conda.exe activate vibecoding
```

Recreate it on another machine:

```powershell
D:\anaconda3\Scripts\conda.exe env create -f environment.yml
```

## Transcribe

Put source media in `input/`, then run:

```powershell
D:\anaconda3\envs\vibecoding\python.exe scripts\transcribe.py input\lecture.mp4
```

By default this uses CPU `int8`, which is slower than GPU but works without CUDA.

Force a language:

```powershell
D:\anaconda3\envs\vibecoding\python.exe scripts\transcribe.py input\lecture.mp4 --language nl
D:\anaconda3\envs\vibecoding\python.exe scripts\transcribe.py input\lecture.mp4 --language en
D:\anaconda3\envs\vibecoding\python.exe scripts\transcribe.py input\lecture.mp4 --language zh
```

Outputs are written to `transcript/`:

- `transcript/lecture.txt`
- `transcript/lecture.srt`
- `transcript/lecture.segments.json`

CPU-friendly run:

```powershell
D:\anaconda3\envs\vibecoding\python.exe scripts\transcribe.py input\lecture.mp4 --device cpu --compute-type int8
```

GPU run, after CUDA/cuBLAS is correctly installed:

```powershell
D:\anaconda3\envs\vibecoding\python.exe scripts\transcribe.py input\lecture.mp4 --device cuda --compute-type float16
```

The first run of a model downloads model files from Hugging Face; later runs use the local cache.

## Integrated Runner

The easiest entry point is `main.py`.

Open the GUI:

```powershell
D:\anaconda3\envs\vibecoding\python.exe main.py
```

or:

```powershell
D:\anaconda3\envs\vibecoding\python.exe main.py --gui
```

Run the full pipeline from the command line:

```powershell
D:\anaconda3\envs\vibecoding\python.exe main.py input\lecture.mp4 --language nl --subtitle-mode chinese --subtitle-position center --force
```

Useful options:

- `--language auto|nl|en|zh|fr|es|de|it|pt|ja|ko|ru|ar|hi`
- `--target-language zh|en`
- `--subtitle-source audio|external-srt`
- `--source-srt path\to\subtitle.srt` when using an external SRT file
- `--subtitle-mode chinese|bilingual`
- `--subtitle-position upper|center|lower`
- `--subtitle-y 0.55` for an exact vertical subtitle position
- `--source-y 0.32` for an exact source-language subtitle position in bilingual mode
- `--watermark "上北下南的东"` or `--watermark ""` to disable
- `--translation-gpu-layers auto`
- `--skip-render` to stop after transcript, translation, SRT, and ASS files
- `--force` to rebuild existing artifacts

The GUI is now a queue-based workbench:

- add multiple media files and process them as a batch queue
- choose the translation target: Chinese subtitles or English subtitles
- choose whether the source subtitles come from audio transcription or an external SRT file
- check pipeline progress by step: subtitle detection, transcription, translation, subtitle files, video render
- choose whether to render immediately or pause after subtitle files for translation review
- run environment checks for ffmpeg, ffprobe, llama-cli, the local GGUF model, faster-whisper, and NVIDIA GPU availability
- preview the source first frame, rendered first frame, or generate a 5-second rendered preview clip
- in bilingual mode, show separate source/target guide lines and click near either line to adjust that language
- open the translation review window to edit source/target segment text, then render the selected video after review

## Translate

Translation is offline-first through `llama.cpp` `llama-cli`.

Recommended local model direction: a small Chinese-capable instruct GGUF model, for example Qwen2.5/Qwen3 1.5B or 3B Instruct quantized to Q4/Q5.

Installed local model:

- `models/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf`

Translate aligned transcript segments with a local GGUF model:

```powershell
D:\anaconda3\envs\vibecoding\python.exe scripts\translate.py transcript\lecture.segments.json --model models\Qwen2.5-1.5B-Instruct-Q4_K_M.gguf
```

Translate Chinese source subtitles into English:

```powershell
D:\anaconda3\envs\vibecoding\python.exe scripts\translate.py transcript\lecture.segments.json --model models\Qwen2.5-1.5B-Instruct-Q4_K_M.gguf --target-language en
```

Use GPU offload when available:

```powershell
D:\anaconda3\envs\vibecoding\python.exe scripts\translate.py transcript\lecture.segments.json --model models\Qwen2.5-1.5B-Instruct-Q4_K_M.gguf --gpu-layers auto
```

`translate.py` automatically uses the `llama-cli.exe` inside the `vibecoding` Conda environment when it exists. If you want to override it:

```powershell
D:\anaconda3\envs\vibecoding\python.exe scripts\translate.py transcript\lecture.segments.json --model models\Qwen2.5-1.5B-Instruct-Q4_K_M.gguf --llama-cli path\to\llama-cli.exe
```

Outputs:

- `transcript/lecture.zh.json`
- `transcript/lecture.en.json` when `--target-language en` is used
- `transcript/lecture.bilingual.txt`

The bilingual TXT keeps each source segment and its target-language translation together. It is for review, not for final styled subtitles.

The subtitle pipeline stays local where practical:

- Subtitle generation: Python scripts.
- Styled subtitle burn-in: ffmpeg with ASS/libass.
- Translation: local `llama-cli` with a GGUF model.

## Subtitle Format

Use SRT as a plain compatibility subtitle:

```text
1
00:00:00,000 --> 00:00:03,000
Original line
Chinese translation line
```

SRT does not reliably support per-line color, font, or position across players. For bilingual subtitles with different colors or different screen positions, use ASS:

```text
Dialogue: 0,0:00:00.00,0:00:03.00,Source,,0,0,0,,Original line
Dialogue: 0,0:00:00.00,0:00:03.00,Target,,0,0,0,,Translated line
```

## One-Step Subtitle Burn-In

Run the full local pipeline on a source video:

```powershell
D:\anaconda3\envs\vibecoding\python.exe scripts\process_bilingual_subs.py input\lecture.mp4 --language nl
```

Use an external source-language SRT instead of transcribing the video audio:

```powershell
D:\anaconda3\envs\vibecoding\python.exe scripts\process_bilingual_subs.py input\lecture.mp4 --subtitle-source external-srt --source-srt input\lecture.nl.srt --language nl
```

Use GPU for local translation in the full pipeline:

```powershell
D:\anaconda3\envs\vibecoding\python.exe scripts\process_bilingual_subs.py input\lecture.mp4 --language nl --translation-gpu-layers auto
```

Translate Chinese subtitles into English in the full pipeline:

```powershell
D:\anaconda3\envs\vibecoding\python.exe scripts\process_bilingual_subs.py input\lecture.mp4 --language zh --target-language en
```

For phone screen recordings, crop fixed top/bottom app UI first:

```powershell
D:\anaconda3\envs\vibecoding\python.exe scripts\process_bilingual_subs.py input\lecture.mp4 --language nl --clean-recording
```

The recording cleaner crops fixed top/bottom UI and pads the video back to the original size with white bars, so the image is not stretched. Tune it like this:

```powershell
D:\anaconda3\envs\vibecoding\python.exe scripts\process_bilingual_subs.py input\lecture.mp4 --language nl --clean-recording --clean-top 120 --clean-bottom 180
```

Outputs:

- `output/lecture/lecture.segments.json`
- `output/lecture/lecture.zh.json`
- `output/lecture/lecture.bilingual.txt`
- `output/lecture/lecture.bilingual.srt`
- `output/lecture/lecture.bilingual.ass`
- `output/lecture/lecture_zh_subs.mp4`
- `output/lecture/lecture_en_subs.mp4` when `--target-language en` is used

The pipeline first checks for embedded subtitle streams with `ffprobe`. It can detect real subtitle streams inside the container, but it cannot reliably detect subtitles already burned into the video image. Hardcoded visual subtitles need OCR if we want automatic detection later.

The current default burn-in mode is Chinese-only, with yellow Chinese subtitles around the visual safe center for vertical social video. To render bilingual subtitles:

```powershell
D:\anaconda3\envs\vibecoding\python.exe scripts\process_bilingual_subs.py input\lecture.mp4 --language nl --subtitle-mode bilingual
```

Choose subtitle position:

```powershell
D:\anaconda3\envs\vibecoding\python.exe scripts\process_bilingual_subs.py input\lecture.mp4 --language nl --subtitle-position upper
D:\anaconda3\envs\vibecoding\python.exe scripts\process_bilingual_subs.py input\lecture.mp4 --language nl --subtitle-position center
D:\anaconda3\envs\vibecoding\python.exe scripts\process_bilingual_subs.py input\lecture.mp4 --language nl --subtitle-position lower
D:\anaconda3\envs\vibecoding\python.exe scripts\process_bilingual_subs.py input\lecture.mp4 --language nl --subtitle-y 0.55
D:\anaconda3\envs\vibecoding\python.exe scripts\process_bilingual_subs.py input\lecture.mp4 --language nl --subtitle-mode bilingual --source-y 0.32 --subtitle-y 0.58
```

By default, the full pipeline adds a subtle floating watermark:

```text
上北下南的东
```

Disable it with:

```powershell
D:\anaconda3\envs\vibecoding\python.exe scripts\process_bilingual_subs.py input\lecture.mp4 --language nl --watermark ""
```

The current Conda ffmpeg build does not include the `ass/subtitles` filter, so `render_video.py` automatically falls back to `drawtext`.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

This repository does not include or grant rights to third-party model weights,
media files, fonts, or binaries. Users are responsible for complying with the
licenses and terms of all third-party components and source materials they use.

Generated transcripts, translations, and subtitles may contain errors and should
be reviewed before professional, commercial, legal, medical, educational, or
public use.
