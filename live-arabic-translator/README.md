# Live Arabic Translator — مترجم فوري للعربية

A Python desktop tool that **listens only to the sound playing on your PC**
(YouTube, any video player, Zoom/Teams, podcasts…) and shows **live Arabic
subtitles** in a small always-on-top window.

It records the *speaker output* via loopback, **not the microphone**, so
voices and noise in the room are never picked up.

```
PC audio (loopback) → speech chunks → Whisper (speech-to-text, any language)
                    → Claude (natural, well-organised Arabic) → subtitle window
```

## Features
- Captures only system audio (WASAPI loopback on Windows, PulseAudio monitor on Linux).
- Auto-detects the spoken language (English, French, Spanish, Hindi, Turkish, ~100 languages).
- High-quality Modern Standard Arabic translation with Claude: fixes speech
  fillers, uses proper Arabic punctuation, keeps names/terms accurate, and uses
  the last few lines as context so the subtitles read consistently.
- Free fallback (Google, then MyMemory) when no Claude API key is set.
- Show/hide the original text, clear, and save the full transcript to a `.txt` file.

## Install (Windows)
1. Install **Python 3.10+** from python.org (tick *Add Python to PATH*).
2. (Recommended, best translation) get an API key from https://console.anthropic.com and set it:
   ```bat
   setx ANTHROPIC_API_KEY "sk-ant-..."
   ```
   then open a new terminal. Without a key the tool uses free Google Translate.
3. Double-click **`run_windows.bat`**. The first run installs the packages and
   downloads the Whisper model (~500 MB for `small`).

Manual install on any OS:
```bash
pip install -r requirements.txt
python live_translator.py
```

## Use
1. Press **▶ Start** (wait for "Listening to: …").
2. Play any video or audio on the PC. Arabic subtitles appear a few seconds after each sentence.
3. Press **■ Stop** when done; **Save transcript** writes a text file.

## Launchers (Windows)
| File | Best for |
|---|---|
| `run_gpu.bat` | **NVIDIA GPU laptops** (e.g. RTX 3060): speech runs on the GPU, almost no CPU load. Installs the NVIDIA cuBLAS library once. |
| `run_windows.bat` | Uses the GPU if it is ready, otherwise the CPU. |
| `run_fast.bat` | Laptops without NVIDIA: lightest CPU settings. |

Defaults are tuned for live use: Whisper `small` on GPU / `base` on CPU,
translation with **Claude Haiku 5.5** (fastest), half the CPU cores at most,
whole sentences shown one by one.

## Options
| Option | Meaning |
|---|---|
| `--model small` | Speech model: `tiny`, `base`, `small`, `medium`, `large-v3-turbo` (bigger = more accurate, heavier). |
| `--compute cuda` / `cpu` | Force GPU or CPU (default `auto`). |
| `--cpu-threads 2` | CPU threads for speech on CPU (fewer = lighter). |
| `--claude-model claude-opus-5-5` | Most polished Arabic (a bit slower). |
| `--fast-mode` | Claude fast mode for Opus: quicker output, about 2x the price. |
| `--engine free` | Free translator (Google / MyMemory) even if an API key is set. |
| `--language en` | Force the source language instead of auto-detect. |
| `--sentence-wait 1.5` | Wait longer for an unfinished sentence (default 1.0 s). |
| `--max-chunk 3` | Send audio every 3 s at most (default 5). |
| `--stream` | Show Arabic word by word instead of whole sentences. |
| `--font-size 15` | Arabic text size (default 13). |
| `--device "Headphones"` | Capture a specific output device (see `--list-devices`). |
| `--threshold 0.004` | Lower if quiet speech is missed; raise if music triggers it. |

## Notes
- **macOS** cannot record system audio natively: install the free
  [BlackHole](https://existential.audio/blackhole/) driver, route output to it
  (Multi-Output Device), and pass `--device BlackHole`.
- **Linux** needs PulseAudio or PipeWire (default on most distros).
- If the audio is muted in Windows the loopback is silent too — keep the volume up
  (you can use headphones).
- Translation with Claude uses your API account (a few cents per hour of video).
