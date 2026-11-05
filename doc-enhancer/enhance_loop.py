#!/usr/bin/env python3
"""
Document enhancement loop.

Send a document in, and Claude keeps improving it round after round:

    critique (score 0-10 + issues)  ->  rewrite  ->  critique again  ->  ...

It stops when the document reaches the target score, when the score stops
improving, or when the maximum number of rounds is reached. Every version
is saved, so you can compare drafts.

Usage:
    python enhance_loop.py my_doc.docx
    python enhance_loop.py report.pdf --goal "board-ready executive report" --target 9
    python enhance_loop.py --watch inbox/          # drop files in inbox/ forever
"""

from __future__ import annotations

import argparse
import base64
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

import anthropic

MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
SUPPORTED = {".txt", ".md", ".markdown", ".docx", ".pdf"}

client = anthropic.Anthropic()

CRITIQUE_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "number", "description": "Overall quality 0-10 against the goal."},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "issues": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Concrete, specific problems, most important first.",
        },
        "plan": {"type": "string", "description": "What the next revision must change."},
    },
    "required": ["score", "strengths", "issues", "plan"],
    "additionalProperties": False,
}

SYSTEM = (
    "You are a senior editor and subject-matter reviewer. You improve documents so they "
    "read as real, finished, professional work: accurate, specific, well structured, and "
    "in a consistent voice. Never invent facts, figures, names, citations or quotes that "
    "are not supported by the source; where information is missing, keep it general or "
    "mark it as [TO CONFIRM]. Keep the author's intent and language."
)


# ---------------------------------------------------------------- input / output

def load_document(path: Path) -> tuple[str | None, dict | None]:
    """Return (text, pdf_block). PDFs are sent to Claude directly as a document block."""
    ext = path.suffix.lower()
    if ext == ".pdf":
        data = base64.standard_b64encode(path.read_bytes()).decode()
        return None, {
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": data},
        }
    if ext == ".docx":
        import docx  # python-docx

        d = docx.Document(str(path))
        parts = [p.text for p in d.paragraphs]
        for table in d.tables:
            for row in table.rows:
                parts.append(" | ".join(c.text.strip() for c in row.cells))
        return "\n".join(parts), None
    return path.read_text(encoding="utf-8", errors="replace"), None


def save_docx(markdown_text: str, out: Path) -> None:
    """Write a simple .docx from the markdown result (headings, bullets, paragraphs)."""
    try:
        import docx
    except ImportError:
        return
    d = docx.Document()
    for line in markdown_text.splitlines():
        s = line.rstrip()
        if not s:
            continue
        if s.startswith("#"):
            level = min(len(s) - len(s.lstrip("#")), 4)
            d.add_heading(s.lstrip("#").strip(), level=level)
        elif s.lstrip().startswith(("- ", "* ")):
            d.add_paragraph(s.lstrip()[2:], style="List Bullet")
        else:
            d.add_paragraph(s.replace("**", ""))
    d.save(str(out))


# ---------------------------------------------------------------- Claude calls

def _call(content: list, max_tokens: int, output_config: dict) -> str:
    """One streamed request with refusal fallback; returns the text of the answer."""
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=max_tokens,
        system=SYSTEM,
        thinking={"type": "adaptive"},
        output_config=output_config,
        betas=[FALLBACK_BETA],
        fallbacks="default",
        messages=[{"role": "user", "content": content}],
    ) as stream:
        msg = stream.get_final_message()
    if msg.stop_reason == "refusal":
        raise RuntimeError("Claude declined to process this document.")
    if msg.stop_reason == "max_tokens":
        print("  ! output hit max_tokens; result may be cut short", file=sys.stderr)
    return "".join(b.text for b in msg.content if b.type == "text")


def doc_content(text: str | None, pdf_block: dict | None) -> list:
    if pdf_block is not None:
        return [pdf_block]
    return [{"type": "text", "text": f"<document>\n{text}\n</document>"}]


def critique(text, pdf_block, goal: str) -> dict:
    content = doc_content(text, pdf_block) + [{
        "type": "text",
        "text": (
            f"Goal for this document: {goal}\n\n"
            "Review the document strictly against that goal. Score it 0-10 where 10 means "
            "it could be published or submitted as-is by a professional. Be demanding: "
            "a 9+ needs no meaningful improvement left. List concrete issues (structure, "
            "clarity, accuracy, specificity, tone, formatting, missing sections) and a plan "
            "for the next revision."
        ),
    }]
    raw = _call(
        content,
        max_tokens=16000,
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": CRITIQUE_SCHEMA}},
    )
    return json.loads(raw)


