from __future__ import annotations

import argparse
import json
import queue
import subprocess
import sys
import threading
from pathlib import Path
from tkinter import BooleanVar, Canvas, DoubleVar, Listbox, StringVar, Tk, filedialog, messagebox
from tkinter import ttk


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_WATERMARK = "上北下南的东"
DEFAULT_MODEL = PROJECT_ROOT / "models" / "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf"
DEFAULT_FFMPEG = Path(sys.executable).parent / "Library" / "bin" / "ffmpeg.exe"
DEFAULT_FFPROBE = Path(sys.executable).parent / "Library" / "bin" / "ffprobe.exe"
DEFAULT_LLAMA_CLI = Path(sys.executable).parent / "Library" / "bin" / "llama-cli.exe"

LANGUAGES = [
    ("auto", "自动识别"),
    ("nl", "荷兰语"),
    ("en", "英语"),
    ("zh", "中文"),
    ("fr", "法语"),
    ("es", "西班牙语"),
    ("de", "德语"),
    ("it", "意大利语"),
    ("pt", "葡萄牙语"),
    ("ja", "日语"),
    ("ko", "韩语"),
    ("ru", "俄语"),
    ("ar", "阿拉伯语"),
    ("hi", "印地语"),
]
LANGUAGE_LABELS = [f"{code} · {name}" for code, name in LANGUAGES]
LANGUAGE_CODES = {label: code for label, (code, _name) in zip(LANGUAGE_LABELS, LANGUAGES)}

SUBTITLE_MODES = {
    "仅中文": "chinese",
    "双语": "bilingual",
}
SUBTITLE_POSITIONS = {
    "上方": ("upper", 0.38),
    "中间": ("center", 0.58),
    "下方": ("lower", 0.72),
}
RENDER_POLICIES = {
    "直接渲染成片": False,
    "生成字幕后等待校对": True,
}
CUSTOM_POSITION_LABEL = "自定义"
SUBTITLE_POSITION_LABELS = [*SUBTITLE_POSITIONS, CUSTOM_POSITION_LABEL]

PIPELINE_STEPS = [
    ("subtitles", "字幕检测"),
    ("transcribe", "转写"),
    ("translate", "翻译"),
    ("subtitle_files", "字幕文件"),
    ("render", "视频烧录"),
]


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def artifact_dir_for(input_path: Path) -> Path:
    return PROJECT_ROOT / "output" / input_path.stem


def artifact_paths(input_path: Path) -> dict[str, Path]:
    stem = input_path.stem
    out_dir = artifact_dir_for(input_path)
    return {
        "dir": out_dir,
        "segments": out_dir / f"{stem}.segments.json",
        "zh": out_dir / f"{stem}.zh.json",
        "txt": out_dir / f"{stem}.bilingual.txt",
        "srt": out_dir / f"{stem}.bilingual.srt",
        "ass": out_dir / f"{stem}.bilingual.ass",
        "video": out_dir / f"{stem}_bilingual_subs.mp4",
        "preview_frame": out_dir / f"{stem}.preview.png",
        "preview_clip": out_dir / f"{stem}.preview_5s.mp4",
    }


def build_pipeline_command(args: argparse.Namespace) -> list[str]:
    command = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "process_bilingual_subs.py"),
        str(args.input),
        "--language",
        args.language,
        "--translation-gpu-layers",
        args.translation_gpu_layers,
        "--translation-batch-size",
        str(args.translation_batch_size),
        "--subtitle-mode",
        args.subtitle_mode,
        "--subtitle-position",
        args.subtitle_position,
        "--watermark",
        args.watermark,
    ]
    if args.subtitle_y is not None:
        command.extend(["--subtitle-y", f"{args.subtitle_y:.3f}"])
    if getattr(args, "source_y", None) is not None:
        command.extend(["--source-y", f"{args.source_y:.3f}"])
    if args.force:
        command.append("--force")
    if args.skip_render:
        command.append("--skip-render")
    return command


def run_pipeline(args: argparse.Namespace) -> int:
    input_path = Path(args.input).expanduser()
    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        return 2

    command = build_pipeline_command(args)
    print(" ".join(command))
    completed = subprocess.run(command, cwd=PROJECT_ROOT, check=False)
    return completed.returncode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Video to Chinese subtitle pipeline.")
    parser.add_argument("input", nargs="?", type=Path, help="Source audio/video file. Omit to open the GUI.")
    parser.add_argument("--gui", action="store_true", help="Open the GUI.")
    parser.add_argument("--language", choices=[code for code, _name in LANGUAGES], default="auto", help="Source language.")
    parser.add_argument(
        "--subtitle-mode",
        choices=["chinese", "bilingual"],
        default="chinese",
        help="Burn Chinese-only or bilingual subtitles.",
    )
    parser.add_argument(
        "--subtitle-position",
        choices=["upper", "center", "lower"],
        default="center",
        help="Chinese subtitle vertical position.",
    )
    parser.add_argument("--subtitle-y", type=float, help="Exact subtitle vertical fraction from 0.05 to 0.90.")
    parser.add_argument("--source-y", type=float, help="Exact source subtitle vertical fraction from 0.05 to 0.90.")
    parser.add_argument("--watermark", default=DEFAULT_WATERMARK, help="Floating watermark text. Use empty string to disable.")
    parser.add_argument("--translation-gpu-layers", default="auto", help="llama.cpp GPU layers. Default: auto")
    parser.add_argument("--translation-batch-size", type=int, default=4, help="Translation batch size. Default: 4")
    parser.add_argument("--force", action="store_true", help="Rebuild intermediate files.")
    parser.add_argument("--skip-render", action="store_true", help="Build subtitles but skip video render.")
    return parser.parse_args()


