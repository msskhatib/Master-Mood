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
import re
import sys
import threading
import time
import warnings
import tkinter as tk
from tkinter import ttk

import numpy as np

TARGET_SR = 16_000          # Whisper expects 16 kHz mono
CAPTURE_SR = 48_000         # native rate of most sound cards (48k = 3 x 16k)
BLOCK_SEC = 0.1             # capture granularity

CLAUDE_MODEL = "claude-opus-5-5"

# Harmless notice from Windows audio when a buffer is late; hide it.
warnings.filterwarnings("ignore", message="data discontinuity")

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

    def __init__(self, min_sec=1.0, max_sec=5.0, silence_sec=0.4,
                 threshold=0.008):
        self.min_len = int(min_sec * TARGET_SR)
        self.max_len = int(max_sec * TARGET_SR)
        self.silence_len = int(silence_sec * TARGET_SR)
        self.threshold = threshold
        self.buf: list[np.ndarray] = []
        self.size = 0
        self.silent_run = 0
        self.has_speech = False
        self.ended_on_pause = True

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
            self.ended_on_pause = pause   # False = cut in the middle of speech
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
                 status, threshold: float, max_sec: float):
    """Records loopback audio and pushes phrase chunks into out_q."""
    chunker = SpeechChunker(threshold=threshold, max_sec=max_sec)
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
                    out_q.put((chunk, chunker.ended_on_pause))
    except Exception as exc:  # device unplugged, driver error, ...
        status(f"Audio capture error: {exc}")


