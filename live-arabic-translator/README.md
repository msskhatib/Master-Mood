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

## Options
| Option | Meaning |
|---|---|
| `--model medium` | More accurate recognition (slower). `tiny`/`base` are faster. `large-v3` is the best. |
| `--compute cuda` | Use an NVIDIA GPU (much faster; allows `large-v3` live). |
| `--language en` | Force the source language instead of auto-detect. |
| `--engine free` | Use the free translator (Google / MyMemory) even if an API key is set. |
| `--device "Headphones"` | Capture a specific output device (see `--list-devices`). |
| `--threshold 0.004` | Lower if quiet speech is missed; raise if music triggers it. |
| `--font-size 30` | Bigger Arabic subtitles. |
| `--sentence-wait 1.5` | How long to wait for an unfinished sentence to continue (default 1.0 s). |
| `--stream` | Show Arabic word by word instead of one whole sentence at a time. |
| `--max-chunk 3` | Send speech every 3 s at most (faster subtitles; default 5). |
| `--claude-model claude-haiku-5-5` | Fastest and cheapest Claude translation (slightly less polished). |
| `--fast-mode` | Claude fast mode: quicker output, about 2x the price. |

### Fastest settings
```bash
python live_translator.py --model base --max-chunk 3 --claude-model claude-haiku-5-5
```
With an NVIDIA GPU add `--compute cuda` (then `--model small` or `medium` stays fast).

Example: `python live_translator.py --model medium --compute cuda --font-size 28`

## Notes
- **macOS** cannot record system audio natively: install the free
  [BlackHole](https://existential.audio/blackhole/) driver, route output to it
  (Multi-Output Device), and pass `--device BlackHole`.
- **Linux** needs PulseAudio or PipeWire (default on most distros).
- If the audio is muted in Windows the loopback is silent too — keep the volume up
  (you can use headphones).
- Translation with Claude uses your API account (a few cents per hour of video).
