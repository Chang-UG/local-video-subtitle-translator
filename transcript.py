from __future__ import annotations

import argparse
import queue
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from tkinter import BooleanVar, StringVar, Tk, filedialog, messagebox
from tkinter import ttk

from faster_whisper import WhisperModel


LANGUAGES = [
    ("auto", "Auto detect"),
    ("nl", "Dutch"),
    ("en", "English"),
    ("zh", "Chinese"),
    ("fr", "French"),
    ("es", "Spanish"),
    ("de", "German"),
    ("it", "Italian"),
    ("pt", "Portuguese"),
    ("ja", "Japanese"),
    ("ko", "Korean"),
    ("ru", "Russian"),
    ("ar", "Arabic"),
    ("hi", "Hindi"),
]
LANGUAGE_LABELS = [f"{code} · {name}" for code, name in LANGUAGES]
LANGUAGE_CODES = {label: code for label, (code, _name) in zip(LANGUAGE_LABELS, LANGUAGES)}

OUTPUT_FORMATS = {
    "Plain text": "plain",
    "Text + timestamps": "timestamps",
    "SRT format": "srt",
}


@dataclass
class TranscriptSegment:
    index: int
    start: float
    end: float
    text: str


def timestamp(seconds: float, *, srt: bool = False) -> str:
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    separator = "," if srt else "."
    return f"{hours:02}:{minutes:02}:{secs:02}{separator}{millis:03}"


def format_segments(segments: list[TranscriptSegment], output_format: str) -> str:
    cleaned = [segment for segment in segments if segment.text.strip()]
    if output_format == "srt":
        blocks = []
        for segment in cleaned:
            blocks.append(
                "\n".join(
                    [
                        str(segment.index),
                        f"{timestamp(segment.start, srt=True)} --> {timestamp(segment.end, srt=True)}",
                        segment.text.strip(),
                    ]
                )
            )
        return "\n\n".join(blocks)
    if output_format == "timestamps":
        return "\n".join(
            f"[{timestamp(segment.start)} --> {timestamp(segment.end)}] {segment.text.strip()}"
            for segment in cleaned
        )
    return "\n".join(segment.text.strip() for segment in cleaned)


def transcribe_segments(
    media_path: Path,
    *,
    language: str,
    model_size: str,
    device: str,
    compute_type: str,
    beam_size: int,
) -> tuple[list[TranscriptSegment], str, float]:
    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    language_hint = None if language == "auto" else language
    raw_segments, info = model.transcribe(
        str(media_path),
        language=language_hint,
        beam_size=beam_size,
        vad_filter=True,
    )
    segments = [
        TranscriptSegment(index=index, start=segment.start, end=segment.end, text=segment.text.strip())
        for index, segment in enumerate(raw_segments, start=1)
    ]
    return segments, info.language, info.language_probability


def plain_transcript(
    media_path: Path,
    *,
    language: str,
    model_size: str,
    device: str,
    compute_type: str,
    beam_size: int,
) -> tuple[str, str, float]:
    segments, detected_language, probability = transcribe_segments(
        media_path,
        language=language,
        model_size=model_size,
        device=device,
        compute_type=compute_type,
        beam_size=beam_size,
    )
    return format_segments(segments, "plain"), detected_language, probability


