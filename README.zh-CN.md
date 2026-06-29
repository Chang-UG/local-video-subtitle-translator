# 本地视频字幕翻译工具

[English](README.md) | [简体中文](README.zh-CN.md)

一个本地优先的视频字幕工具：转写视频语音，将字幕翻译成中文，人工审核翻译文本，并把中文或双语字幕烧录进最终视频。

当前 MVP：

```text
音频/视频文件
-> faster-whisper
-> 转写文本
-> srt 字幕
-> 用于对齐翻译校对的 segment json
-> 本地 llama.cpp 翻译
-> 烧录中文或双语字幕的视频
```

## 项目结构

```text
local_video_subtitle_translator/
+-- input/
+-- models/
+-- transcript/
+-- output/
+-- scripts/
+-- main.py
```

典型输出：

- `output/lecture/lecture.segments.json`
- `output/lecture/lecture.zh.json`
- `output/lecture/lecture.bilingual.txt`
- `output/lecture/lecture.bilingual.srt`
- `output/lecture/lecture.bilingual.ass`
- `output/lecture/lecture_bilingual_subs.mp4`

## 环境

本地 Conda 环境：

```powershell
D:\anaconda3\Scripts\conda.exe activate vibecoding
```

在另一台机器上重建环境：

```powershell
D:\anaconda3\Scripts\conda.exe env create -f environment.yml
```

## 转写

把源视频或音频放进 `input/`，然后运行：

```powershell
D:\anaconda3\envs\vibecoding\python.exe scripts\transcribe.py input\lecture.mp4
```

默认使用 CPU `int8`，比 GPU 慢，但不需要 CUDA。

指定源语言：

```powershell
D:\anaconda3\envs\vibecoding\python.exe scripts\transcribe.py input\lecture.mp4 --language nl
D:\anaconda3\envs\vibecoding\python.exe scripts\transcribe.py input\lecture.mp4 --language en
D:\anaconda3\envs\vibecoding\python.exe scripts\transcribe.py input\lecture.mp4 --language zh
```

输出会写入 `transcript/`：

- `transcript/lecture.txt`
- `transcript/lecture.srt`
- `transcript/lecture.segments.json`

CPU 友好运行方式：

```powershell
D:\anaconda3\envs\vibecoding\python.exe scripts\transcribe.py input\lecture.mp4 --device cpu --compute-type int8
```

正确安装 CUDA/cuBLAS 后可尝试 GPU：

```powershell
D:\anaconda3\envs\vibecoding\python.exe scripts\transcribe.py input\lecture.mp4 --device cuda --compute-type float16
```

第一次使用某个 Whisper 模型时会从 Hugging Face 下载模型文件；后续会使用本地缓存。

## 集成入口

最简单的入口是 `main.py`。

打开 GUI：

```powershell
D:\anaconda3\envs\vibecoding\python.exe main.py
```

或：

```powershell
D:\anaconda3\envs\vibecoding\python.exe main.py --gui
```

从命令行运行完整流程：

```powershell
D:\anaconda3\envs\vibecoding\python.exe main.py input\lecture.mp4 --language nl --subtitle-mode chinese --subtitle-position center --force
```

常用选项：

- `--language auto|nl|en|zh|fr|es|de|it|pt|ja|ko|ru|ar|hi`
- `--subtitle-source audio|external-srt`
- `--source-srt path\to\subtitle.srt` 使用外部 SRT 时指定字幕文件
- `--subtitle-mode chinese|bilingual`
- `--subtitle-position upper|center|lower`
- `--subtitle-y 0.55` 精确控制字幕垂直位置
- `--source-y 0.32` 在双语模式里精确控制原文字幕位置
- `--watermark "上北下南的东"` 或用 `--watermark ""` 关闭水印
- `--translation-gpu-layers auto`
- `--skip-render` 只生成转写、翻译、SRT 和 ASS，不直接烧录视频
- `--force` 重新生成已有中间文件

GUI 是一个队列式工作台：

- 添加多个媒体文件并按队列批量处理
- 选择字幕来源：从视频音轨转写，或使用外部 SRT 文件
- 按步骤查看进度：字幕检测、转写、翻译、字幕文件、视频烧录
- 选择直接渲染成片，或先生成字幕文件并等待翻译校对
- 环境自检：ffmpeg、ffprobe、llama-cli、本地 GGUF 模型、faster-whisper、NVIDIA GPU
- 预览原片首帧、成片首帧，或生成 5 秒成片预览片段
- 双语模式下会显示原文/中文字幕两条指示线，点击靠近哪条线就调整哪种语言
- 打开翻译校对窗口，编辑原文/中文字幕 segment，然后校对后渲染当前视频

## 翻译

翻译优先走离线流程，使用 `llama.cpp` 的 `llama-cli`。

推荐使用小体量、支持中文的 instruct GGUF 模型，例如 Qwen2.5/Qwen3 1.5B 或 3B Instruct 的 Q4/Q5 量化版本。

当前本地模型路径：

- `models/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf`

用本地 GGUF 模型翻译对齐后的转写片段：

```powershell
D:\anaconda3\envs\vibecoding\python.exe scripts\translate.py transcript\lecture.segments.json --model models\Qwen2.5-1.5B-Instruct-Q4_K_M.gguf
```

可用时启用 GPU offload：

