"""
Live Arabic Translator
======================

Listens ONLY to the sound your computer is playing (videos, YouTube, Zoom,
media players...) through "loopback" capture of the speakers. The microphone
is never opened, so voices in the room are ignored.

Pipeline:
    system audio (loopback) -> speech chunker -> Whisper (speech-to-text,
    auto language detection) -> Claude (natural, well-organised Arabic
    translation, with Google Translate as a free fallback) -> subtitle window

Run:
    python live_translator.py                 # default settings
    python live_translator.py --model medium  # more accurate speech recognition
    python live_translator.py --list-devices  # show output devices
"""

from __future__ import annotations

import argparse
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk

import numpy as np

TARGET_SR = 16_000          # Whisper expects 16 kHz mono
CAPTURE_SR = 48_000         # native rate of most sound cards (48k = 3 x 16k)
BLOCK_SEC = 0.1             # capture granularity

CLAUDE_MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = (
    "You are a professional subtitle translator. Translate the given speech "
    "transcript into clear, natural, well-organised Modern Standard Arabic "
    "(الفصحى المعاصرة). Rules:\n"
    "- Convey the meaning and tone, not word-for-word; fix the broken grammar, "
    "fillers (um, uh) and repetitions typical of speech recognition.\n"
    "- Use correct Arabic punctuation (، ؛ ؟) and split long sentences.\n"
    "- Keep names, brands and technical terms accurate; add the original term "
    "in parentheses only when an Arabic reader would need it.\n"
    "- Use the previous lines only as context for consistency; translate ONLY "
    "the new text.\n"
    "- Output the Arabic translation only, with no notes or explanations."
)


# --------------------------------------------------------------------------
# 1. Audio capture: speaker loopback only (never the microphone)
# --------------------------------------------------------------------------
def get_loopback_device(speaker_name: str | None = None):
    import soundcard as sc

    speaker = None
    if speaker_name:
        for s in sc.all_speakers():
            if speaker_name.lower() in s.name.lower():
                speaker = s
                break
        if speaker is None:
            raise SystemExit(f"No output device matching '{speaker_name}'. "
                             "Use --list-devices.")
    else:
        speaker = sc.default_speaker()
    # A "loopback microphone" mirrors exactly what this speaker plays.
    loop = sc.get_microphone(id=str(speaker.name), include_loopback=True)
    return speaker, loop


def list_devices() -> None:
    import soundcard as sc
    print("Output devices (use part of the name with --device):")
    default = sc.default_speaker().name
    for s in sc.all_speakers():
        mark = "  (default)" if s.name == default else ""
        print(f"  - {s.name}{mark}")


class SpeechChunker:
    """Groups a stream of 16 kHz samples into phrase-sized chunks.

    A chunk is closed when a pause (silence) follows enough speech, or when it
    reaches max_sec, so subtitles appear quickly and sentences stay whole.
    """

    def __init__(self, min_sec=1.5, max_sec=9.0, silence_sec=0.6,
                 threshold=0.008):
        self.min_len = int(min_sec * TARGET_SR)
        self.max_len = int(max_sec * TARGET_SR)
        self.silence_len = int(silence_sec * TARGET_SR)
        self.threshold = threshold
        self.buf: list[np.ndarray] = []
        self.size = 0
        self.silent_run = 0
        self.has_speech = False

    def feed(self, block: np.ndarray) -> np.ndarray | None:
        rms = float(np.sqrt(np.mean(block ** 2))) if block.size else 0.0
        loud = rms >= self.threshold

        if not self.has_speech and not loud:
            return None  # idle: drop silence between phrases

        self.buf.append(block)
        self.size += block.size
        if loud:
            self.has_speech = True
            self.silent_run = 0
        else:
            self.silent_run += block.size

        pause = self.silent_run >= self.silence_len and self.size >= self.min_len
        if pause or self.size >= self.max_len:
            return self._flush()
        if self.silent_run >= self.silence_len * 3:   # only a short blip
            self._reset()
        return None

    def _flush(self) -> np.ndarray:
        chunk = np.concatenate(self.buf).astype(np.float32)
        self._reset()
        return chunk

    def _reset(self):
        self.buf, self.size, self.silent_run, self.has_speech = [], 0, 0, False


