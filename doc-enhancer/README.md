# Document Enhancer Loop

Give it a document. Claude reviews it, scores it out of 10, rewrites it, and reviews it again. The loop repeats until the document is good enough to use for real.

```
document -> critique (score + issues) -> rewrite -> critique -> rewrite -> ... -> final
```

The loop stops when one of these happens:
- the score reaches `--target` (default 9/10)
- the score fails to improve for 2 rounds in a row (the best version is kept)
- `--max-rounds` rewrites have been done (default 5)

It reads `.txt`, `.md`, `.docx` and `.pdf` files.

## Setup

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
```

## Use

Enhance one document:

```bash
python enhance_loop.py my_report.docx
```

Tell it what the finished document should be:

```bash
python enhance_loop.py cv.pdf --goal "an ATS-friendly CV for a senior network architect role" --target 9.5
```

Run it forever on a folder. Every file you drop into `inbox/` is enhanced automatically, then moved to `inbox/done/`:

```bash
python enhance_loop.py --watch inbox/
```

## Output

Each run writes a folder `enhanced/<name>-<time>/` containing:
- `v0-original.md`, `v1.md`, `v2.md`, ...: every draft, so you can compare them
- `final.md` and `final.docx`: the highest-scoring version
- `review-log.json`: the score, strengths, issues and plan from each round

Claude is told not to invent facts, numbers, names or citations. Anything it can't confirm from your source is marked `[TO CONFIRM]` so you can fill it in yourself.