class TranscriptGui:
    def __init__(self, initial_file: Path | None = None) -> None:
        self.root = Tk()
        self.root.title("Transcript")
        self.root.geometry("980x700")
        self.root.minsize(820, 560)
        self.root.configure(bg="#101317")

        self.file_path = StringVar(value=str(initial_file) if initial_file else "")
        self.language_label = StringVar(value=LANGUAGE_LABELS[0])
        self.model_size = StringVar(value="small")
        self.device = StringVar(value="cpu")
        self.compute_type = StringVar(value="int8")
        self.beam_size = StringVar(value="5")
        self.output_format_label = StringVar(value="Plain text")
        self.status = StringVar(value="Ready")
        self.copy_status = StringVar(value="")
        self.wrap_text = BooleanVar(value=True)
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.last_segments: list[TranscriptSegment] = []
        self.last_media_path: Path | None = initial_file

        self._style()
        self._build()
        self._poll_events()

    def _style(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", font=("Segoe UI", 10), background="#101317", foreground="#e8eaed")
        style.configure("TFrame", background="#101317")
        style.configure("Panel.TFrame", background="#171b21", borderwidth=1, relief="solid")
        style.configure("TLabel", background="#101317", foreground="#e8eaed")
        style.configure("Panel.TLabel", background="#171b21", foreground="#e8eaed")
        style.configure("Muted.TLabel", background="#171b21", foreground="#9aa4b2")
        style.configure("Title.TLabel", background="#101317", foreground="#ffffff", font=("Segoe UI Semibold", 18))
        style.configure("TButton", background="#252b34", foreground="#f0f3f6", borderwidth=0, padding=(10, 7))
        style.map("TButton", background=[("active", "#313946")])
        style.configure("Accent.TButton", background="#3ddc97", foreground="#08110d", borderwidth=0, padding=(14, 8))
        style.map("Accent.TButton", background=[("active", "#55e6a8"), ("disabled", "#32443b")])
        style.configure("TEntry", fieldbackground="#0f1217", foreground="#f2f4f8", bordercolor="#303743")
        style.configure("TCombobox", fieldbackground="#0f1217", foreground="#f2f4f8", bordercolor="#303743")
        style.configure("TCheckbutton", background="#171b21", foreground="#e8eaed")

    def _build(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        header = ttk.Frame(self.root, padding=(22, 18, 22, 8))
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text="Transcript", style="Title.TLabel").pack(side="left")
        ttk.Label(header, textvariable=self.status).pack(side="right")

        body = ttk.Frame(self.root, style="Panel.TFrame", padding=16)
        body.grid(row=1, column=0, sticky="nsew", padx=22, pady=(8, 22))
        body.columnconfigure(0, weight=1)
        body.rowconfigure(4, weight=1)

        file_row = ttk.Frame(body, style="Panel.TFrame")
        file_row.grid(row=0, column=0, sticky="ew")
        file_row.columnconfigure(0, weight=1)
        ttk.Entry(file_row, textvariable=self.file_path).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(file_row, text="Choose media", command=self.choose_file).grid(row=0, column=1, sticky="e")

        controls = ttk.Frame(body, style="Panel.TFrame")
        controls.grid(row=1, column=0, sticky="ew", pady=(12, 10))
        for col in range(10):
            controls.columnconfigure(col, weight=1)

        ttk.Label(controls, text="Language", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            controls,
            textvariable=self.language_label,
            values=LANGUAGE_LABELS,
            state="readonly",
            width=18,
        ).grid(row=1, column=0, sticky="ew", padx=(0, 8))

        ttk.Label(controls, text="Model", style="Muted.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Combobox(
            controls,
            textvariable=self.model_size,
            values=["tiny", "base", "small", "medium", "large-v3"],
            width=12,
        ).grid(row=1, column=1, sticky="ew", padx=(0, 8))

        ttk.Label(controls, text="Device", style="Muted.TLabel").grid(row=0, column=2, sticky="w")
        ttk.Combobox(
            controls,
            textvariable=self.device,
            values=["cpu", "cuda", "auto"],
            state="readonly",
            width=10,
        ).grid(row=1, column=2, sticky="ew", padx=(0, 8))

        ttk.Label(controls, text="Compute", style="Muted.TLabel").grid(row=0, column=3, sticky="w")
        ttk.Combobox(
            controls,
            textvariable=self.compute_type,
            values=["int8", "float16", "float32"],
            width=10,
        ).grid(row=1, column=3, sticky="ew", padx=(0, 8))

        ttk.Label(controls, text="Beam", style="Muted.TLabel").grid(row=0, column=4, sticky="w")
        ttk.Entry(controls, textvariable=self.beam_size, width=6).grid(row=1, column=4, sticky="ew", padx=(0, 8))

        ttk.Label(controls, text="Output", style="Muted.TLabel").grid(row=0, column=5, sticky="w")
        output_combo = ttk.Combobox(
            controls,
            textvariable=self.output_format_label,
            values=list(OUTPUT_FORMATS),
            state="readonly",
            width=16,
        )
        output_combo.grid(row=1, column=5, sticky="ew", padx=(0, 8))
        output_combo.bind("<<ComboboxSelected>>", self.rerender_output)

        ttk.Checkbutton(controls, text="Wrap", variable=self.wrap_text, command=self.update_wrap).grid(
            row=1, column=6, sticky="w", padx=(0, 8)
        )
        self.run_button = ttk.Button(controls, text="Transcribe", style="Accent.TButton", command=self.start)
        self.run_button.grid(row=1, column=7, sticky="ew", padx=(0, 8))
        ttk.Button(controls, text="Copy", command=self.copy_text).grid(row=1, column=8, sticky="ew", padx=(0, 8))
        ttk.Button(controls, text="Save SRT", command=self.save_srt).grid(row=1, column=9, sticky="ew")

        ttk.Label(
            body,
            text="Copyable source transcript. Files are written only when Save SRT is clicked.",
            style="Muted.TLabel",
        ).grid(row=2, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(body, textvariable=self.copy_status, style="Muted.TLabel").grid(row=3, column=0, sticky="ew")

        import tkinter as tk

        text_frame = ttk.Frame(body, style="Panel.TFrame")
        text_frame.grid(row=4, column=0, sticky="nsew")
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)
        self.output = tk.Text(
            text_frame,
            wrap="word",
            bg="#0f1217",
            fg="#d6dde7",
            insertbackground="#d6dde7",
            relief="flat",
            padx=12,
            pady=12,
            undo=True,
        )
        scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=self.output.yview)
        self.output.configure(yscrollcommand=scrollbar.set)
        self.output.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

    def choose_file(self) -> None:
        filename = filedialog.askopenfilename(
            title="Choose audio or video",
            filetypes=[("Media files", "*.mp4 *.mov *.mkv *.avi *.mp3 *.wav *.m4a"), ("All files", "*.*")],
        )
        if filename:
            self.file_path.set(filename)
            self.last_media_path = Path(filename)
            self.copy_status.set("")

    def start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        media_path = Path(self.file_path.get()).expanduser()
        if not media_path.exists():
            messagebox.showwarning("Missing file", "Choose an existing audio or video file first.")
            return
        try:
            beam_size = int(self.beam_size.get())
        except ValueError:
            messagebox.showwarning("Invalid beam", "Beam must be an integer.")
            return
        if beam_size < 1:
            messagebox.showwarning("Invalid beam", "Beam must be at least 1.")
            return

        self.output.delete("1.0", "end")
        self.last_segments = []
        self.last_media_path = media_path
        self.copy_status.set("")
        self.status.set("Loading model...")
        self.run_button.configure(state="disabled")
        self.worker = threading.Thread(
            target=self._worker,
            args=(
                media_path,
                LANGUAGE_CODES[self.language_label.get()],
                self.model_size.get().strip() or "small",
                self.device.get(),
                self.compute_type.get().strip() or "int8",
                beam_size,
                OUTPUT_FORMATS[self.output_format_label.get()],
            ),
            daemon=True,
        )
        self.worker.start()

    def _worker(
        self,
        media_path: Path,
        language: str,
        model_size: str,
        device: str,
        compute_type: str,
        beam_size: int,
        output_format: str,
    ) -> None:
        try:
            self.events.put(("status", "Transcribing..."))
            segments, detected_language, probability = transcribe_segments(
                media_path,
                language=language,
                model_size=model_size,
                device=device,
                compute_type=compute_type,
                beam_size=beam_size,
            )
        except Exception as exc:
            self.events.put(("error", str(exc)))
            return
        self.events.put(("done", (segments, output_format, detected_language, probability)))

    def _poll_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "status":
                    self.status.set(str(payload))
                elif event == "error":
                    self.status.set("Failed")
                    self.run_button.configure(state="normal")
                    messagebox.showerror("Transcription failed", str(payload))
                elif event == "done":
                    segments, output_format, detected_language, probability = payload
                    self.last_segments = segments
                    text = format_segments(segments, output_format)
                    self.output.delete("1.0", "end")
                    self.output.insert("1.0", text)
                    self.status.set(f"Done · {detected_language} ({probability:.1%})")
                    self.copy_status.set(f"{len(text)} characters")
                    self.run_button.configure(state="normal")
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)

    def copy_text(self) -> None:
        text = self.output.get("1.0", "end").strip()
        if not text:
            self.copy_status.set("Nothing to copy")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.copy_status.set("Copied to clipboard")

    def save_srt(self) -> None:
        if not self.last_segments:
            self.copy_status.set("Nothing to save")
            messagebox.showinfo("No transcript", "Transcribe a file before saving SRT.")
            return

        initial_dir = str(self.last_media_path.parent) if self.last_media_path else str(Path.cwd())
        initial_file = f"{self.last_media_path.stem}.srt" if self.last_media_path else "transcript.srt"
        filename = filedialog.asksaveasfilename(
            title="Save SRT",
            initialdir=initial_dir,
            initialfile=initial_file,
            defaultextension=".srt",
            filetypes=[("SRT subtitles", "*.srt"), ("All files", "*.*")],
        )
        if not filename:
            return
        srt_text = format_segments(self.last_segments, "srt")
        Path(filename).write_text(srt_text + ("\n" if srt_text else ""), encoding="utf-8")
        self.copy_status.set(f"Saved SRT: {Path(filename).name}")

    def update_wrap(self) -> None:
        self.output.configure(wrap="word" if self.wrap_text.get() else "none")

    def rerender_output(self, _event=None) -> None:
        if not self.last_segments:
            return
        text = format_segments(self.last_segments, OUTPUT_FORMATS[self.output_format_label.get()])
        self.output.delete("1.0", "end")
        self.output.insert("1.0", text)
        self.copy_status.set(f"{len(text)} characters")

    def run(self) -> None:
        self.root.mainloop()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Open a GUI for plain source transcript extraction.")
    parser.add_argument("input", nargs="?", type=Path, help="Optional media file to preload in the GUI.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    TranscriptGui(args.input).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
