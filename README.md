# realtime-subtitle (moiku fork: JA → EN lecture subtitles)

Fork of [Vanyoo/realtime-subtitle](https://github.com/Vanyoo/realtime-subtitle) tuned for live English subtitles of Japanese university lectures. Changes from upstream:

- **Glossary-driven translation**: course glossaries (Markdown tables `| 日本語 | English |` or YAML) are injected into the translation prompt; a short hint list biases Whisper via `initial_prompt`.
- **Lecture-aware prompt**: drops fillers, keeps self-corrections, reads `X分のY` as Y/X, keeps negations; last 3 segments as context; translation serialized so context stays in order.
- **Segmentation for lecture speech**: short buffers are merged unless there is a long pause, so a word split by a pause (確率…関数) is recognized as one.
- **Hallucination filters** for Japanese (repetition loops, 「ご視聴ありがとうございました」, low-confidence segments).
- **Session logs**: `transcripts/<timestamp>/{audio.wav, segments.jsonl, meta.json}`.
- `simulate.py` runs the pipeline on a recording; `reprocess.py` re-transcribes (large-v3) and re-translates a session into `refined.jsonl` + `.srt`.
- uv-managed; `OPENAI_API_KEY` is read from `~/.secrets/api_keys.env` and never written to `config.ini`.

## Quick start (macOS, Apple Silicon)

```bash
brew install uv
./install_mac.sh          # uv sync + creates config.ini
./start_mac.sh            # dashboard -> Launch Translator
```

Microphone input is the default. Edit `config.ini` → `[glossary] files` to point to your course glossary.

```bash
# Try the pipeline on a recording (16 kHz mono WAV)
ffmpeg -i lecture.mp4 -vn -ac 1 -ar 16000 lecture.wav
uv run python simulate.py lecture.wav --start 1500 --duration 120
# After class: reference transcript/translation + SRT
uv run python reprocess.py transcripts/<timestamp>
```

---

*Upstream README follows.*

# Real-Time Translator 🎙️➡️🇨🇳

A high-performance real-time speech-to-text and translation application built for macOS (Apple Silicon optimized).

## Features
- **⚡️ Real-Time Transcription**: Instant streaming display using `faster-whisper`, `mlx-whisper`, or `FunASR`.
- **🎯 Multiple ASR Backends**: Choose between Whisper (multilingual), MLX (Apple Silicon optimized), or FunASR (industrial-grade Chinese/English).
- **🌊 Word-by-Word Streaming**: See text appear as you speak, with smart context accumulation.
- **🔄 Async Translation**: Translates text to Chinese (or target language) in the background without blocking the UI.
- **🖥️ Overlay UI**: Always-on-top, transparent, click-through window for seamless usage during meetings/videos.
- **⚙️ Hot Reloading**: Change code or config and the app restarts automatically.
- **💾 Transcript Saving**: One-click save of your session history. Can be used as subtitle or LLM analyze.

## Demo
https://github.com/user-attachments/assets/9982fe5d-3937-42d5-bcfc-e23748c01edf

![Dashboard](./demo/main_dashboard.png)

## Installation

1. **Prerequisites**:
   - Python 3.10+
   - macOS (recommended for `mlx-whisper` support)
   - `ffmpeg` installed (e.g., `brew install ffmpeg`)
   - `BlackHole` installed (e.g., `brew install blackhole-2ch`, need to enter system password)
   - `BlackHole` Settings![BlackHole Settings](demo/how_to_set_blackhole.png)

2. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
   
   *(Ensure you have `PyQt6`, `sounddevice`, `numpy`, `openai`, `watchdog` installed)*

   **🪟 Windows Users**:
   1. Double-click `install_windows.bat` to automatically set up the environment.
   2. Ensure [FFmpeg](https://ffmpeg.org/download.html) is installed and added to your PATH.

   **🖥 MacOS Users**:
   1. Use terminal to run `install_mac.sh`

## ✨ New Features & Quick Start
- **Modern Control Center**: Manage all settings in a dark-themed Dashboard.
- **One-Click Launch**: Start the overlay translator directly from the Dashboard.
- **Auto-Dependency Check**: Automatically installs missing requirements.
- **Audio Device Selection**: Choose your specific microphone input.

## Usage

### 1. Start the Application
Run the helper script for your OS:
- **Mac/Linux**: `./start_mac.sh`
- **Windows**: `start_windows.bat`

### 2. The Dashboard
The application opens the **Real-Time Translator Control Center**.
- **Home**: Click **"▶ Launch Translator"** to start the overlay.
- **Audio**: Select your Input Device and adjust Silence Threshold.
  * <details>
     <summary>How to Set</summary>
     1. Audio MIDI Setup: create multiple devices, including `BlackHole 2ch` device, and if you want to listen too, remember adding system output device

     ![](./demo/Audio_MIDI_Setup.png)

     2. Choose target audio device to capture

     ![](./demo/Audio_configuraiton.png)
   </details>
- **Transcription**: Choose Whisper model size (tiny, base, small, medium, large-v3, [see the difference](https://github.com/openai/whisper?tab=readme-ov-file#available-models-and-languages)).
  * <details>
     <summary>How to Set</summary>
     
     * MacOS
       * Whisper Model: base
       * Compute Device: audo
       * Quantization: float16
   </details>
- **Translation**: Set your OpenAI API Key and Target Language.
- **Save Settings**: Click "Save Settings" to persist your configuration.

### 3. The Overlay
Once launched, a transparent window appears:
- **Move**: Click and drag text to move.
- **Resize**: Drag the bottom-right handle (◢).
- **Stop**: Click **"⏹"** on the overlay or "Stop Translator" in the Dashboard.
- **Save**: Click **"💾 Save"** to export transcript.

## ⚙️ Configuration Reference
Settings are managed via the Dashboard, but stored in `config.ini`.

#### `[api]` Section
| Parameter | Description | Examples |
| :--- | :--- | :--- |
| `base_url` | API Endpoint | `https://api.openai.com/v1`, `http://localhost:11434/v1` |
| `api_key` | Auth Key | `sk-...` (or `dummy` for local) |
| `target_lang` | Output Language | `Chinese`, `English`, `Japanese` |

#### `[transcription]` Section
| Parameter | Description | Details |
| :--- | :--- | :--- |
| `backend` | ASR Engine | `whisper` (default), `mlx` (Apple Silicon), `funasr` (Alibaba) |
| `whisper_model` | Whisper Model Size | `tiny` (fast), `large-v3` (accurate) |
| `funasr_model` | FunASR Model Name | `paraformer-zh` (Chinese), `SenseVoiceSmall` (Multi-lang) |
| `device` | Compute Unit | `auto` (Apple Neural Engine), `cuda` (NVIDIA) |

#### `[audio]` Section
| Parameter | Description | Details |
| :--- | :--- | :--- |
| `silence_threshold`| Sensitivity | `0.005` (Quiet) to `0.05` (Loud) |
| `device_index` | Mic ID | `auto` or specific index `0`, `1`... |

## Troubleshooting
- **No Audio?** Check the terminal for "Audio Capture" logs. If using BlackHole, ensure it's selected in `config.ini` or auto-detected.
- **Resize not working?** Use the designated "◢" handle in the bottom-right.
- **Hot Reload**: Modify any `.py` file or save settings in the UI to trigger a reload.

## 🎯 Using FunASR (NEW!)

FunASR is Alibaba's industrial-grade ASR toolkit with excellent Chinese language support.

**Quick Start:**
1. Set backend to `funasr` in Settings or `config.ini`
2. Choose a FunASR model (e.g., `iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch` for Chinese)
3. Models auto-download on first use from ModelScope

**Recommended Models:**
- **Chinese (Offline)**: `iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch`
- **Chinese (Streaming)**: `iic/speech_paraformer_asr_nat-zh-cn-16k-common-vocab8404-online`
- **English (Streaming)**: `iic/speech_UniASR_asr_2pass-en-16k-common-vocab1080-tensorflow1-online`
- **Multi-language**: `iic/SenseVoiceSmall` or `FunAudioLLM/SenseVoiceSmall`
- **Latest 31-language model**: `FunAudioLLM/Fun-ASR-Nano-2512` (Supports dialects, accents, lyrics)

**Note**: FunASR model names must include the namespace (e.g., `iic/` or `FunAudioLLM/`)


## License: MIT
Copyright 2025 Van

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the “Software”), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
