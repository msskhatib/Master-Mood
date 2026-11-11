# Live Arabic Translator — مترجم فوري للعربية

A Python desktop tool that **listens only to the sound playing on your PC**
(YouTube, any video player, Zoom/Teams, podcasts…) and shows **live Arabic
subtitles** in a small always-on-top window.

It records the *speaker output* via loopback, **not the microphone**, so
voices and noise in the room are never picked up.

```
PC audio (loopback) → live speech recognition (Whisper, on the GPU)
                    → instant Arabic on the PC (Meta NLLB-200, ~0.1 s on the GPU)
                    → optional Claude polish a moment later → flowing Arabic text
```
The Arabic appears **while the person is still speaking** and each sentence is
complete a fraction of a second after it ends. Nothing is sent online except
the optional Claude polish.

## Features
- Captures only system audio (WASAPI loopback on Windows, PulseAudio monitor on Linux).
- Auto-detects the spoken language (English, French, Spanish, Hindi, Turkish, ~100 languages).
- High-quality Modern Standard Arabic translation with Claude: fixes speech
  fillers, uses proper Arabic punctuation, keeps names/terms accurate, and uses
  the last few lines as context so the subtitles read consistently.
- Free fallback (Google, then MyMemory) when no Claude API key is set.
- Arabic-only list of sentences; clear, and save the full Arabic transcript to a `.txt` file.

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
instant local translation (NLLB-200, downloaded once, ~1.4 GB) polished by **Claude Haiku 5.5** when a key is set, half the CPU cores at most,
Arabic only, flowing as one right-aligned text, written word by word.

## Options
| Option | Meaning |
|---|---|
| `--model small` | Speech model: `tiny`, `base`, `small`, `medium`, `large-v3-turbo` (bigger = more accurate, heavier). |
| `--compute cuda` / `cpu` | Force GPU or CPU (default `auto`). |
| `--cpu-threads 2` | CPU threads for speech on CPU (fewer = lighter). |
| `--claude-model claude-opus-5-5` | Most polished Arabic (a bit slower). |
| `--fast-mode` | Claude fast mode for Opus: quicker output, about 2x the price. |
| `--engine local` | Instant translation on this PC (default). |
| `--engine claude` | Online Claude only (more polished, ~1 s slower). |
| `--engine free` | Free online translator (Google / MyMemory). |
| `--no-polish` | Keep the instant local Arabic; never rewrite lines with Claude. |
| `--language en` | Force the source language instead of auto-detect. |
| `--step 0.2` | How often speech is re-checked (default 0.2 s on GPU, 0.6 s on CPU). Lower = faster, more GPU/CPU use. |
| `--pause 0.5` | Silence that ends what is being said (default 0.5 s). |
| `--end-gap 0.4` | Audio needed after a sentence's final punctuation before it is final (default 0.6 s). Lower = faster, more risk of split sentences. |
| `--max-buffer 10` | Longest speech sent without a sentence end (default 10 s). |
| `--paragraph-gap 6` | Seconds of silence that start a new paragraph (default 6). |
| `--no-stream` | Show each Arabic sentence only when complete (default: word by word, faster). |
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
