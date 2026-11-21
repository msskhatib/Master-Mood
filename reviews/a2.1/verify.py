#!/usr/bin/env python3
"""Verify the A2.1 final revision against PLAN.md (Verification, checks 1 to 9).

Usage, from the repository root:
  python3 reviews/a2.1/verify.py ORIGINAL.docx FINAL.docx FINAL.pdf
Private inputs read from reviews/a2.1/inputs/build/ (gitignored): quotes.json,
render-record.json, tool-record.json, figs/*.html, canvas/canvas.html.
Writes reviews/a2.1/inputs/build/verify-report.md. Exit code 1 on any failure.
"""
import sys, re, json, hashlib, subprocess, os, difflib
from collections import Counter
import docx
from docx.oxml.ns import qn

ORIG, FINAL, PDF = sys.argv[1:4]
BUILD = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'inputs', 'build')
results = []
def check(name, ok, detail=''):
    results.append((name, bool(ok), detail)); return ok

# ---------- unit extraction ----------
def units(path):
    d = docx.Document(path); u = []
    for i, p in enumerate(d.paragraphs):
        u.append((f'P{i}', p.text))
    for t, T in enumerate(d.tables):
        for r, R in enumerate(T.rows):
            seen = set()
            for c, C in enumerate(R.cells):
                if id(C._tc) in seen: continue
                seen.add(id(C._tc)); u.append((f'T{t}R{r}C{c}', C.text))
    return d, u
do, uo = units(ORIG); df, uf = units(FINAL)

# Allowed edit locations (criterion 2a to 2i, contents tokens, declaration). Final-side IDs.
ALLOWED = {'P5', 'P63', 'P114', 'P137', 'P145', 'P208', 'P211',
           'T3R2C1', 'T4R3C0', 'T4R3C1', 'T4R6C1', 'T8R5C1', 'T8R5C2', 'T9R1C1', 'T12R6C3',
           'T17R1C0', 'T17R2C0', 'T17R3C0', 'T17R4C0', 'T17R5C0', 'T17R6C0', 'T25R1C3',
           'T27R1C2', 'T27R2C2', 'T27R5C1', 'T27R5C2', 'T27R7C1',
           'T29R4C0', 'T29R4C1', 'T30R1C0'}
INSERTED_OK = {'T27R3'}            # new early-retention row
# Named replacements: tokens that may disappear from a location (criterion 2c, 2i).
NAMED_REMOVALS = {('T4R3C0', '65'), ('P63', '65'), ('T29R4C0', '65'), ('T30R1C0', '65')}
TOK = re.compile(r'\(A\)|\[\d+\]|\d+(?:[.,]\d+)*%?')

def remap(uid):
    """Map an original unit ID to the final ID, accounting for the inserted T27 row."""
    m = re.match(r'T27R(\d+)C(\d+)', uid)
    if m and int(m.group(1)) >= 3: return f'T27R{int(m.group(1))+1}C{m.group(2)}'
    return uid

fo = dict(uf); changed = []; removed = []
for uid, txt in uo:
    if uid.startswith('P'): continue
    fid = remap(uid); new = fo.get(fid)
    if new is None: removed.append(uid); continue
    if new != txt: changed.append((uid, fid, txt, new))
# paragraphs: align by sequence
po = [t for k, t in uo if k.startswith('P')]; pf = [t for k, t in uf if k.startswith('P')]
sm = difflib.SequenceMatcher(a=po, b=pf, autojunk=False)
decl_start = next(i for i, t in enumerate(po) if t.startswith('I acknowledge the use of Claude'))
for tag, a0, a1, b0, b1 in sm.get_opcodes():
    if tag == 'equal': continue
    if tag == 'insert':
        ok = a0 == decl_start + 1
        check(f'1 inserted paragraphs at P{b0}..P{b1-1}', ok, 'after the AI declaration' if ok else 'unexpected location')
        continue
    if tag == 'delete':
        check(f'1 deleted paragraphs P{a0}..P{a1-1}', False, 'paragraphs removed'); continue
    for k in range(a1 - a0):
        a, b = a0 + k, b0 + k
        changed.append((f'P{a}', f'P{b}', po[a], pf[b] if b < b1 else ''))
check('1 no table cell removed', not removed, ', '.join(removed))
for uid, fid, old, new in changed:
    in_allowed = fid in ALLOWED
    check(f'1 change at {fid} is in an allowed location', in_allowed, (old[:80] + ' -> ' + new[:80]))
    if fid == 'P5':   # contents token: heading text unchanged, number may change
        check('1 contents heading text unchanged (P5)', old.rsplit('\t', 1)[0] == new.rsplit('\t', 1)[0]); continue
    miss = Counter(TOK.findall(old)) - Counter(TOK.findall(new))
    miss = [t for t in miss.elements() if (fid, t) not in NAMED_REMOVALS]
    check(f'1 tokens kept at {fid}', not miss, 'missing: ' + ', '.join(miss))
check('1 inserted row T27R3 present', fo.get('T27R3C0', '').startswith('Early retention'))