# --------------------------------------------------------------------------
# 2. Speech recognition (local Whisper)
# --------------------------------------------------------------------------
class Transcriber:
    def __init__(self, model_size: str, language: str | None, device: str):
        from faster_whisper import WhisperModel
        compute = "float16" if device == "cuda" else "int8"
        self.model = WhisperModel(model_size, device=device, compute_type=compute,
                                  cpu_threads=os.cpu_count() or 4)
        self.language = language
        self.last_text = ""

    def __call__(self, audio: np.ndarray) -> tuple[str, str]:
        segments, info = self.model.transcribe(
            audio,
            language=self.language,
            beam_size=1,                 # greedy decoding: much faster, live-friendly
            without_timestamps=True,
            vad_filter=True,
            condition_on_previous_text=False,
            initial_prompt=self.last_text[-200:] or None,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        if text:
            self.last_text = text
        return text, info.language


_ENDS_SENTENCE = re.compile(r"[.!?…。！？؟][\"'”’)\]]*$")


def split_sentences(text: str) -> tuple[list[str], str]:
    """Returns (complete sentences, unfinished remainder)."""
    sentences, current = [], ""
    for word in text.split():
        current = f"{current} {word}" if current else word
        if _ENDS_SENTENCE.search(word):
            sentences.append(current)
            current = ""
    return sentences, current


# --------------------------------------------------------------------------
# 3. Translation to Arabic
# --------------------------------------------------------------------------
class ArabicTranslator:
    """Claude for high-quality, organised Arabic; free online fallbacks."""

    def __init__(self, engine: str, status=print, model: str = CLAUDE_MODEL,
                 fast_mode: bool = False):
        self.history: list[tuple[str, str]] = []   # (source, arabic) context
        self.client = None
        self.status = status
        self.engine = "free"
        self.model = model
        self.fast_mode = fast_mode
        if engine in ("auto", "claude") and os.environ.get("ANTHROPIC_API_KEY", "").strip():
            import anthropic
            self.client = anthropic.Anthropic()
            self.engine = "claude"
        elif engine == "claude":
            raise SystemExit("ANTHROPIC_API_KEY is not set (needed for --engine claude).")

    def __call__(self, text: str, src_lang: str, on_partial=None) -> str:
        if src_lang == "ar":
            return text
        result = None
        if self.engine == "claude":
            try:
                result = self._claude(text, src_lang, on_partial)
            except Exception as exc:
                import anthropic
                if isinstance(exc, (anthropic.AuthenticationError,
                                    anthropic.PermissionDeniedError)):
                    # Wrong / revoked key: stop trying Claude for this session.
                    self.engine = "free"
                    self.status("Claude API key is invalid - using the free "
                                "translator. Check ANTHROPIC_API_KEY.")
                print(f"[Claude error, using free translator] {exc}", file=sys.stderr)
        if result is None:
            result = self._free(text, src_lang)
        self.history = (self.history + [(text, result)])[-4:]
        return result

    def _claude(self, text: str, src_lang: str, on_partial=None) -> str:
        context = "\n".join(f"- {s}  =>  {a}" for s, a in self.history[-3:])
        user = (
            (f"Previous lines (context only):\n{context}\n\n" if context else "")
            + f"Source language code: {src_lang}\n"
            + f"New text to translate:\n{text}"
        )
        extra = {"speed": "fast"} if self.fast_mode else {}
        # Stream so the Arabic words appear on screen while they are written.
        with self.client.beta.messages.stream(
            model=self.model,
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": user}],
            **extra,
        ) as stream:
            partial = ""
            for piece in stream.text_stream:
                partial += piece
                if on_partial:
                    on_partial(partial)
            response = stream.get_final_message()
        if response.stop_reason == "refusal":
            raise RuntimeError("translation declined")
        out = "".join(b.text for b in response.content if b.type == "text").strip()
        if not out:
            raise RuntimeError("empty translation")
        return out

    @staticmethod
    def _free(text: str, src_lang: str) -> str:
        """Google's public endpoint, then MyMemory; retries on rate limits."""
        import json
        import urllib.parse
        import urllib.request

        def get(url):
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read().decode("utf-8"))

        def google():
            q = urllib.parse.urlencode({"client": "gtx", "sl": "auto", "tl": "ar",
                                        "dt": "t", "q": text})
            data = get("https://translate.googleapis.com/translate_a/single?" + q)
            return "".join(part[0] for part in data[0] if part and part[0])

        def mymemory():
            src = src_lang if src_lang and src_lang != "auto" else "en"
            q = urllib.parse.urlencode({"q": text[:480], "langpair": f"{src}|ar"})
            data = get("https://api.mymemory.translated.net/get?" + q)
            return data["responseData"]["translatedText"]

        errors = []
        for attempt in range(2):
            for fn in (google, mymemory):
                try:
                    out = (fn() or "").strip()
                    if out:
                        return out
                except Exception as exc:
                    errors.append(f"{fn.__name__}: {exc}")
            time.sleep(1.5 * (attempt + 1))
        raise RuntimeError("free translators unavailable (" + "; ".join(errors[-2:]) + ")")


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
        self.lines: list[list] = []          # [id, source, arabic]
        self.next_id = 0
        self.dirty = False

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
                elif kind == "new":
                    self.lines = (self.lines + [list(payload)])[-200:]
                    self.dirty = True
                elif kind == "update":
                    line_id, arabic = payload
                    for line in reversed(self.lines):
                        if line[0] == line_id:
                            line[2] = arabic
                            self.dirty = True
                            break
                elif kind == "ready":
                    self.btn.configure(text="■ Stop", state="normal")
                elif kind == "reset":
                    self.btn.configure(text="▶ Start", state="normal")
        except queue.Empty:
            pass
        if self.dirty:
            self.dirty = False
            self.render()
        self.root.after(50, self.poll)

    def render(self):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        for _id, src, ar in self.lines[-30:]:
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
            for _id, src, ar in self.lines:
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
                self.translator = ArabicTranslator(self.args.engine, self.set_status,
                                                   self.args.claude_model,
                                                   self.args.fast_mode)
            speaker, loop = get_loopback_device(self.args.device)
        except BaseException as exc:
            self.running = False
            self.set_status(f"Error: {exc}")
            self.ui_q.put(("reset", None))
            return

        self.audio_q = queue.Queue()
        threading.Thread(target=capture_loop, daemon=True,
                         args=(loop, self.audio_q, self.stop_evt, self.set_status,
                               self.args.threshold, self.args.max_chunk)).start()
        # Two workers so the next sentence is transcribed while the previous
        # one is being translated.
        text_q: queue.Queue = queue.Queue()
        threading.Thread(target=self.transcribe_loop, daemon=True,
                         args=(self.audio_q, text_q, self.stop_evt)).start()
        threading.Thread(target=self.translate_loop, daemon=True,
                         args=(text_q, self.stop_evt)).start()
        self.set_status(f"Listening to: {speaker.name}  |  translator: "
                        f"{self.translator.engine}")
        self.ui_q.put(("ready", None))

    def transcribe_loop(self, audio_q: queue.Queue, text_q: queue.Queue,
                        stop: threading.Event):
        """Speech -> text, then regroup the text into whole sentences.

        Audio is cut at pauses (or every few seconds), which can split a
        sentence in two. The unfinished part is kept and joined with the next
        piece; it is sent on its own only when nothing follows within
        --sentence-wait seconds.
        """
        pending, pending_lang, last_heard = "", "en", 0.0
        wait = self.args.sentence_wait

        def emit(sentence, lang):
            line_id = self.next_id
            self.next_id += 1
            self.ui_q.put(("new", (line_id, f"[{lang}] {sentence}", "…")))
            text_q.put((line_id, sentence, lang))

        while not stop.is_set():
            try:
                chunk, on_pause = audio_q.get(timeout=0.1)
            except queue.Empty:
                # Silence: flush an unfinished sentence after the wait.
                if pending and time.monotonic() - last_heard >= wait:
                    emit(pending, pending_lang)
                    pending = ""
                continue
            # If we fall behind, merge waiting chunks so we catch up.
            while not audio_q.empty() and chunk.size < TARGET_SR * 12:
                more, on_pause = audio_q.get_nowait()
                chunk = np.concatenate([chunk, more])
            try:
                text, lang = self.transcriber(chunk)
            except Exception as exc:
                self.set_status(f"Speech recognition error: {exc}")
                continue
            last_heard = time.monotonic()
            if not text or len(text) < 2:
                continue
            pending_lang = lang
            sentences, rest = split_sentences(f"{pending} {text}")
            if sentences and not rest and not on_pause:
                # Audio was cut mid-speech: the last "sentence" may go on.
                rest = sentences.pop()
            for sentence in sentences:
                emit(sentence, lang)
            pending = rest
            if len(pending) > 300:            # very long run-on: send it anyway
                emit(pending, lang)
                pending = ""

    def translate_loop(self, text_q: queue.Queue, stop: threading.Event):
        while not stop.is_set():
            try:
                line_id, text, lang = text_q.get(timeout=0.2)
            except queue.Empty:
                continue
            # Catch up: if more sentences are waiting, translate them together
            # and show the result on the newest line.
            merged = [line_id]
            while text_q.qsize() >= 3:     # only when far behind
                nid, ntext, _ = text_q.get_nowait()
                merged.append(nid)
                text += " " + ntext
            for old in merged[:-1]:
                self.ui_q.put(("update", (old, "↓")))
            target = merged[-1]

            def partial(ar, target=target):
                self.ui_q.put(("update", (target, ar)))

            if not self.args.stream:
                partial = None   # show each sentence complete, no word-by-word

            try:
                arabic = self.translator(text, lang, on_partial=partial)
            except Exception as exc:
                arabic = "⚠ تعذّرت الترجمة"
                self.set_status(f"Translation error: {exc}")
            self.ui_q.put(("update", (target, arabic)))

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
    p.add_argument("--engine", default="auto", choices=["auto", "claude", "free"],
                   help="Translator: claude (best quality), free (Google/MyMemory). Default: auto")
    p.add_argument("--compute", default="cpu", choices=["cpu", "cuda"],
                   help="Run Whisper on CPU or NVIDIA GPU (cuda)")
    p.add_argument("--device", default=None, help="Part of the output device name")
    p.add_argument("--threshold", type=float, default=0.008,
                   help="Loudness that counts as speech (lower = more sensitive)")
    p.add_argument("--max-chunk", type=float, default=5.0,
                   help="Longest phrase in seconds before it is sent (lower = faster, "
                        "but sentences may be cut). Default: 5")
    p.add_argument("--sentence-wait", type=float, default=1.0,
                   help="Seconds to wait for the end of an unfinished sentence "
                        "before translating it anyway. Default: 1.0")
    p.add_argument("--stream", action="store_true",
                   help="Show the Arabic word by word instead of whole sentences")
    p.add_argument("--claude-model", default=CLAUDE_MODEL,
                   help=f"Claude model for translation (default: {CLAUDE_MODEL}). "
                        "claude-haiku-5-5 is the fastest and cheapest")
    p.add_argument("--fast-mode", action="store_true",
                   help="Claude fast mode: faster output, about twice the price")
    p.add_argument("--font-size", type=int, default=24, help="Arabic subtitle size")
    p.add_argument("--list-devices", action="store_true", help="List output devices")
    args = p.parse_args()

    if args.list_devices:
        list_devices()
        return
    TranslatorApp(args).run()


if __name__ == "__main__":
    main()