class TranslationReviewWindow:
    def __init__(self, app: PipelineGui, input_path: Path) -> None:
        self.app = app
        self.input_path = input_path
        self.paths = artifact_paths(input_path)
        self.path = self.paths["zh"]
        self.payload: dict = {}
        self.segments: list[dict] = []
        self.current_index: int | None = None

        if not self.path.exists():
            messagebox.showinfo("暂无翻译", "还没有找到翻译 JSON。请先至少跑完转写和翻译。")
            return

        self.window = ttk.Toplevel(app.root) if hasattr(ttk, "Toplevel") else None
        if self.window is None:
            import tkinter as tk

            self.window = tk.Toplevel(app.root)
        self.window.title(f"翻译校对 · {input_path.stem}")
        self.window.geometry("980x620")
        self.window.configure(bg="#101317")
        self._load()
        self._build()

    def _load(self) -> None:
        self.payload = json.loads(self.path.read_text(encoding="utf-8"))
        raw_segments = self.payload.get("segments", [])
        self.segments = raw_segments if isinstance(raw_segments, list) else []

    def _build(self) -> None:
        root = self.window
        root.columnconfigure(0, weight=1)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(1, weight=1)

        ttk.Label(root, text="逐条检查转写和中文字幕，保存后会重新生成 SRT/ASS。", style="TLabel").grid(
            row=0, column=0, columnspan=2, sticky="ew", padx=16, pady=(14, 8)
        )

        columns = ("index", "time", "source", "zh")
        self.tree = ttk.Treeview(root, columns=columns, show="headings", height=18)
        for col, label, width in [
            ("index", "#", 50),
            ("time", "时间", 120),
            ("source", "原文", 300),
            ("zh", "中文", 360),
        ]:
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, stretch=col in {"source", "zh"})
        self.tree.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=16, pady=(0, 12))
        self.tree.bind("<<TreeviewSelect>>", self._select_row)

        for segment in self.segments:
            self.tree.insert(
                "",
                "end",
                iid=str(segment.get("index")),
                values=(
                    segment.get("index"),
                    f"{segment.get('start', 0):.2f}-{segment.get('end', 0):.2f}",
                    segment.get("source_text", ""),
                    segment.get("zh_text", ""),
                ),
            )

        import tkinter as tk

        edit_frame = ttk.Frame(root, padding=(16, 0, 16, 16))
        edit_frame.grid(row=2, column=0, columnspan=2, sticky="ew")
        edit_frame.columnconfigure(0, weight=1)
        edit_frame.columnconfigure(1, weight=1)

        ttk.Label(edit_frame, text="原文").grid(row=0, column=0, sticky="w")
        ttk.Label(edit_frame, text="中文字幕").grid(row=0, column=1, sticky="w")
        self.source_text = tk.Text(edit_frame, height=5, wrap="word", bg="#0f1217", fg="#d6dde7", relief="flat")
        self.zh_text = tk.Text(edit_frame, height=5, wrap="word", bg="#0f1217", fg="#d6dde7", relief="flat")
        self.source_text.grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=(4, 10))
        self.zh_text.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(4, 10))

        button_row = ttk.Frame(edit_frame)
        button_row.grid(row=2, column=0, columnspan=2, sticky="ew")
        ttk.Button(button_row, text="保存当前行", command=self.save_current).pack(side="left")
        ttk.Button(button_row, text="保存全部并重建字幕", command=self.save_all).pack(side="left", padx=(8, 0))
        ttk.Button(button_row, text="重新载入", command=self.reload).pack(side="left", padx=(8, 0))

        if self.segments:
            first = str(self.segments[0].get("index"))
            self.tree.selection_set(first)
            self.tree.focus(first)
            self._select_row()

    def _selected_segment(self) -> dict | None:
        if self.current_index is None:
            return None
        for segment in self.segments:
            if segment.get("index") == self.current_index:
                return segment
        return None

    def _select_row(self, _event=None) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        self.current_index = int(selected[0])
        segment = self._selected_segment()
        if not segment:
            return
        self.source_text.delete("1.0", "end")
        self.zh_text.delete("1.0", "end")
        self.source_text.insert("1.0", segment.get("source_text", ""))
        self.zh_text.insert("1.0", segment.get("zh_text", ""))

    def save_current(self) -> None:
        segment = self._selected_segment()
        if not segment:
            return
        segment["source_text"] = self.source_text.get("1.0", "end").strip()
        segment["zh_text"] = self.zh_text.get("1.0", "end").strip()
        iid = str(segment.get("index"))
        self.tree.item(
            iid,
            values=(
                segment.get("index"),
                f"{segment.get('start', 0):.2f}-{segment.get('end', 0):.2f}",
                segment.get("source_text", ""),
                segment.get("zh_text", ""),
            ),
        )

    def save_all(self) -> None:
        self.save_current()
        self.payload["segments"] = self.segments
        self.path.write_text(json.dumps(self.payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        command = [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "make_srt.py"),
            str(self.path),
            "--output-srt",
            str(self.paths["srt"]),
            "--output-ass",
            str(self.paths["ass"]),
        ]
        completed = subprocess.run(command, cwd=PROJECT_ROOT, check=False, capture_output=True, text=True)
        if completed.returncode == 0:
            stale_outputs = []
            for key in ("video", "preview_clip"):
                if self.paths[key].exists():
                    self.paths[key].unlink()
                    stale_outputs.append(self.paths[key])
            extra = ""
            if stale_outputs:
                extra = "\n\n旧成片/预览片段已移除，下次处理会重新烧录。"
            messagebox.showinfo("已保存", f"已更新翻译和字幕文件：\n{self.paths['srt']}\n{self.paths['ass']}{extra}")
        else:
            messagebox.showerror("重建字幕失败", completed.stdout + completed.stderr)

    def reload(self) -> None:
        self._load()
        for item in self.tree.get_children():
            self.tree.delete(item)
        for segment in self.segments:
            self.tree.insert(
                "",
                "end",
                iid=str(segment.get("index")),
                values=(
                    segment.get("index"),
                    f"{segment.get('start', 0):.2f}-{segment.get('end', 0):.2f}",
                    segment.get("source_text", ""),
                    segment.get("zh_text", ""),
                ),
            )


class PipelineGui:
    preview_width = 360
    preview_height = 500

    def __init__(self) -> None:
        self.root = Tk()
        self.root.title("Local Video Subtitle Translator")
        self.root.geometry("1180x760")
        self.root.minsize(1040, 680)
        self.root.configure(bg="#101317")

        self.input_files: list[Path] = []
        self.file_path = StringVar()
        self.language_label = StringVar(value=LANGUAGE_LABELS[0])
        self.subtitle_mode_label = StringVar(value="仅中文")
        self.subtitle_position_label = StringVar(value="中间")
        self.render_policy_label = StringVar(value="直接渲染成片")
        self.subtitle_y = DoubleVar(value=0.58)
        self.source_y = DoubleVar(value=0.34)
        self.position_hint = StringVar(value="")
        self.watermark = StringVar(value=DEFAULT_WATERMARK)
        self.use_watermark = BooleanVar(value=True)
        self.force = BooleanVar(value=False)
        self.gpu = BooleanVar(value=True)
        self.status = StringVar(value="准备就绪")
        self.env_status = StringVar(value="等待自检")
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.preview_image = None
        self.preview_image_size = (0, 0)
        self.preview_origin = (0, 0)
        self.preview_source: Path | None = None
        self.current_job_index = -1
        self.step_vars: dict[str, StringVar] = {}
        self.step_labels: dict[str, ttk.Label] = {}

        self._style()
        self._build()
        self._poll_events()
        self.run_environment_check()

    def _style(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", font=("Segoe UI", 10), background="#101317", foreground="#e8eaed")
        style.configure("TFrame", background="#101317")
        style.configure("Panel.TFrame", background="#171b21", borderwidth=1, relief="solid")
        style.configure("TLabel", background="#101317", foreground="#e8eaed")
        style.configure("Muted.TLabel", background="#171b21", foreground="#9aa4b2")
        style.configure("Panel.TLabel", background="#171b21", foreground="#e8eaed")
        style.configure("Title.TLabel", background="#101317", foreground="#ffffff", font=("Segoe UI Semibold", 18))
        style.configure("Accent.TButton", background="#3ddc97", foreground="#08110d", borderwidth=0, padding=(14, 8))
        style.map("Accent.TButton", background=[("active", "#55e6a8"), ("disabled", "#32443b")])
        style.configure("TButton", background="#252b34", foreground="#f0f3f6", borderwidth=0, padding=(10, 7))
        style.map("TButton", background=[("active", "#313946")])
        style.configure("TEntry", fieldbackground="#0f1217", foreground="#f2f4f8", bordercolor="#303743")
        style.configure("TCombobox", fieldbackground="#0f1217", foreground="#f2f4f8", bordercolor="#303743")
        style.configure("TCheckbutton", background="#171b21", foreground="#e8eaed")
        style.configure("TNotebook", background="#101317", borderwidth=0)
        style.configure("TNotebook.Tab", background="#252b34", foreground="#dce2ea", padding=(12, 7))
        style.map("TNotebook.Tab", background=[("selected", "#3ddc97")], foreground=[("selected", "#08110d")])

    def _build(self) -> None:
        self.root.columnconfigure(0, weight=0)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(1, weight=1)

        header = ttk.Frame(self.root, padding=(22, 18, 22, 8))
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Label(header, text="Local Video Subtitle Translator", style="Title.TLabel").pack(side="left")
        ttk.Label(header, textvariable=self.status).pack(side="right")

        controls = ttk.Frame(self.root, style="Panel.TFrame", padding=16)
        controls.grid(row=1, column=0, sticky="nsw", padx=(22, 12), pady=(8, 22))
        controls.columnconfigure(0, weight=1)

        self._section_label(controls, "素材队列", 0)
        queue_frame = ttk.Frame(controls, style="Panel.TFrame")
        queue_frame.grid(row=1, column=0, sticky="ew", pady=(4, 8))
        queue_frame.columnconfigure(0, weight=1)
        self.queue_list = Listbox(
            queue_frame,
            height=5,
            bg="#0f1217",
            fg="#d6dde7",
            selectbackground="#3ddc97",
            selectforeground="#08110d",
            relief="flat",
            highlightthickness=1,
            highlightbackground="#303743",
        )
        self.queue_list.grid(row=0, column=0, columnspan=3, sticky="ew")
        self.queue_list.bind("<<ListboxSelect>>", self._queue_selected)
        ttk.Button(queue_frame, text="添加", command=self.add_files).grid(row=1, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(queue_frame, text="移除", command=self.remove_selected).grid(row=1, column=1, sticky="ew", padx=6, pady=(8, 0))
        ttk.Button(queue_frame, text="清空", command=self.clear_queue).grid(row=1, column=2, sticky="ew", pady=(8, 0))

        self._section_label(controls, "语言", 2)
        ttk.Combobox(
            controls,
            textvariable=self.language_label,
            values=LANGUAGE_LABELS,
            state="readonly",
            width=30,
        ).grid(row=3, column=0, sticky="ew", pady=(4, 12))

        self._section_label(controls, "字幕", 4)
        mode_combo = ttk.Combobox(
            controls,
            textvariable=self.subtitle_mode_label,
            values=list(SUBTITLE_MODES),
            state="readonly",
            width=30,
        )
        mode_combo.grid(row=5, column=0, sticky="ew", pady=(4, 8))
        mode_combo.bind("<<ComboboxSelected>>", self._subtitle_mode_changed)
        position_combo = ttk.Combobox(
            controls,
            textvariable=self.subtitle_position_label,
            values=SUBTITLE_POSITION_LABELS,
            state="readonly",
            width=30,
        )
        position_combo.grid(row=6, column=0, sticky="ew", pady=(0, 6))
        position_combo.bind("<<ComboboxSelected>>", self._position_combo_changed)
        self.position_hint_label = ttk.Label(controls, textvariable=self.position_hint, style="Muted.TLabel")
        self.position_hint_label.grid(row=7, column=0, sticky="w", pady=(0, 12))
        self.position_hint_label.grid_remove()

        self._section_label(controls, "输出策略", 8)
        ttk.Combobox(
            controls,
            textvariable=self.render_policy_label,
            values=list(RENDER_POLICIES),
            state="readonly",
            width=30,
        ).grid(row=9, column=0, sticky="ew", pady=(4, 8))

        self._section_label(controls, "选项", 10)
        ttk.Checkbutton(controls, text="使用 GPU 翻译", variable=self.gpu).grid(row=11, column=0, sticky="w", pady=2)
        ttk.Checkbutton(controls, text="重新生成全部文件", variable=self.force).grid(row=12, column=0, sticky="w", pady=2)
        ttk.Checkbutton(controls, text="浮动水印", variable=self.use_watermark).grid(row=13, column=0, sticky="w", pady=(8, 3))
        ttk.Entry(controls, textvariable=self.watermark).grid(row=14, column=0, sticky="ew", pady=(0, 12))

        ttk.Button(controls, text="打开翻译校对", command=self.open_translation_review).grid(row=15, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(controls, text="渲染当前视频", command=self.render_selected).grid(row=16, column=0, sticky="ew", pady=(0, 8))
        self.run_button = ttk.Button(controls, text="开始处理队列", style="Accent.TButton", command=self.start)
        self.run_button.grid(row=17, column=0, sticky="ew")

        self._section_label(controls, "流程", 18)
        steps = ttk.Frame(controls, style="Panel.TFrame")
        steps.grid(row=19, column=0, sticky="ew", pady=(4, 0))
        for row, (key, name) in enumerate(PIPELINE_STEPS):
            var = StringVar(value=f"○ {name}")
            label = ttk.Label(steps, textvariable=var, style="Muted.TLabel")
            label.grid(row=row, column=0, sticky="w", pady=1)
            self.step_vars[key] = var
            self.step_labels[key] = label

        workspace = ttk.Notebook(self.root)
        workspace.grid(row=1, column=1, sticky="nsew", padx=(0, 22), pady=(8, 22))

        self.preview_tab = ttk.Frame(workspace, style="Panel.TFrame", padding=18)
        self.review_tab = ttk.Frame(workspace, style="Panel.TFrame", padding=18)
        self.env_tab = ttk.Frame(workspace, style="Panel.TFrame", padding=18)
        self.log_tab = ttk.Frame(workspace, style="Panel.TFrame", padding=18)
        workspace.add(self.preview_tab, text="预览")
        workspace.add(self.review_tab, text="翻译校对")
        workspace.add(self.env_tab, text="环境")
        workspace.add(self.log_tab, text="日志")

        self._build_preview_tab()
        self._build_review_tab()
        self._build_env_tab()
        self._build_log_tab()

    def _section_label(self, parent: ttk.Frame, text: str, row: int) -> None:
        ttk.Label(parent, text=text, style="Muted.TLabel").grid(row=row, column=0, sticky="w", pady=(4, 2))

    def _build_preview_tab(self) -> None:
        self.preview_tab.columnconfigure(0, weight=1)
        self.preview_tab.rowconfigure(1, weight=1)
        header = ttk.Frame(self.preview_tab, style="Panel.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text="视觉检查", style="Panel.TLabel", font=("Segoe UI Semibold", 13)).pack(side="left")
        self.preview_hint_label = ttk.Label(header, text="", style="Muted.TLabel")
        self.preview_hint_label.pack(side="right")

        self.canvas = Canvas(
            self.preview_tab,
            width=self.preview_width,
            height=self.preview_height,
            bg="#0b0e12",
            highlightthickness=1,
            highlightbackground="#303743",
        )
        self.canvas.grid(row=1, column=0, sticky="n", pady=(12, 10))
        self.canvas.bind("<Button-1>", self._preview_clicked)
        self._draw_empty_preview()

        self.position_text = StringVar(value="字幕位置：58%")
        ttk.Label(self.preview_tab, textvariable=self.position_text, style="Muted.TLabel").grid(row=2, column=0, sticky="ew")

        action_row = ttk.Frame(self.preview_tab, style="Panel.TFrame")
        action_row.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        ttk.Button(action_row, text="预览原片首帧", command=lambda: self.load_selected_preview(rendered=False)).pack(side="left")
        ttk.Button(action_row, text="预览成片首帧", command=lambda: self.load_selected_preview(rendered=True)).pack(side="left", padx=(8, 0))
        ttk.Button(action_row, text="生成 5 秒成片预览", command=self.generate_preview_clip).pack(side="left", padx=(8, 0))
        self.preview_status = StringVar(value="")
        ttk.Label(self.preview_tab, textvariable=self.preview_status, style="Muted.TLabel").grid(row=4, column=0, sticky="ew", pady=(10, 0))

    def _build_review_tab(self) -> None:
        self.review_tab.columnconfigure(0, weight=1)
        ttk.Label(
            self.review_tab,
            text="烧录前先校对翻译。保存后自动重建 SRT/ASS，再渲染当前视频。",
            style="Panel.TLabel",
        ).grid(row=0, column=0, sticky="ew")
        ttk.Button(self.review_tab, text="打开当前视频的翻译校对", command=self.open_translation_review).grid(
            row=1, column=0, sticky="w", pady=(14, 0)
        )

    def _build_env_tab(self) -> None:
        import tkinter as tk

        self.env_tab.columnconfigure(0, weight=1)
        self.env_tab.rowconfigure(1, weight=1)
        top = ttk.Frame(self.env_tab, style="Panel.TFrame")
        top.grid(row=0, column=0, sticky="ew")
        ttk.Label(top, textvariable=self.env_status, style="Panel.TLabel").pack(side="left")
        ttk.Button(top, text="重新自检", command=self.run_environment_check).pack(side="right")
        self.env_text = tk.Text(
            self.env_tab,
            wrap="word",
            bg="#0f1217",
            fg="#d6dde7",
            relief="flat",
            padx=10,
            pady=8,
        )
        self.env_text.grid(row=1, column=0, sticky="nsew", pady=(12, 0))

    def _build_log_tab(self) -> None:
        import tkinter as tk

        self.log_tab.columnconfigure(0, weight=1)
        self.log_tab.rowconfigure(0, weight=1)
        self.log = tk.Text(
            self.log_tab,
            wrap="word",
            bg="#0f1217",
            fg="#d6dde7",
            insertbackground="#d6dde7",
            relief="flat",
            padx=10,
            pady=8,
        )
        scrollbar = ttk.Scrollbar(self.log_tab, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=scrollbar.set)
        self.log.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

    def selected_input(self) -> Path | None:
        selected = self.queue_list.curselection()
        if selected:
            return self.input_files[selected[0]]
        if self.input_files:
            return self.input_files[0]
        return None

    def add_files(self) -> None:
        filenames = filedialog.askopenfilenames(
            title="选择视频或音频",
            filetypes=[("Media files", "*.mp4 *.mov *.mkv *.avi *.mp3 *.wav *.m4a"), ("All files", "*.*")],
        )
        for filename in filenames:
            path = Path(filename)
            if path not in self.input_files:
                self.input_files.append(path)
                self.queue_list.insert("end", path.name)
        if self.input_files and not self.queue_list.curselection():
            self.queue_list.selection_set(0)
            self._queue_selected()

    def remove_selected(self) -> None:
        selected = list(self.queue_list.curselection())
        for index in reversed(selected):
            self.queue_list.delete(index)
            del self.input_files[index]
        if self.input_files:
            self.queue_list.selection_set(min(selected[0] if selected else 0, len(self.input_files) - 1))
            self._queue_selected()
        else:
            self.file_path.set("")
            self._draw_empty_preview()

    def clear_queue(self) -> None:
        self.input_files.clear()
        self.queue_list.delete(0, "end")
        self.file_path.set("")
        self._draw_empty_preview()

    def _queue_selected(self, _event=None) -> None:
        path = self.selected_input()
        if not path:
            return
        self.file_path.set(str(path))
        self.load_preview(path)

    def load_selected_preview(self, rendered: bool) -> None:
        path = self.selected_input()
        if not path:
            messagebox.showinfo("暂无素材", "请先添加一个视频。")
            return
        target = artifact_paths(path)["video"] if rendered else path
        if not target.exists():
            messagebox.showinfo("暂无成片", f"还没有找到：\n{target}")
            return
        self.load_preview(target)

    def load_preview(self, media_path: Path) -> None:
        if not DEFAULT_FFMPEG.exists():
            self.status.set("未找到 ffmpeg，无法生成预览")
            return
        paths = artifact_paths(media_path)
        preview_path = paths["preview_frame"]
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            str(DEFAULT_FFMPEG),
            "-y",
            "-hide_banner",
            "-ss",
            "0",
            "-i",
            str(media_path),
            "-frames:v",
            "1",
            "-vf",
            "scale=-2:420",
            str(preview_path),
        ]
        completed = subprocess.run(command, cwd=PROJECT_ROOT, check=False, capture_output=True, text=True)
        if completed.returncode != 0 or not preview_path.exists():
            self.status.set("预览生成失败")
            return

        import tkinter as tk

        self.preview_source = media_path
        self.preview_image = tk.PhotoImage(file=str(preview_path))
        self.preview_image_size = (self.preview_image.width(), self.preview_image.height())
        x = (self.preview_width - self.preview_image_size[0]) // 2
        y = (self.preview_height - self.preview_image_size[1]) // 2
        self.preview_origin = (x, y)
        self.canvas.delete("all")
        self.canvas.create_image(x, y, image=self.preview_image, anchor="nw")
        self._draw_subtitle_marker()
        self.status.set("预览已就绪")
        self.preview_status.set(str(media_path))

    def generate_preview_clip(self) -> None:
        path = self.selected_input()
        if not path:
            messagebox.showinfo("暂无素材", "请先添加一个视频。")
            return
        rendered = artifact_paths(path)["video"]
        if not rendered.exists():
            messagebox.showinfo("暂无成片", "还没有渲染好的成片，先跑完队列再生成预览片段。")
            return
        output = artifact_paths(path)["preview_clip"]
        command = [str(DEFAULT_FFMPEG), "-y", "-hide_banner", "-i", str(rendered), "-t", "5", "-c", "copy", str(output)]
        completed = subprocess.run(command, cwd=PROJECT_ROOT, check=False, capture_output=True, text=True)
        if completed.returncode != 0:
            command = [str(DEFAULT_FFMPEG), "-y", "-hide_banner", "-i", str(rendered), "-t", "5", str(output)]
            completed = subprocess.run(command, cwd=PROJECT_ROOT, check=False, capture_output=True, text=True)
        if completed.returncode == 0:
            self.preview_status.set(f"已生成：{output}")
        else:
            messagebox.showerror("预览生成失败", completed.stdout + completed.stderr)

    def _draw_empty_preview(self) -> None:
        self.canvas.delete("all")
        self.canvas.create_text(
            self.preview_width / 2,
            self.preview_height / 2,
            text="导入视频后显示首帧",
            fill="#697386",
            font=("Segoe UI", 13),
        )
        self._draw_subtitle_marker()

    def _position_combo_changed(self, _event=None) -> None:
        if self.subtitle_position_label.get() == CUSTOM_POSITION_LABEL:
            self._set_custom_position_hint(selected=False)
            self.status.set("点击预览选择字幕位置")
            return
        self._set_custom_position_hint(active=False)
        _position, fraction = SUBTITLE_POSITIONS[self.subtitle_position_label.get()]
        self.subtitle_y.set(fraction)
        self._update_position_label()
        self._draw_subtitle_marker()

    def _subtitle_mode_changed(self, _event=None) -> None:
        self._update_position_label()
        self._draw_subtitle_marker()

    def _preview_clicked(self, event) -> None:
        x0, y0 = self.preview_origin
        width, height = self.preview_image_size
        if width and height and y0 <= event.y <= y0 + height:
            fraction = (event.y - y0) / max(1, height)
        else:
            fraction = event.y / self.preview_height
        fraction = min(0.90, max(0.05, fraction))
        if self.is_bilingual_mode():
            source_distance = abs(event.y - self._marker_canvas_y("source"))
            chinese_distance = abs(event.y - self._marker_canvas_y("chinese"))
            if source_distance < chinese_distance:
                self.source_y.set(fraction)
            else:
                self.subtitle_y.set(fraction)
        else:
            self.subtitle_y.set(fraction)
        self.subtitle_position_label.set(CUSTOM_POSITION_LABEL)
        self._set_custom_position_hint(selected=True)
        self._update_position_label()
        self._draw_subtitle_marker()

    def _draw_subtitle_marker(self) -> None:
        self.canvas.delete("subtitle_marker")
        if self.is_bilingual_mode():
            source_y = self._marker_canvas_y("source")
            self.canvas.create_line(28, source_y, self.preview_width - 28, source_y, fill="#ffffff", width=2, tags="subtitle_marker")
            self.canvas.create_text(
                self.preview_width / 2,
                source_y - 16,
                text="原文字幕",
                fill="#ffffff",
                font=("Segoe UI", 12, "bold"),
                tags="subtitle_marker",
            )
        y = self._marker_canvas_y("chinese")
        self.canvas.create_line(28, y, self.preview_width - 28, y, fill="#f4d35e", width=2, tags="subtitle_marker")
        self.canvas.create_text(
            self.preview_width / 2,
            y - 18,
            text="中文字幕",
            fill="#f4d35e",
            font=("Microsoft YaHei", 14, "bold"),
            tags="subtitle_marker",
        )

    def _marker_canvas_y(self, language: str = "chinese") -> float:
        _x0, y0 = self.preview_origin
        _width, height = self.preview_image_size
        fraction = self.source_y.get() if language == "source" else self.subtitle_y.get()
        if height:
            return y0 + height * fraction
        return self.preview_height * fraction

    def _update_position_label(self) -> None:
        if self.is_bilingual_mode():
            self.position_text.set(f"原文：{self.source_y.get() * 100:.0f}% · 中文：{self.subtitle_y.get() * 100:.0f}%")
        else:
            self.position_text.set(f"字幕位置：{self.subtitle_y.get() * 100:.0f}%")

    def _set_custom_position_hint(self, active: bool = True, selected: bool = False) -> None:
        if not active:
            self.position_hint.set("")
            self.preview_hint_label.configure(text="")
            self.position_hint_label.grid_remove()
            self.preview_hint_label.pack_forget()
            return
        text = "已选择，可继续点击微调" if selected else "点击预览选择位置"
        if self.is_bilingual_mode() and not selected:
            text = "点击靠近对应指示线的位置，分别调整原文和中文字幕"
        self.position_hint.set(text)
        self.preview_hint_label.configure(text=text)
        self.position_hint_label.grid()
        if not self.preview_hint_label.winfo_ismapped():
            self.preview_hint_label.pack(side="right")

    def is_bilingual_mode(self) -> bool:
        return SUBTITLE_MODES.get(self.subtitle_mode_label.get()) == "bilingual"

    def build_args_for(self, input_path: Path) -> argparse.Namespace:
        position_label = self.subtitle_position_label.get()
        subtitle_position = SUBTITLE_POSITIONS.get(position_label, ("center", self.subtitle_y.get()))[0]
        return argparse.Namespace(
            input=input_path,
            language=LANGUAGE_CODES[self.language_label.get()],
            subtitle_mode=SUBTITLE_MODES[self.subtitle_mode_label.get()],
            subtitle_position=subtitle_position,
            subtitle_y=self.subtitle_y.get(),
            source_y=self.source_y.get() if self.is_bilingual_mode() else None,
            watermark=self.watermark.get() if self.use_watermark.get() else "",
            translation_gpu_layers="auto" if self.gpu.get() else "0",
            translation_batch_size=4,
            force=self.force.get(),
            skip_render=RENDER_POLICIES[self.render_policy_label.get()],
        )

    def render_args_for(self, input_path: Path) -> argparse.Namespace:
        args = self.build_args_for(input_path)
        args.skip_render = False
        args.force = False
        return args

    def start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if not self.input_files:
            messagebox.showwarning("Missing file", "请先添加至少一个视频或音频文件。")
            return

        self.log.delete("1.0", "end")
        self.run_button.configure(state="disabled")
        self.reset_steps()
        jobs = [self.build_args_for(path) for path in self.input_files]
        for index, job in enumerate(jobs):
            job.queue_index = index
        self.worker = threading.Thread(target=self._run_queue_worker, args=(jobs,), daemon=True)
        self.worker.start()

    def render_selected(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        path = self.selected_input()
        if not path:
            messagebox.showinfo("暂无素材", "请先从队列里选择一个视频。")
            return
        paths = artifact_paths(path)
        if not paths["zh"].exists() or not paths["ass"].exists():
            messagebox.showinfo("还不能渲染", "还没有翻译 JSON 和字幕文件。请先处理队列到翻译/字幕文件阶段。")
            return
        self.log.delete("1.0", "end")
        self.run_button.configure(state="disabled")
        self.reset_steps()
        args = self.render_args_for(path)
        selected = self.queue_list.curselection()
        args.queue_index = selected[0] if selected else 0
        self.worker = threading.Thread(target=self._run_queue_worker, args=([args],), daemon=True)
        self.worker.start()

    def _run_queue_worker(self, jobs: list[argparse.Namespace]) -> None:
        for job_index, args in enumerate(jobs):
            queue_index = getattr(args, "queue_index", job_index)
            self.events.put(("job_start", (job_index, len(jobs), args.input, queue_index)))
            command = build_pipeline_command(args)
            self.events.put(("log", " ".join(command) + "\n\n"))
            process = subprocess.Popen(
                command,
                cwd=PROJECT_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            assert process.stdout is not None
            for line in process.stdout:
                self.events.put(("line", line))
            returncode = process.wait()
            self.events.put(("job_done", (job_index, returncode, args.input, args.skip_render)))
            if returncode != 0:
                break
        self.events.put(("queue_done", None))

    def classify_step(self, line: str) -> str | None:
        if "subtitle streams" in line or "Hardcoded visual subtitles" in line:
            return "subtitles"
        if "transcribe.py" in line or "Transcribing:" in line or "Using existing transcript" in line:
            return "transcribe"
        if "translate.py" in line or "Translating batch" in line or "Using existing translation" in line:
            return "translate"
        if "make_srt.py" in line or "Wrote:" in line or "Using existing subtitles" in line:
            return "subtitle_files"
        if "--skip-render" in line:
            return "render"
        if "render_video.py" in line or "Using existing rendered video" in line:
            return "render"
        return None

    def reset_steps(self) -> None:
        for key, name in PIPELINE_STEPS:
            self.step_vars[key].set(f"○ {name}")

    def mark_step(self, key: str, state: str = "running") -> None:
        names = dict(PIPELINE_STEPS)
        if state == "running":
            prefix = "●"
        elif state == "skipped":
            prefix = "—"
        else:
            prefix = "✓"
        self.step_vars[key].set(f"{prefix} {names[key]}")

    def open_translation_review(self) -> None:
        path = self.selected_input()
        if not path:
            messagebox.showinfo("暂无素材", "请先从队列里选择一个视频。")
            return
        TranslationReviewWindow(self, path)

    def run_environment_check(self) -> None:
        self.env_status.set("环境自检中")
        self.env_text.delete("1.0", "end")
        threading.Thread(target=self._environment_worker, daemon=True).start()

    def _environment_worker(self) -> None:
        checks: list[tuple[str, bool, str]] = []
        checks.append(("ffmpeg", DEFAULT_FFMPEG.exists(), str(DEFAULT_FFMPEG)))
        checks.append(("ffprobe", DEFAULT_FFPROBE.exists(), str(DEFAULT_FFPROBE)))
        checks.append(("llama-cli", DEFAULT_LLAMA_CLI.exists(), str(DEFAULT_LLAMA_CLI)))
        checks.append(("translation model", DEFAULT_MODEL.exists(), str(DEFAULT_MODEL)))

        py_check = subprocess.run(
            [sys.executable, "-c", "import faster_whisper; print('ok')"],
            cwd=PROJECT_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        checks.append(("faster-whisper", py_check.returncode == 0, py_check.stdout.strip() or py_check.stderr.strip()))

        try:
            gpu_check = subprocess.run(["nvidia-smi", "-L"], cwd=PROJECT_ROOT, check=False, capture_output=True, text=True)
            gpu_ok = gpu_check.returncode == 0
            gpu_detail = gpu_check.stdout.strip() or gpu_check.stderr.strip() or "未检测到 nvidia-smi"
        except FileNotFoundError:
            gpu_ok = False
            gpu_detail = "未检测到 nvidia-smi"
        checks.append(("NVIDIA GPU", gpu_ok, gpu_detail))

        lines = []
        ok_count = 0
        for name, ok, detail in checks:
            ok_count += int(ok)
            lines.append(f"{'OK' if ok else 'MISS'}  {name}\n  {detail}\n")
        summary = f"环境自检：{ok_count}/{len(checks)} 项可用"
        self.events.put(("env", (summary, "\n".join(lines))))

    def _poll_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self.log.insert("end", str(payload))
                    self.log.see("end")
                elif kind == "line":
                    line = str(payload)
                    self.log.insert("end", line)
                    self.log.see("end")
                    step = self.classify_step(line)
                    if step:
                        self.mark_step(step, "running")
                elif kind == "job_start":
                    job_index, total, path, queue_index = payload
                    self.current_job_index = job_index
                    self.status.set(f"处理中 {job_index + 1}/{total}: {Path(path).name}")
                    self.reset_steps()
                    self.queue_list.selection_clear(0, "end")
                    if self.input_files:
                        queue_index = min(queue_index, len(self.input_files) - 1)
                        self.queue_list.selection_set(queue_index)
                        self.queue_list.see(queue_index)
                elif kind == "job_done":
                    _job_index, returncode, path, skipped_render = payload
                    if returncode == 0:
                        for key, _name in PIPELINE_STEPS:
                            if key == "render" and skipped_render:
                                self.mark_step(key, "skipped")
                            else:
                                self.mark_step(key, "done")
                        if skipped_render:
                            self.status.set(f"等待校对：{Path(path).name}")
                        else:
                            self.status.set(f"完成：{Path(path).name}")
                    else:
                        self.status.set(f"失败：{Path(path).name} · exit {returncode}")
                elif kind == "queue_done":
                    self.run_button.configure(state="normal")
                elif kind == "env":
                    summary, text = payload
                    self.env_status.set(summary)
                    self.env_text.delete("1.0", "end")
                    self.env_text.insert("1.0", text)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)

    def run(self) -> None:
        self.root.mainloop()


def launch_gui() -> int:
    PipelineGui().run()
    return 0


def main() -> int:
    args = parse_args()
    if args.gui or args.input is None:
        return launch_gui()
    return run_pipeline(args)


if __name__ == "__main__":
    raise SystemExit(main())