# ---------- 2 rubric quotes ----------
alltext = ' '.join(t for _, t in uf); low = alltext.lower()
for q in json.load(open(os.path.join(BUILD, 'quotes.json'))):
    check(f'2 quote present: {q[:50]}', q.lower() in low)

# ---------- 3 criterion-2 content ----------
f = dict(uf)
for rid, name in [('T27R1C2', 'main-line'), ('T27R2C2', 'customers kept'), ('T27R5C2', 'visitor')]:
    check(f'3 6.3 {name} baseline has method and month', 'month 1' in f[rid].lower() and 'measured' in f[rid].lower(), f[rid])
check('3 37% anchor with [10] kept', '37% multi-SIM on the network [10]' in f['T27R1C2'])
types = ('web page', 'press release', 'report')
for r in range(1, 7):
    check(f'3 culture point {r} has evidence type', any(t in f[f'T17R{r}C0'] for t in types), f[f'T17R{r}C0'])
check('3 Hierarchy counter-evidence kept', 'a Hierarchy trait' in f['P106'])
for k, t in uf:
    if '65 plans' in t or 'about 65' in t:
        check(f'3 "65" labelled secondary at {k}', 'comparison site' in t, t[:90])
    if '10 to 15' in t:
        check(f'3 kiosk time labelled at {k}', 'travel guide' in t, t[:90])
check('3 plan-choice claims cite [2]', '[2]' in f['P114'] and '[2]' in f['T4R3C1'])

# ---------- 4 + 5 figures, identity, resolution ----------
rec = json.load(open(os.path.join(BUILD, 'render-record.json')))
by_src = {os.path.basename(v['source']): v for v in rec.values()}
FIG_SRC = {2: 'fig02.png', 4: 'fig04.png', 5: 'fig05.png', 6: 'fig06.png', 7: 'fig07.png', 8: 'fig08.png', 9: 'fig09.png',
           10: 'fig10.png', 11: 'fig11.png', 12: 'fig12.png', 13: 'fig13.png', 14: 'fig14.png'}
def images_and_captions(d):
    seq = []
    for el in d.element.body.iter(qn('w:p')):
        for b in el.iter(qn('a:blip')):
            part = d.part.related_parts[b.get(qn('r:embed'))]
            node = b
            while node.tag not in (qn('wp:inline'), qn('wp:anchor')): node = node.getparent()
            cx = int(node.find(qn('wp:extent')).get('cx')) / 914400
            seq.append(('img', hashlib.sha256(part.blob).hexdigest(), part.blob, cx))
        txt = ''.join(t.text or '' for t in el.iter(qn('w:t')))
        m = re.match(r'Figure (\d+)\.', txt)
        if m: seq.append(('cap', int(m.group(1)), txt))
    return seq
def fig_hashes(seq):
    out = {}; last = None
    for s in seq:
        if s[0] == 'img': last = s
        elif last is not None: out[s[1]] = last; last = None
    return out
so, sf = images_and_captions(do), images_and_captions(df)
caps = [s[1] for s in sf if s[0] == 'cap']
K = json.load(open(os.path.join(BUILD, 'tool-record.json')))['image_generation'].get('count_included', 0)
check('4 caption sequence is 1..14+K', caps == list(range(1, 15 + K)), str(caps))
ho, hf = fig_hashes(so), fig_hashes(sf)
from io import BytesIO
from PIL import Image
for n in range(1, 15):
    if n in FIG_SRC:
        exp = by_src[FIG_SRC[n]]['sha256']
        check(f'4 Figure {n} is its redraw', hf.get(n, (0, ''))[1] == exp)
        im = Image.open(BytesIO(hf[n][2])); dpi = im.size[0] / hf[n][3]
        check(f'5 Figure {n} >= 300 dpi', dpi >= 300, f'{dpi:.0f} dpi')
        if hf[n][3] >= 6: check(f'5 Figure {n} >= 2400 px (full width)', im.size[0] >= 2400, f'{im.size[0]} px')
    else:
        check(f'4 Figure {n} screenshot unchanged', hf.get(n, (0, ''))[1] == ho.get(n, (0, 'x'))[1])
canvas = [s for s in sf if s[0] == 'img' and s[1] == by_src['canvas.png']['sha256']]
check('4 canvas is the rebuilt composite', len(canvas) == 1)
if canvas:
    im = Image.open(BytesIO(canvas[0][2])); check('5 canvas >= 300 dpi', im.size[0] / canvas[0][3] >= 300, f'{im.size[0]/canvas[0][3]:.0f} dpi')
refs = lambda u: Counter(m for k, t in u for m in re.findall(r'Figure (\d+)', t) if not re.match(r'Figure \d+\.', t))
check('4 in-text figure references unchanged', refs(uo) == refs(uf), str(refs(uf) - refs(uo)) + ' / ' + str(refs(uo) - refs(uf)))