def revise(text, pdf_block, goal: str, review: dict) -> str:
    issues = "\n".join(f"- {i}" for i in review["issues"])
    content = doc_content(text, pdf_block) + [{
        "type": "text",
        "text": (
            f"Goal for this document: {goal}\n\n"
            f"Reviewer score: {review['score']}/10\nIssues:\n{issues}\n\nPlan: {review['plan']}\n\n"
            "Rewrite the COMPLETE document fixing every issue. Keep everything that already "
            "works. Output only the finished document in Markdown, with no commentary "
            "before or after it."
        ),
    }]
    return _call(content, max_tokens=64000, output_config={"effort": "high"}).strip()


# ---------------------------------------------------------------- the loop

def enhance(path: Path, goal: str, target: float, max_rounds: int, out_root: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = out_root / f"{path.stem}-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    text, pdf_block = load_document(path)
    if text is not None:
        (out_dir / "v0-original.md").write_text(text, encoding="utf-8")

    log, best_text, best_score, stalls = [], text, -1.0, 0
    print(f"\n== {path.name}  (goal: {goal}; target {target}/10, max {max_rounds} rounds)")

    for rnd in range(1, max_rounds + 1):
        review = critique(text, pdf_block, goal)
        score = float(review["score"])
        log.append({"round": rnd, "score_before_rewrite": score, **review})
        print(f"  round {rnd}: score {score:.1f}/10 - {len(review['issues'])} issues")

        if text is not None and score > best_score:
            best_text, best_score, stalls = text, score, 0
        elif text is not None:
            stalls += 1

        if score >= target:
            print("  target reached, stopping.")
            break
        if stalls >= 2:
            print("  score stopped improving for 2 rounds, keeping best version.")
            break

        text = revise(text, pdf_block, goal, review)
        pdf_block = None  # after the first rewrite we work on the text version
        (out_dir / f"v{rnd}.md").write_text(text, encoding="utf-8")
    else:
        # last rewrite was never scored; score it so 'best' is accurate
        review = critique(text, None, goal)
        score = float(review["score"])
        log.append({"round": max_rounds + 1, "score_before_rewrite": score, **review})
        print(f"  final check: score {score:.1f}/10")
        if score > best_score:
            best_text, best_score = text, score

    if best_text is None:  # a PDF that already met the target on the first check
        best_text = "_The original PDF already met the target score; no rewrite was needed._"
    final_md = out_dir / "final.md"
    final_md.write_text(best_text or "", encoding="utf-8")
    save_docx(best_text or "", out_dir / "final.docx")
    (out_dir / "review-log.json").write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  best score {best_score:.1f}/10 -> {final_md}")
    return final_md


def watch(inbox: Path, args) -> None:
    """Run forever: every file dropped into the inbox is enhanced, then moved to inbox/done."""
    done = inbox / "done"
    done.mkdir(parents=True, exist_ok=True)
    print(f"Watching {inbox}/ - drop .txt .md .docx or .pdf files in. Ctrl+C to stop.")
    while True:
        for f in sorted(inbox.iterdir()):
            if f.is_file() and f.suffix.lower() in SUPPORTED:
                try:
                    enhance(f, args.goal, args.target, args.max_rounds, args.out)
                except Exception as e:  # keep the watcher alive
                    print(f"  ! failed on {f.name}: {e}", file=sys.stderr)
                shutil.move(str(f), done / f.name)
        time.sleep(args.interval)


def main() -> None:
    p = argparse.ArgumentParser(description="Keep enhancing a document with Claude until it is publication-ready.")
    p.add_argument("files", nargs="*", type=Path, help="documents to enhance")
    p.add_argument("--goal", default="a polished, professional, publication-ready document",
                   help="what the finished document should be")
    p.add_argument("--target", type=float, default=9.0, help="stop when the score reaches this (0-10)")
    p.add_argument("--max-rounds", type=int, default=5, help="maximum rewrite rounds per document")
    p.add_argument("--out", type=Path, default=Path("enhanced"), help="output folder")
    p.add_argument("--watch", type=Path, help="folder to watch for new documents (runs forever)")
    p.add_argument("--interval", type=int, default=5, help="seconds between inbox checks")
    args = p.parse_args()

    if args.watch:
        watch(args.watch, args)
    elif args.files:
        for f in args.files:
            enhance(f, args.goal, args.target, args.max_rounds, args.out)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