def capture_loop(loop_device, out_q: queue.Queue, stop: threading.Event,
                 status, threshold: float):
    """Records loopback audio and pushes phrase chunks into out_q."""
    chunker = SpeechChunker(threshold=threshold)
    frames = int(CAPTURE_SR * BLOCK_SEC)
    ratio = CAPTURE_SR // TARGET_SR
    try:
        with loop_device.recorder(samplerate=CAPTURE_SR, blocksize=frames) as rec:
            status("Listening to computer audio…")
            while not stop.is_set():
                data = rec.record(numframes=frames)          # (frames, channels)
                mono = data.mean(axis=1) if data.ndim == 2 else data
                n = (mono.size // ratio) * ratio
                block = mono[:n].reshape(-1, ratio).mean(axis=1)  # 48k -> 16k
                chunk = chunker.feed(block.astype(np.float32))
                if chunk is not None:
                    out_q.put(chunk)
    except Exception as exc:  # device unplugged, driver error, ...
        status(f"Audio capture error: {exc}")


# --------------------------------------------------------------------------
# 2. Speech recognition (local Whisper)
# --------------------------------------------------------------------------
class Transcriber:
    def __init__(self, model_size: str, language: str | None, device: str):
        from faster_whisper import WhisperModel
        compute = "float16" if device == "cuda" else "int8"
        self.model = WhisperModel(model_size, device=device, compute_type=compute)
        self.language = language
        self.last_text = ""

    def __call__(self, audio: np.ndarray) -> tuple[str, str]:
        segments, info = self.model.transcribe(
            audio,
            language=self.language,
            beam_size=5,
            vad_filter=True,
            condition_on_previous_text=False,
            initial_prompt=self.last_text[-200:] or None,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        if text:
            self.last_text = text
        return text, info.language


# --------------------------------------------------------------------------
# 3. Translation to Arabic
# --------------------------------------------------------------------------
class ArabicTranslator:
    """Claude for high-quality, organised Arabic; Google Translate fallback."""

    def __init__(self, engine: str):
        self.history: list[tuple[str, str]] = []   # (source, arabic) context
        self.client = None
        self.engine = engine
        if engine in ("auto", "claude") and os.environ.get("ANTHROPIC_API_KEY"):
            import anthropic
            self.client = anthropic.Anthropic()
            self.engine = "claude"
        elif engine == "claude":
            raise SystemExit("ANTHROPIC_API_KEY is not set (needed for --engine claude).")
        else:
            self.engine = "google"

    def __call__(self, text: str, src_lang: str) -> str:
        if src_lang == "ar":
            return text
        if self.engine == "claude":
            try:
                result = self._claude(text, src_lang)
            except Exception as exc:
                print(f"[Claude error, using Google] {exc}", file=sys.stderr)
                result = self._google(text)
        else:
            result = self._google(text)
        self.history = (self.history + [(text, result)])[-4:]
        return result

    def _claude(self, text: str, src_lang: str) -> str:
        context = "\n".join(f"- {s}  =>  {a}" for s, a in self.history)
        user = (
            (f"Previous lines (context only):\n{context}\n\n" if context else "")
            + f"Source language code: {src_lang}\n"
            + f"New text to translate:\n{text}"
        )
        response = self.client.beta.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4000,
            system=SYSTEM_PROMPT,
            output_config={"effort": "low"},          # fast enough for live subtitles
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": user}],
        )
        if response.stop_reason == "refusal":
            raise RuntimeError("translation declined")
        out = "".join(b.text for b in response.content if b.type == "text").strip()
        if not out:
            raise RuntimeError("empty translation")
        return out

    @staticmethod
    def _google(text: str) -> str:
        from deep_translator import GoogleTranslator
        return GoogleTranslator(source="auto", target="ar").translate(text) or ""


# --------------------------------------------------------------------------
# 4. Subtitle window
# --------------------------------------------------------------------------
def make_rtl_formatter():
    """Tk on Windows shapes Arabic itself; Linux/macOS need reshaping + bidi."""
    if sys.platform.startswith("win"):
        return lambda s: s
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        return lambda s: "\n".join(get_display(arabic_reshaper.reshape(line))
                                   for line in s.split("\n"))
    except ImportError:
        return lambda s: s


class TranslatorApp:
    def __init__(self, args):
        self.args = args
        self.ui_q: queue.Queue = queue.Queue()
        self.audio_q: queue.Queue = queue.Queue()
        self.stop_evt = threading.Event()
        self.running = False
        self.transcriber = None
        self.translator = None
        self.rtl = make_rtl_formatter()
        self.lines: list[tuple[str, str]] = []

        self.root = tk.Tk()
        self.root.title("Live Arabic Translator – مترجم فوري")
        self.root.geometry("900x420")
        self.root.configure(bg="#111418")
        self.root.attributes("-topmost", True)

        bar = tk.Frame(self.root, bg="#111418")
        bar.pack(fill="x", padx=12, pady=8)
        self.btn = ttk.Button(bar, text="▶ Start", command=self.toggle)
        self.btn.pack(side="left")
        self.show_src = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="Show original", variable=self.show_src,
                        command=self.render).pack(side="left", padx=10)
        ttk.Button(bar, text="Clear", command=self.clear).pack(side="left")
        ttk.Button(bar, text="Save transcript", command=self.save).pack(side="left", padx=10)
        self.status = tk.Label(bar, text="Press Start, then play a video.",
                               fg="#9aa4b1", bg="#111418", anchor="w")
        self.status.pack(side="left", fill="x", expand=True, padx=10)

        self.text = tk.Text(self.root, wrap="word", bg="#111418", fg="#ffffff",
                            bd=0, padx=16, pady=10, font=("Segoe UI", 22))
        self.text.tag_configure("ar", justify="right", font=("Segoe UI", args.font_size),
                                foreground="#ffffff", spacing3=4)
        self.text.tag_configure("src", justify="left", font=("Segoe UI", 12),
                                foreground="#7d8794", spacing1=10)
        self.text.pack(fill="both", expand=True)
        self.text.configure(state="disabled")

        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        self.root.after(100, self.poll)

    # ---- thread-safe status/text updates ----
    def set_status(self, msg: str):
        self.ui_q.put(("status", msg))

    def poll(self):
        try:
            while True:
                kind, payload = self.ui_q.get_nowait()
                if kind == "status":
                    self.status.configure(text=payload)
                elif kind == "line":
                    self.lines = (self.lines + [payload])[-200:]
                    self.render()
                elif kind == "ready":
                    self.btn.configure(text="■ Stop", state="normal")
                elif kind == "reset":
                    self.btn.configure(text="▶ Start", state="normal")
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def render(self):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        for src, ar in self.lines[-30:]:
            if self.show_src.get():
                self.text.insert("end", src + "\n", "src")
            self.text.insert("end", self.rtl(ar) + "\n", "ar")
        self.text.see("end")
        self.text.configure(state="disabled")

    def clear(self):
        self.lines = []
        self.render()

    def save(self):
        name = time.strftime("transcript_%Y%m%d_%H%M%S.txt")
        with open(name, "w", encoding="utf-8") as f:
            for src, ar in self.lines:
                f.write(f"{src}\n{ar}\n\n")
        self.status.configure(text=f"Saved {os.path.abspath(name)}")

    # ---- start / stop ----
    def toggle(self):
        if self.running:
            self.stop_evt.set()
            self.running = False
            self.btn.configure(text="▶ Start")
            self.status.configure(text="Stopped.")
        else:
            self.running = True
            self.stop_evt = threading.Event()
            self.btn.configure(text="Loading…", state="disabled")
            threading.Thread(target=self.start_workers, daemon=True).start()

    def start_workers(self):
        try:
            if self.transcriber is None:
                self.set_status(f"Loading Whisper '{self.args.model}' model "
                                "(first run downloads it)…")
                self.transcriber = Transcriber(self.args.model, self.args.language,
                                               self.args.compute)
                self.translator = ArabicTranslator(self.args.engine)
            speaker, loop = get_loopback_device(self.args.device)
        except BaseException as exc:
            self.running = False
            self.set_status(f"Error: {exc}")
            self.ui_q.put(("reset", None))
            return

        self.audio_q = queue.Queue()
        threading.Thread(target=capture_loop, daemon=True,
                         args=(loop, self.audio_q, self.stop_evt, self.set_status,
                               self.args.threshold)).start()
        threading.Thread(target=self.process_loop, daemon=True,
                         args=(self.audio_q, self.stop_evt)).start()
        self.set_status(f"Listening to: {speaker.name}  |  translator: "
                        f"{self.translator.engine}")
        self.ui_q.put(("ready", None))

    def process_loop(self, audio_q: queue.Queue, stop: threading.Event):
        while not stop.is_set():
            try:
                chunk = audio_q.get(timeout=0.3)
            except queue.Empty:
                continue
            # If we fall behind, merge waiting chunks so we catch up.
            while not audio_q.empty() and chunk.size < TARGET_SR * 20:
                chunk = np.concatenate([chunk, audio_q.get_nowait()])
            try:
                text, lang = self.transcriber(chunk)
                if not text or len(text) < 2:
                    continue
                arabic = self.translator(text, lang)
                self.ui_q.put(("line", (f"[{lang}] {text}", arabic)))
            except Exception as exc:
                self.set_status(f"Error: {exc}")

    def quit(self):
        self.stop_evt.set()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    p = argparse.ArgumentParser(description="Translate computer audio to Arabic live.")
    p.add_argument("--model", default="small",
                   help="Whisper size: tiny, base, small, medium, large-v3 (default: small)")
    p.add_argument("--language", default=None,
                   help="Force source language code (e.g. en, fr). Default: auto-detect")
    p.add_argument("--engine", default="auto", choices=["auto", "claude", "google"],
                   help="Translator: claude (best quality), google (free). Default: auto")
    p.add_argument("--compute", default="cpu", choices=["cpu", "cuda"],
                   help="Run Whisper on CPU or NVIDIA GPU (cuda)")
    p.add_argument("--device", default=None, help="Part of the output device name")
    p.add_argument("--threshold", type=float, default=0.008,
                   help="Loudness that counts as speech (lower = more sensitive)")
    p.add_argument("--font-size", type=int, default=24, help="Arabic subtitle size")
    p.add_argument("--list-devices", action="store_true", help="List output devices")
    args = p.parse_args()

    if args.list_devices:
        list_devices()
        return
    TranslatorApp(args).run()


if __name__ == "__main__":
    main()