# ---------- PDF: pages, captions, contents ----------
info = subprocess.run(['pdfinfo', PDF], capture_output=True, text=True).stdout
npg = int(re.search(r'Pages:\s+(\d+)', info).group(1))
check('8 PDF has at most 17 pages', npg <= 17, str(npg))
pages = [subprocess.run(['pdftotext', '-f', str(i), '-l', str(i), PDF, '-'], capture_output=True, text=True).stdout for i in range(1, npg + 1)]
flat = re.sub(r'\s+', ' ', ' '.join(pages))
for n in range(1, 15 + K):
    check(f'4 PDF has caption Figure {n}.', f'Figure {n}.' in flat)
dfin = df
for p in dfin.paragraphs[3:35]:
    if '\t' not in p.text: continue
    head, num = p.text.rsplit('\t', 1); key = re.sub(r'\s+', ' ', head.strip())[:45]
    found = next((i for i, t in enumerate(pages[2:], start=3) if key in re.sub(r'\s+', ' ', t)), None)
    check(f'4 contents page for "{key[:30]}"', found is not None and str(found - 1) == num.strip(), f'contents {num.strip()}, PDF printed page {found - 1 if found else None}')

# ---------- 6 data: figure sources carry the inventory values ----------
def src(n): return open(os.path.join(BUILD, 'figs', f'fig{n:02d}.html')).read()
f6 = src(6)
for v in ['49.0', '23.8', '14.6', '6.2', '4.8', '0.8', '17%', '27%', '37%', '13%', '1%']:
    check(f'6 Figure 6 shows {v}', v in f6)
f10 = src(10)
for r in ['R1', 'R2', 'R3', 'R4', 'R5', 'R6', 'R7']:
    check(f'6 Figure 10 shows {r}', r + ' ' in f10)
check('6 Figure 12 uses 13 voice packages', '13 voice packages' in src(12) and '65 plans' not in src(12) and 'about 65' not in src(12))
check('6 Figure 14 uses 13 voice packages', '13 voice packages' in src(14) and '65 plans' not in src(14))

# ---------- 7 declaration ----------
tr = json.load(open(os.path.join(BUILD, 'tool-record.json')))
decl = [t for t in pf if t.startswith('I acknowledge') or t.startswith('I also used') or 'image-generation' in t or 'generate' in t]
orig_decl = po[decl_start]
check('7 original Claude disclosure unchanged', orig_decl in pf)
dtext = ' '.join(pf[pf.index(orig_decl):])
check('7 review tool, purpose, prompt and use declared', all(s in dtext for s in ['Codex', 'reviewer', 'representative prompt', 'findings']))
check('7 model named matches execution record', tr['review_tool']['effective_model'] in dtext)
st = tr['image_generation']['status']
check('7 image statement matches record', ('No image-generation tool was used' in dtext) == (st == 'none'))

# ---------- 9 gate and metrics logic ----------
g1 = ['5 points', '97% of control']
check('9 Gate 1 rule in 6.2 text', all(s in f['P137'] for s in ['early retention'] + g1))
check('9 Gate 1 rule in R1 mitigation', all(s in f['T25R1C3'] for s in ['early retention', '5 points', '97% of control']))
check('9 R1 warning keeps two-cycle trigger', f['T25R1C2'] == dict(uo)['T25R1C2'] and 'two cycles' in f['T25R1C2'])
check('9 6.3 early-retention row', '+5 points over control' in f['T27R3C3'] and 'Month 6' in f['T27R3C4'] and 'Pending' in f['T27R3C2'])
check('9 guardrail row names holdout to month 12', '10% holdout' in f['T27R7C1'] and 'month 12' in f['T27R7C1'])
check('9 visitor row: arrival to first data, 60-minute rule', all(s in f['T27R5C1'] for s in ['actual arrival', 'first data session', '60 minutes', 'complete a purchase']))
check('9 target policy note', '65%, 70%, 5 minutes, 10% and 4.6' in f['P145'] and 'planning assumptions' in f['P145'])
f9 = src(9)
check('9 Figure 9 gate rules', all(s in f9 for s in ['early retention +5 pts vs control', 'revenue at least 97% of control', 'at most 5 minutes', '97% of holdout', '10% holdout']))
cv = open(os.path.join(BUILD, 'canvas', 'canvas.html')).read()
check('9 canvas metric box has Gate 1 rule and holdout', 'early retention after 3 cycles +5 pts vs control' in cv and '10% holdout' in cv)
for t in ['65%', '70%', '5 by month 12', '10% by month 18', '4.6']:
    check(f'9 canvas target {t}', t in cv)
check('9 targets in 5.2', '65%' in f['P118'] and '10% a year' in f['P119'] and '70%' in f['P120'])

# ---------- report ----------
fail = [r for r in results if not r[1]]
os.makedirs(BUILD, exist_ok=True)
with open(os.path.join(BUILD, 'verify-report.md'), 'w') as fh:
    fh.write(f'# verify.py report\n\n{len(results)} checks, {len(fail)} failed\n\n')
    for n, ok, det in results: fh.write(f"- {'PASS' if ok else 'FAIL'} {n}{(': ' + det) if det else ''}\n")
print(f'{len(results)} checks, {len(fail)} failed')
for n, ok, det in fail: print('FAIL', n, det)
sys.exit(1 if fail else 0)