```powershell
D:\anaconda3\envs\vibecoding\python.exe scripts\translate.py transcript\lecture.segments.json --model models\Qwen2.5-1.5B-Instruct-Q4_K_M.gguf --gpu-layers auto
```

`translate.py` 会优先使用 `vibecoding` Conda 环境里的 `llama-cli.exe`。也可以手动指定：

```powershell
D:\anaconda3\envs\vibecoding\python.exe scripts\translate.py transcript\lecture.segments.json --model models\Qwen2.5-1.5B-Instruct-Q4_K_M.gguf --llama-cli path\to\llama-cli.exe
```

输出：

- `transcript/lecture.zh.json`
- `transcript/lecture.bilingual.txt`

双语 TXT 会把每段原文和中文翻译放在一起，方便审核；最终样式字幕不依赖 TXT。

字幕流程尽量保持本地：

- 字幕生成：Python 脚本
- 样式字幕烧录：ffmpeg + ASS/libass
- 翻译：本地 `llama-cli` + GGUF 模型

## 字幕格式

SRT 作为通用兼容字幕：

```text
1
00:00:00,000 --> 00:00:03,000
Original line
Chinese translation line
```

SRT 在不同播放器中不可靠支持逐行颜色、字体或位置。双语字幕如果需要不同颜色或不同位置，使用 ASS：

```text
Dialogue: 0,0:00:00.00,0:00:03.00,Source,,0,0,0,,Original line
Dialogue: 0,0:00:00.00,0:00:03.00,Chinese,,0,0,0,,Chinese translation line
```

## 一步生成烧录字幕视频

对源视频运行完整本地流程：

```powershell
D:\anaconda3\envs\vibecoding\python.exe scripts\process_bilingual_subs.py input\lecture.mp4 --language nl
```

如果已经有原文 SRT，可以跳过音频转写，直接使用外部 SRT：

```powershell
D:\anaconda3\envs\vibecoding\python.exe scripts\process_bilingual_subs.py input\lecture.mp4 --subtitle-source external-srt --source-srt input\lecture.nl.srt --language nl
```

在完整流程里使用 GPU 翻译：

```powershell
D:\anaconda3\envs\vibecoding\python.exe scripts\process_bilingual_subs.py input\lecture.mp4 --language nl --translation-gpu-layers auto
```

手机录屏素材可以先裁掉固定顶部/底部 UI：

```powershell
D:\anaconda3\envs\vibecoding\python.exe scripts\process_bilingual_subs.py input\lecture.mp4 --language nl --clean-recording
```

录屏清理会裁掉固定顶部/底部 UI，再用白边补回原尺寸，避免画面被拉伸。也可以手动调参数：

```powershell
D:\anaconda3\envs\vibecoding\python.exe scripts\process_bilingual_subs.py input\lecture.mp4 --language nl --clean-recording --clean-top 120 --clean-bottom 180
```

输出：

- `output/lecture/lecture.segments.json`
- `output/lecture/lecture.zh.json`
- `output/lecture/lecture.bilingual.txt`
- `output/lecture/lecture.bilingual.srt`
- `output/lecture/lecture.bilingual.ass`
- `output/lecture/lecture_bilingual_subs.mp4`

流程会先用 `ffprobe` 检查视频容器里是否有内嵌字幕流。它可以检测真正的 subtitle stream，但不能可靠检测已经硬烧在画面里的字幕。硬字幕自动检测以后需要 OCR。

当前默认烧录模式是仅中文字幕，黄色中文字幕放在竖屏社交视频的视觉安全中部。渲染双语字幕：

```powershell
D:\anaconda3\envs\vibecoding\python.exe scripts\process_bilingual_subs.py input\lecture.mp4 --language nl --subtitle-mode bilingual
```

选择字幕位置：

```powershell
D:\anaconda3\envs\vibecoding\python.exe scripts\process_bilingual_subs.py input\lecture.mp4 --language nl --subtitle-position upper
D:\anaconda3\envs\vibecoding\python.exe scripts\process_bilingual_subs.py input\lecture.mp4 --language nl --subtitle-position center
D:\anaconda3\envs\vibecoding\python.exe scripts\process_bilingual_subs.py input\lecture.mp4 --language nl --subtitle-position lower
D:\anaconda3\envs\vibecoding\python.exe scripts\process_bilingual_subs.py input\lecture.mp4 --language nl --subtitle-y 0.55
D:\anaconda3\envs\vibecoding\python.exe scripts\process_bilingual_subs.py input\lecture.mp4 --language nl --subtitle-mode bilingual --source-y 0.32 --subtitle-y 0.58
```

完整流程默认添加一个很浅的浮动水印：

```text
上北下南的东
```

关闭水印：

```powershell
D:\anaconda3\envs\vibecoding\python.exe scripts\process_bilingual_subs.py input\lecture.mp4 --language nl --watermark ""
```

当前 Conda ffmpeg build 不包含 `ass/subtitles` filter，所以 `render_video.py` 会自动 fallback 到 `drawtext`。

## 许可证

本项目使用 MIT License。详情见 [LICENSE](LICENSE)。

本仓库不包含、也不授予任何第三方模型权重、媒体文件、字体或二进制文件的使用权。用户需要自行确保其使用的所有第三方组件和源素材符合相应许可证与服务条款。

自动生成的转写、翻译和字幕可能包含错误。在专业、商业、法律、医疗、教育或公开使用前，应先进行人工审核。
