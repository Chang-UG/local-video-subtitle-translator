# Local Video Subtitle Translator Distributable MVP

This is the smallest practical packaging target for sharing the app with another Windows user.

## MVP Boundary

Keep:

- GUI workbench in `main.py`
- transcript-only GUI in `transcript.py`
- batch queue
- environment self-check
- first-frame preview and subtitle position picking
- transcription with faster-whisper
- offline translation with `llama-cli`
- Chinese and English subtitle targets
- translation review window
- target-language-only and bilingual subtitle burn-in
- floating watermark
- per-video output folders under `output/<video_name>/`

Do not include yet:

- voice-over generation / voice replacement
- speaker separation
- app-store-style installer
- one-file executable
- OCR detection for hard-burned subtitles
- automatic online video download

## Recommended MVP Distribution Shape

```text
Local-Video-Subtitle-Translator-MVP/
|-- main.py
|-- transcript.py
|-- README.md
|-- DISTRIBUTION_MVP.md
|-- environment.yml
|-- requirements.txt
|-- install_env.bat
|-- run_gui.bat
|-- run_transcript.bat
|-- scripts/
|   |-- process_bilingual_subs.py
|   |-- transcribe.py
|   |-- translate.py
|   |-- import_srt.py
|   |-- make_srt.py
|   |-- render_video.py
|   |-- clean_recording.py
|-- models/
|   |-- Qwen2.5-1.5B-Instruct-Q4_K_M.gguf
|-- input/
|-- output/
|-- transcript/
```

## Runtime Assumptions

Target platform:

- Windows 10/11
- Anaconda or Miniconda installed
- NVIDIA GPU optional

The MVP should work on CPU, but GPU translation and future GPU transcription depend on the user's local CUDA stack.

## First-Run Flow For User

1. Unzip `Local-Video-Subtitle-Translator-MVP`.
2. Double-click `install_env.bat`.
3. Put the GGUF model in `models/` if it is not bundled.
4. Double-click `run_gui.bat`.
5. Add videos in the queue and process.

## Offline Reality Check

Fully offline operation needs all of these already local:

- Conda packages installed in the environment
- `faster-whisper` Python package installed
- `llama-cli.exe` from `llama.cpp`
- translation GGUF model in `models/`
- faster-whisper model cache already downloaded, or a local faster-whisper model folder

The current MVP is offline for translation once the GGUF model is present. The first faster-whisper run may still download the Whisper model from Hugging Face unless the cache already exists.

## Packaging Strategy

Use a source-folder distribution first:

- easiest to debug
- smallest risk with native DLLs
- keeps conda-managed `ffmpeg` and `llama-cli`
- avoids PyInstaller hidden-import and DLL collection problems

Later, after the workflow stabilizes, consider:

- `conda-pack` portable environment
- NSIS/Inno Setup installer
- PyInstaller one-folder build, not one-file

## MVP Acceptance Checklist

- `install_env.bat` creates or updates the `vibecoding` environment.
- `run_gui.bat` opens the GUI.
- Environment tab reports ffmpeg, ffprobe, llama-cli, faster-whisper, and model status.
- A sample video can be added to the queue.
- First-frame preview appears.
- Custom subtitle position can be selected by clicking preview.
- Pipeline produces `output/<video_name>/<video_name>_zh_subs.mp4` or `output/<video_name>/<video_name>_en_subs.mp4`.
- Translation review can save edits and rebuild SRT/ASS.
- Re-running after review rebuilds the rendered video.

## Known MVP Limitations

- The user still needs Anaconda/Miniconda.
- The first faster-whisper model download is not bundled.
- GPU setup is best-effort and machine-specific.
- GUI logs are still engineering-style.
- Render preview is a generated 5-second file, not an embedded video player.
