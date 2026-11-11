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

CLAUDE_MODEL = "claude-opus-5-5"          # most polished
FAST_CLAUDE_MODEL = "claude-haiku-5-5"    # fastest, default for live use

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
    "- The text is one spoken sentence (sometimes cut short). Always answer with "
    "complete, grammatical Arabic sentence(s) that read naturally after the "
    "previous lines, like professional film subtitles.\n"
    "- Output ONLY the Arabic translation: never write English sentences, notes, "
    "corrections, questions to the user or explanations. Do not comment on the "
    "task. If the text is empty, noise or has no meaning, output nothing."
)

_ARABIC = re.compile(r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]")
_LATIN = re.compile(r"[A-Za-z]")
_PIECES = re.compile(r"(?<=[.!?؟…:])\s+|\n+")


def clean_arabic(text: str) -> str:
    """Keeps only Arabic sentences: drops any English note the model adds.

    A sentence stays if it has more Arabic letters than Latin ones, so terms
    like (Five Whys) inside an Arabic sentence are kept.
    """
    kept = []
    for piece in _PIECES.split(text):
        piece = piece.strip()
        if piece and len(_ARABIC.findall(piece)) > len(_LATIN.findall(piece)):
            kept.append(piece)
    return " ".join(kept)


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


def capture_loop(loop_device, out_q: queue.Queue, stop: threading.Event,
                 status, threshold: float):
    """Records loopback audio and streams 0.1 s blocks (with a loudness flag)."""
    frames = int(CAPTURE_SR * BLOCK_SEC)
    ratio = CAPTURE_SR // TARGET_SR
    try:
        with loop_device.recorder(samplerate=CAPTURE_SR, blocksize=frames) as rec:
            status("Listening to computer audio…")
            while not stop.is_set():
                data = rec.record(numframes=frames)          # (frames, channels)
                mono = data.mean(axis=1) if data.ndim == 2 else data
                n = (mono.size // ratio) * ratio
                block = mono[:n].reshape(-1, ratio).mean(axis=1).astype(np.float32)
                rms = float(np.sqrt(np.mean(block ** 2)))
                out_q.put((block, rms >= threshold, rms))
    except Exception as exc:  # device unplugged, driver error, ...
        status(f"Audio capture error: {exc}")


# --------------------------------------------------------------------------
# 2. Speech recognition (local Whisper)
# --------------------------------------------------------------------------
def _add_nvidia_dll_dirs() -> None:
    """Windows: make the CUDA/cuDNN DLLs from the pip 'nvidia-*' packages findable."""
    if not sys.platform.startswith("win"):
        return
    import site
    roots = site.getsitepackages() + [site.getusersitepackages()]
    for root in roots:
        base = os.path.join(root, "nvidia")
        if not os.path.isdir(base):
            continue
        for pkg in os.listdir(base):
            bin_dir = os.path.join(base, pkg, "bin")
            if os.path.isdir(bin_dir):
                os.add_dll_directory(bin_dir)
                os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")


class Transcriber:
    def __init__(self, model_size: str | None, language: str | None, device: str,
                 status=print, cpu_threads: int = 2):
        from faster_whisper import WhisperModel
        self.device = "cpu"
        if device in ("auto", "cuda"):
            try:
                _add_nvidia_dll_dirs()
                self.model = WhisperModel(model_size or "small", device="cuda",
                                          compute_type="int8_float16")
                # Run once so missing GPU libraries show up now, not mid-video.
                list(self.model.transcribe(np.zeros(TARGET_SR, np.float32))[0])
                self.device = "cuda"
                self.model_name = model_size or "small"
            except Exception as exc:
                if device == "cuda":
                    status(f"GPU not usable ({exc}); using CPU.")
                print(f"[GPU not used] {exc}", file=sys.stderr)
        if self.device == "cpu":
            self.model_name = model_size or "base"
            self.model = WhisperModel(self.model_name, device="cpu",
                                      compute_type="int8", cpu_threads=cpu_threads)
        self.language = language
        self.last_text = ""

    def words(self, audio: np.ndarray) -> tuple[list[tuple[str, float]], str]:
        """Returns [(word, end_time_seconds), ...] and the language code."""
        segments, info = self.model.transcribe(
            audio,
            language=self.language,
            beam_size=1,                 # greedy decoding: fastest
            word_timestamps=True,
            vad_filter=True,
            condition_on_previous_text=False,   # no prompt: avoids repeated text
            hallucination_silence_threshold=1.0,
        )
        words = []
        for seg in segments:
            # Whisper's own "probably not speech" test: skip invented text.
            if seg.no_speech_prob > 0.6 and seg.avg_logprob < -0.7:
                continue
            if seg.avg_logprob < -1.2:
                continue
            words.extend((w.word, w.end) for w in (seg.words or []))
        if self.language is None and words and info.language_probability > 0.9:
            self.language = info.language     # lock it: skips detection next time
        return words, info.language

    def remember(self, text: str):
        self.last_text = (self.last_text + " " + text)[-300:]


# Phrases Whisper tends to invent over music or silence.
_HALLUCINATIONS = re.compile(
    r"^(thank you( very much| so much)?( for watching| for listening)?|"
    r"thanks for watching|please subscribe.*|subscribe.*|we'?ll see you next time|"
    r"see you (next time|in the next video)|bye( bye)?|you|\.+)[.!?]*$", re.I)

def _key(text: str) -> str:
    return re.sub(r"[^\w]", "", text.lower())


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
# Whisper language code -> NLLB-200 language code.
NLLB_CODES = {
    "en": "eng_Latn", "fr": "fra_Latn", "es": "spa_Latn", "de": "deu_Latn",
    "it": "ita_Latn", "pt": "por_Latn", "nl": "nld_Latn", "ru": "rus_Cyrl",
    "uk": "ukr_Cyrl", "pl": "pol_Latn", "tr": "tur_Latn", "fa": "pes_Arab",
    "ur": "urd_Arab", "hi": "hin_Deva", "bn": "ben_Beng", "zh": "zho_Hans",
    "ja": "jpn_Jpan", "ko": "kor_Hang", "id": "ind_Latn", "ms": "zsm_Latn",
    "vi": "vie_Latn", "th": "tha_Thai", "sv": "swe_Latn", "no": "nob_Latn",
    "da": "dan_Latn", "fi": "fin_Latn", "el": "ell_Grek", "he": "heb_Hebr",
    "ro": "ron_Latn", "hu": "hun_Latn", "cs": "ces_Latn", "sw": "swh_Latn",
    "tl": "tgl_Latn", "ta": "tam_Taml", "te": "tel_Telu", "ml": "mal_Mlym",
}


class LocalTranslator:
    """Meta NLLB-200 running on this PC (GPU if available): ~0.1 s per sentence."""

    GPU_MODEL = "OpenNMT/nllb-200-distilled-1.3B-ct2-int8"
    CPU_MODEL = "JustFrederik/nllb-200-distilled-600M-ct2-int8"

    def __init__(self, device: str, cpu_threads: int = 2, status=print):
        import ctranslate2
        import tokenizers
        from huggingface_hub import snapshot_download

        self.device = "cpu"
        if device in ("auto", "cuda"):
            try:
                _add_nvidia_dll_dirs()
                path = snapshot_download(self.GPU_MODEL)
                self.model = ctranslate2.Translator(path, device="cuda",
                                                    compute_type="int8_float16")
                self.device = "cuda"
            except Exception as exc:
                print(f"[local translator: GPU not used] {exc}", file=sys.stderr)
        if self.device == "cpu":
            path = snapshot_download(self.CPU_MODEL)
            self.model = ctranslate2.Translator(path, device="cpu", compute_type="int8",
                                                intra_threads=cpu_threads)
        self.tok = tokenizers.Tokenizer.from_file(os.path.join(path, "tokenizer.json"))
        self("Hello.", "en")                      # warm up

    def __call__(self, text: str, src_lang: str) -> str:
        src = NLLB_CODES.get(src_lang, "eng_Latn")
        tokens = [src] + self.tok.encode(text, add_special_tokens=False).tokens + ["</s>"]
        result = self.model.translate_batch(
            [tokens], target_prefix=[["arb_Arab"]],
            beam_size=2 if self.device == "cuda" else 1,
            max_decoding_length=256)
        out = result[0].hypotheses[0][1:]            # drop the language tag
        ids = [i for i in (self.tok.token_to_id(t) for t in out) if i is not None]
        return self.tok.decode(ids, skip_special_tokens=True).strip()


class ArabicTranslator:
    """Local instant translation, optional Claude polish, free online fallback."""

    def __init__(self, engine: str, status=print, model: str = CLAUDE_MODEL,
                 fast_mode: bool = False, device: str = "auto", cpu_threads: int = 2,
                 polish: bool = True):
        self.history: list[tuple[str, str]] = []   # (source, arabic) context
        # Early translations started before a sentence is confirmed.
        from concurrent.futures import ThreadPoolExecutor
        self.pool = ThreadPoolExecutor(max_workers=4)
        self.early: dict[str, object] = {}
        self.client = None
        self.status = status
        self.engine = "free"
        self.model = model
        self.fast_mode = fast_mode
        self.local = None
        has_key = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
        if engine == "claude" and not has_key:
            raise SystemExit("ANTHROPIC_API_KEY is not set (needed for --engine claude).")
        if has_key and engine in ("auto", "local", "claude"):
            import anthropic
            self.client = anthropic.Anthropic()
        if engine in ("auto", "local"):
            try:
                status("Loading the local translator (first run downloads ~1.4 GB)…")
                self.local = LocalTranslator(device, cpu_threads, status)
                self.engine = "local"
            except Exception as exc:
                status(f"Local translator unavailable ({exc}); using online translator.")
                print(f"[local translator error] {exc}", file=sys.stderr)
        if self.engine != "local" and self.client is not None:
            self.engine = "claude"
        # With the local translator, Claude only rewrites lines into polished
        # Arabic a moment later (the instant local text is shown first).
        self.polish_on = self.engine == "local" and self.client is not None and polish

    def live(self, text: str, src_lang: str) -> str:
        """Instant translation of words that are still being spoken."""
        if self.local is None or src_lang == "ar":
            return text if src_lang == "ar" else ""
        return clean_arabic(self.local(text, src_lang))

    def polish(self, text: str, src_lang: str) -> str | None:
        try:
            return self._claude(text, src_lang) or None
        except Exception as exc:
            print(f"[Claude polish skipped] {exc}", file=sys.stderr)
            return None

    def __call__(self, text: str, src_lang: str, on_partial=None) -> str:
        if src_lang == "ar":
            return text
        if len(re.findall(r"[^\W\d_]", text)) < 2:
            return ""                     # no real words: nothing to translate
        result = None
        if self.engine == "local":
            try:
                result = clean_arabic(self.local(text, src_lang))
            except Exception as exc:
                print(f"[local translator error] {exc}", file=sys.stderr)
        early = self.early.pop(_key(text), None)
        if early is not None and self.engine == "claude":
            try:
                result = early.result(timeout=15)   # usually already finished
            except Exception:
                result = None
        if result is None and self.engine == "claude":
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
                else:
                    self.status(f"Claude error, used free translator: {str(exc)[:120]}")
                print(f"[Claude error, using free translator] {exc}", file=sys.stderr)
        if result is None and self.client is not None and self.engine == "local":
            result = self.polish(text, src_lang)
        if result is None:
            result = self._free(text, src_lang)
        self.history = (self.history + [(text, result)])[-4:]
        return result

    def prefetch(self, text: str, src_lang: str) -> None:
        """Starts translating a sentence that is probably finished."""
        if self.engine != "claude" or src_lang == "ar":
            return
        key = _key(text)
        if not key or key in self.early:
            return
        if len(self.early) > 30:                    # forget stale guesses
            self.early.pop(next(iter(self.early)))
        self.early[key] = self.pool.submit(self._claude, text, src_lang, None)

    def _claude(self, text: str, src_lang: str, on_partial=None) -> str:
        context = "\n".join(f"- {s}  =>  {a}" for s, a in self.history[-3:])
        user = (
            (f"Previous lines (context only):\n{context}\n\n" if context else "")
            + f"Source language code: {src_lang}\n"
            + f"New text to translate:\n{text}"
        )
        params = dict(model=self.model, max_tokens=600, system=SYSTEM_PROMPT,
                      messages=[{"role": "user", "content": user}])
        if "haiku" in self.model:
            # Thinking stays on (adaptive) at low effort: with thinking off the
            # model sometimes writes its reasoning into the subtitle.
            params.update(output_config={"effort": "low"})
            stream_ctx = self.client.messages.stream(**params)
        else:
            params.update(output_config={"effort": "low"},
                          betas=["server-side-fallback-2026-07-01"], fallbacks="default")
            if self.fast_mode:
                params["speed"] = "fast"
            stream_ctx = self.client.beta.messages.stream(**params)
        with stream_ctx as stream:
            partial = ""
            for piece in stream.text_stream:
                partial += piece
                if on_partial:
                    on_partial(clean_arabic(partial))
            response = stream.get_final_message()
        if response.stop_reason == "refusal":
            raise RuntimeError("translation declined")
        return clean_arabic("".join(b.text for b in response.content
                                    if b.type == "text"))

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
    BG, CARD, FG, MUTED, ACCENT = "#14171c", "#1c2128", "#f1f3f5", "#8b95a1", "#4ea1ff"

    def __init__(self, args):
        self.args = args
        self.ui_q: queue.Queue = queue.Queue()
        self.audio_q: queue.Queue = queue.Queue()
        self.stop_evt = threading.Event()
        self.running = False
        self.transcriber = None
        self.translator = None
        self.rtl = make_rtl_formatter()
        self.lines: dict[int, list] = {}      # id -> [time, lang, source, arabic|None]
        self.paragraphs: list[list[int]] = []  # sentence ids per paragraph
        self.live_text = ""                     # Arabic of words still being spoken
        self.gen = 0
        self.last_added = 0.0
        self.next_id = 0
        self.latest = None

        self.root = tk.Tk()
        self.root.title("Live Arabic Translator – مترجم فوري")
        self.root.geometry("760x520")
        self.root.minsize(480, 300)
        self.root.configure(bg=self.BG)
        self.topmost = tk.BooleanVar(value=True)
        self.root.attributes("-topmost", True)

        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TButton", padding=(10, 3), font=("Segoe UI", 9),
                        background="#2a313a", foreground=self.FG, bordercolor="#3a424d",
                        lightcolor="#2a313a", darkcolor="#2a313a")
        style.map("TButton", background=[("active", "#36404b"), ("disabled", "#20252c")],
                  foreground=[("disabled", self.MUTED)])
        style.configure("TCheckbutton", background=self.BG, foreground=self.MUTED,
                        font=("Segoe UI", 9))
        style.map("TCheckbutton", background=[("active", self.BG)])

        # Toolbar
        bar = tk.Frame(self.root, bg=self.BG)
        bar.pack(fill="x", padx=10, pady=(8, 4))
        self.btn = ttk.Button(bar, text="▶ Start", command=self.toggle, width=8)
        self.btn.pack(side="left")
        ttk.Button(bar, text="Clear", command=self.clear).pack(side="left", padx=(6, 0))
        ttk.Button(bar, text="Save", command=self.save).pack(side="left", padx=6)
        ttk.Checkbutton(bar, text="On top", variable=self.topmost,
                        command=lambda: self.root.attributes(
                            "-topmost", self.topmost.get())).pack(side="left")
        self.count = tk.Label(bar, text="0 sentences", fg=self.MUTED, bg=self.BG,
                              font=("Segoe UI", 9))
        self.count.pack(side="right")

        # Status line
        self.status = tk.Label(self.root, text="Press Start, then play a video.",
                               fg=self.MUTED, bg=self.BG, anchor="w",
                               font=("Segoe UI", 9))
        self.status.pack(fill="x", padx=12)

        # Scrollable list of translated sentences
        body = tk.Frame(self.root, bg=self.BG)
        body.pack(fill="both", expand=True, padx=10, pady=(4, 10))
        self.text = tk.Text(body, wrap="word", bg=self.CARD, fg=self.FG, bd=0,
                            highlightthickness=0, padx=14, pady=8, cursor="arrow",
                            font=("Segoe UI", 10))
        scroll = ttk.Scrollbar(body, command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)

        size = args.font_size
        # One flowing, right-aligned Arabic paragraph; a new paragraph starts
        # after a long pause. (A paragraph is always one tag run so Windows
        # lays the right-to-left text out correctly.)
        self.text.tag_configure("ar", font=("Segoe UI", size), foreground=self.FG,
                                justify="right", spacing2=6, spacing3=14)
        self.text.configure(state="disabled")

        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        self.root.after(100, self.poll)

    # ---- thread-safe status/text updates ----
    def set_status(self, msg: str):
        self.ui_q.put(("status", msg))

    def poll(self):
        try:
            for _ in range(200):
                kind, payload = self.ui_q.get_nowait()
                if kind == "status":
                    self.status.configure(text=payload)
                elif kind == "new":
                    self.add_line(*payload)
                elif kind == "update":
                    self.update_line(*payload, first=True)
                elif kind == "polish":
                    self.update_line(*payload)
                elif kind == "gen":
                    self.gen = payload
                elif kind == "live":
                    gen, arabic = payload
                    if gen == self.gen and arabic != self.live_text:
                        self.live_text = arabic
                        if arabic and (not self.paragraphs or time.monotonic()
                                       - self.last_added > self.args.paragraph_gap):
                            self._new_paragraph()
                        if self.paragraphs:
                            self._render_paragraph(len(self.paragraphs) - 1)
                elif kind == "ready":
                    self.btn.configure(text="■ Stop", state="normal")
                elif kind == "reset":
                    self.btn.configure(text="▶ Start", state="normal")
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def _at_bottom(self) -> bool:
        return self.text.yview()[1] > 0.98

    def add_line(self, line_id: int, source: str, arabic: str):
        lang, _, src = source.partition("] ")
        self.lines[line_id] = [time.strftime("%H:%M:%S"), lang.strip("["), src, None]
        now = time.monotonic()
        current = self.paragraphs[-1] if self.paragraphs else None
        long_pause = now - self.last_added > self.args.paragraph_gap
        too_long = current and sum(len(self.lines[i][2]) for i in current) > 500
        if current is None or (long_pause and current) or too_long:
            self._new_paragraph()
        self.paragraphs[-1].append(line_id)
        self.last_added = now
        self.count.configure(text=f"{len(self.lines)} sentences")

    def _new_paragraph(self):
        self.paragraphs.append([])
        self.last_added = time.monotonic()
        self.text.configure(state="normal")
        self.text.insert("end", "\n", ("ar", f"p{len(self.paragraphs) - 1}"))
        self.text.configure(state="disabled")

    def update_line(self, line_id: int, arabic: str, first: bool = False):
        if line_id not in self.lines:
            return
        if first and self.lines[line_id][3] is None:
            self.live_text = ""      # its words were in the live text until now
        self.lines[line_id][3] = arabic
        for index, para in enumerate(self.paragraphs):
            if line_id in para:
                self._render_paragraph(index)
                break

    def _render_paragraph(self, index: int):
        # Sentences are shown in spoken order: stop at the first one that is
        # still being translated, so a faster later one never jumps ahead.
        parts = []
        for i in self.paragraphs[index]:
            ar = self.lines[i][3]
            if ar is None:
                break
            if ar.strip():
                parts.append(ar.strip())
        if index == len(self.paragraphs) - 1 and self.live_text:
            parts.append(self.live_text)
        tag = f"p{index}"
        ranges = self.text.tag_ranges(tag)
        if not ranges:
            return
        stick = self._at_bottom()
        t = self.text
        t.configure(state="normal")
        t.delete(ranges[0], ranges[1])
        t.insert(ranges[0], self.rtl(" ".join(parts)) + "\n", ("ar", tag))
        t.configure(state="disabled")
        if stick:
            t.see("end")

    def clear(self):
        self.lines.clear()
        self.paragraphs.clear()
        self.live_text = ""
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")
        self.count.configure(text="0 sentences")

    def save(self):
        name = time.strftime("transcript_%Y%m%d_%H%M%S.txt")
        with open(name, "w", encoding="utf-8") as f:
            for para in self.paragraphs:
                f.write(" ".join(self.lines[i][3] or "" for i in para).strip() + "\n\n")
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
                self.set_status("Loading speech model (first run downloads it)…")
                self.transcriber = Transcriber(self.args.model, self.args.language,
                                               self.args.compute, self.set_status,
                                               self.args.cpu_threads)
                self.translator = ArabicTranslator(self.args.engine, self.set_status,
                                                   self.args.claude_model,
                                                   self.args.fast_mode,
                                                   self.args.compute,
                                                   self.args.cpu_threads,
                                                   self.args.polish)
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
        # Two workers so the next sentence is transcribed while the previous
        # one is being translated.
        text_q: queue.Queue = queue.Queue()
        threading.Thread(target=self.transcribe_loop, daemon=True,
                         args=(self.audio_q, text_q, self.stop_evt)).start()
        self.live_evt = threading.Event()
        self.live_req = (0, "", "en")
        threading.Thread(target=self.live_loop, daemon=True,
                         args=(self.stop_evt,)).start()
        for _ in range(3):   # up to 3 sentences translated at the same time
            threading.Thread(target=self.translate_loop, daemon=True,
                             args=(text_q, self.stop_evt)).start()
        if self.translator.engine == "claude":
            # Open the connection now so the first sentence is not slower.
            threading.Thread(target=self._warm_up, daemon=True).start()
        self.set_status(f"Listening to: {speaker.name}  |  speech: "
                        f"{self.transcriber.model_name} on {self.transcriber.device.upper()}  |  "
                        f"translator: {self.translator.engine}"
                        + (f" on {self.translator.local.device.upper()}" if self.translator.local else "")
                        + (f" ({self.translator.model})" if self.translator.engine == "claude" else "")
                        + (" + Claude polish" if self.translator.polish_on else ""))
        self.ui_q.put(("ready", None))

    def transcribe_loop(self, audio_q: queue.Queue, text_q: queue.Queue,
                        stop: threading.Event):
        """Live recognition with a rolling buffer.

        Every --step seconds the audio heard since the last sent sentence is
        recognised again. A sentence is sent as soon as its final punctuation
        is confirmed by two runs in a row (so it does not wait for silence),
        (or the next sentence has started), and the buffer is cut right after
        it. A pause flushes everything.
        """
        sr = TARGET_SR
        step = int((self.args.step or (0.2 if self.transcriber.device == "cuda"
                                       else 0.6)) * sr)
        pause = int(self.args.pause * sr)
        buf = np.zeros(0, np.float32)
        prev: list[str] = []
        since_run = quiet = gen = 0
        levels: list[float] = []

        def norm(w):
            return re.sub(r"[^\w]", "", w.lower())

        last_sent = [""]

        def emit(text, lang):
            text = text.strip()
            if (len(re.findall(r"[^\W\d_]", text)) < 2 or norm(text) == last_sent[0]
                    or _HALLUCINATIONS.match(text)):
                return                            # empty, repeat or invented
            last_sent[0] = norm(text)
            self.transcriber.remember(text)
            line_id = self.next_id
            self.next_id += 1
            self.ui_q.put(("new", (line_id, f"[{lang}] {text}", "…")))
            text_q.put((line_id, text, lang))

        def emit_text(text, lang):
            sentences, rest = split_sentences(text)
            for sentence in sentences + ([rest] if rest else []):
                emit(sentence, lang)

        while not stop.is_set():
            try:
                item = audio_q.get(timeout=0.1)
            except queue.Empty:
                continue
            # Take everything that is waiting (we may be a bit behind).
            items = [item]
            while not audio_q.empty():
                items.append(audio_q.get_nowait())
            if buf.size == 0 and not any(l for _, l, _ in items):
                continue                          # idle silence: ignore
            dip = False
            for b, l, r in items:
                quiet = 0 if l else quiet + b.size
                levels.append(r)
                # Voice drop (end of a sentence, even over music): check now.
                recent = levels[-25:]
                if len(recent) >= 10 and r < 0.55 * float(np.median(recent)):
                    dip = True
            del levels[:-25]
            new = np.concatenate([b for b, _, _ in items])
            buf = np.concatenate([buf, new])
            since_run += new.size
            ended = quiet >= pause
            early = dip and since_run >= int(0.15 * sr)
            if since_run < step and not ended and not early:
                continue
            since_run = 0
            try:
                words, lang = self.transcriber.words(buf)
            except Exception as exc:
                self.set_status(f"Speech recognition error: {exc}")
                buf, prev = np.zeros(0, np.float32), []
                continue
            dur = buf.size / sr

            if ended:                             # speaker paused: send it all
                gen += 1
                self.ui_q.put(("gen", gen))
                emit_text("".join(w for w, _ in words), lang)
                self.request_live(gen, "", lang)
                buf, prev, quiet = np.zeros(0, np.float32), [], 0
                continue
            if not words:
                if dur > 3:                       # music / noise only
                    buf = buf[-sr:]
                continue

            # Words that two consecutive runs agree on are stable.
            current = [norm(w) for w, _ in words]
            agreed = 0
            while (agreed < len(current) and agreed < len(prev)
                   and current[agreed] == prev[agreed]):
                agreed += 1
            prev = current
            # A sentence is finished when its last word ends with . ? ! and
            # the speaker has started the next word, or --end-gap seconds of
            # audio follow it, or two runs in a row agree on it.
            cut = None
            for i in range(len(words)):
                if not _ENDS_SENTENCE.search(words[i][0].strip()):
                    continue
                if (i < len(words) - 1 or words[i][1] < dur - self.args.end_gap
                        or (i < agreed and words[i][1] < dur - 0.1)):
                    cut = i
            if cut is None and dur > self.args.max_buffer:
                cut = agreed - 1 if agreed > 0 else len(words) - 1   # very long run-on
            if cut is None or cut < 0:
                # Show the words being spoken right now, translated instantly.
                self.request_live(gen, "".join(w for w, _ in words), lang)
                # Not confirmed yet: start translating the likely sentence(s)
                # now so the Arabic is ready the moment it is confirmed.
                for j in range(len(words) - 1, -1, -1):
                    if _ENDS_SENTENCE.search(words[j][0].strip()):
                        done, _ = split_sentences("".join(w for w, _ in words[:j + 1]))
                        for sentence in done:
                            self.translator.prefetch(sentence.strip(), lang)
                        break
                continue
            gen += 1
            self.ui_q.put(("gen", gen))
            emit_text("".join(w for w, _ in words[:cut + 1]), lang)
            self.request_live(gen, "".join(w for w, _ in words[cut + 1:]), lang)
            t_end = words[cut][1]
            buf = buf[int(t_end * sr):]
            prev = current[cut + 1:]

    def _warm_up(self):
        try:
            self.translator._claude("Hello.", "en")
        except Exception:
            pass

    def live_loop(self, stop: threading.Event):
        """Translates the words still being spoken, always the latest only."""
        while not stop.is_set():
            if not self.live_evt.wait(0.2):
                continue
            self.live_evt.clear()
            gen, text, lang = self.live_req
            try:
                arabic = self.translator.live(text, lang) if text else ""
            except Exception as exc:
                print(f"[live translation error] {exc}", file=sys.stderr)
                continue
            self.ui_q.put(("live", (gen, arabic)))

    def request_live(self, gen: int, text: str, lang: str):
        if self.translator.local is None:
            return
        sentences, rest = split_sentences(text)
        keep = [x for x in sentences + [rest]
                if x and not _HALLUCINATIONS.match(x.strip())]
        text = " ".join(keep).strip(" -–—")
        if len(text.split()) < 2:            # one stray word: wait for more
            text = ""
        self.live_req = (gen, text, lang)
        self.live_evt.set()

    def translate_loop(self, text_q: queue.Queue, stop: threading.Event):
        while not stop.is_set():
            try:
                line_id, text, lang = text_q.get(timeout=0.2)
            except queue.Empty:
                continue
            target = line_id

            def partial(ar, target=target):
                self.ui_q.put(("update", (target, ar)))

            if not self.args.stream:
                partial = None   # show each sentence complete, no word-by-word

            try:
                arabic = self.translator(text, lang, on_partial=partial)
            except Exception as exc:
                arabic = "[…]"
                self.set_status(f"Translation error: {exc}")
            self.ui_q.put(("update", (target, arabic)))
            if self.translator.polish_on and lang != "ar":
                def polished(fut, target=target):
                    better = fut.result()
                    if better:
                        self.ui_q.put(("polish", (target, better)))
                self.translator.pool.submit(self.translator.polish, text, lang) \
                    .add_done_callback(polished)

    def quit(self):
        self.stop_evt.set()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    p = argparse.ArgumentParser(description="Translate computer audio to Arabic live.")
    p.add_argument("--model", default=None,
                   help="Whisper size: tiny, base, small, medium, large-v3-turbo. "
                        "Default: small on GPU, base on CPU")
    p.add_argument("--language", default=None,
                   help="Force source language code (e.g. en, fr). Default: auto-detect")
    p.add_argument("--engine", default="auto", choices=["auto", "local", "claude", "free"],
                   help="Translator: local (instant, on this PC), claude (online, most "
                        "polished), free (Google/MyMemory). Default: auto = local, "
                        "plus Claude polish when an API key is set")
    p.add_argument("--no-polish", dest="polish", action="store_false",
                   help="Keep the instant local translation; do not rewrite lines with Claude")
    p.add_argument("--compute", default="auto", choices=["auto", "cpu", "cuda"],
                   help="Speech recognition on NVIDIA GPU (cuda) or CPU. Default: auto")
    p.add_argument("--cpu-threads", type=int, default=max(1, min(4, (os.cpu_count() or 4) // 2)),
                   help="CPU threads for speech recognition (fewer = lighter). Default: half, max 4")
    p.add_argument("--device", default=None, help="Part of the output device name")
    p.add_argument("--threshold", type=float, default=0.008,
                   help="Loudness that counts as speech (lower = more sensitive)")
    p.add_argument("--step", type=float, default=None,
                   help="How often speech is re-checked, in seconds "
                        "(default 0.2 on GPU, 0.6 on CPU). Lower = faster")
    p.add_argument("--pause", type=float, default=0.5,
                   help="Silence (seconds) that ends what is being said. Default: 0.5")
    p.add_argument("--end-gap", type=float, default=0.6,
                   help="Audio after a sentence's final punctuation needed to send it "
                        "(default 0.6 s). Lower = faster, more risk of split sentences")
    p.add_argument("--max-buffer", type=float, default=10.0,
                   help="Longest speech (seconds) before it is sent without a "
                        "sentence end. Default: 10")
    p.add_argument("--paragraph-gap", type=float, default=6.0,
                   help="Seconds of silence that start a new paragraph. Default: 6")
    p.add_argument("--no-stream", dest="stream", action="store_false",
                   help="Wait for each whole sentence instead of showing the Arabic "
                        "word by word as it is written (default: word by word)")
    p.add_argument("--claude-model", default=FAST_CLAUDE_MODEL,
                   help=f"Claude model (default: {FAST_CLAUDE_MODEL}, fastest). "
                        f"Use {CLAUDE_MODEL} for the most polished Arabic")
    p.add_argument("--fast-mode", action="store_true",
                   help="Claude fast mode: faster output, about twice the price")
    p.add_argument("--font-size", type=int, default=13, help="Arabic text size (default 13)")
    p.add_argument("--list-devices", action="store_true", help="List output devices")
    args = p.parse_args()

    if args.list_devices:
        list_devices()
        return
    TranslatorApp(args).run()


if __name__ == "__main__":
    main()
