#!/usr/bin/env python3
"""Verify the A2.1 final revision against PLAN.md (Verification, checks 1 to 9).

Usage, from the repository root:
  python3 reviews/a2.1/verify.py ORIGINAL.docx FINAL.docx FINAL.pdf
Private inputs come from reviews/a2.1/inputs/build/ (gitignored): inventory.json, edit-log.json,
declaration.json, quotes.json, render-record.json, tool-record.json, figs/, canvas/, visual-audit.md.
Writes reviews/a2.1/inputs/build/verify-report.md. Exit code 1 on any failure.
"""
import sys, re, json, hashlib, subprocess, os, tempfile, glob, html as H
from collections import Counter
from io import BytesIO
import docx
from docx.oxml.ns import qn
from PIL import Image
import numpy as np

ORIG, FINAL, PDF = sys.argv[1:4]
HERE = os.path.dirname(os.path.abspath(__file__)); BUILD = os.path.join(HERE, 'inputs', 'build'); MEDIA = os.path.join(HERE, 'inputs', 'report-media')
J = lambda n: json.load(open(os.path.join(BUILD, n)))
results = []
def check(name, ok, detail=''):
    results.append((name, bool(ok), detail)); return ok
sha = lambda b: hashlib.sha256(b).hexdigest()

# ---------------- units ----------------
def units(d):
    u = {}
    for i, p in enumerate(d.paragraphs): u[f'P{i}'] = p.text
    for t, T in enumerate(d.tables):
        for r, R in enumerate(T.rows):
            seen = set()
            for c, C in enumerate(R.cells):
                if id(C._tc) in seen: continue
                seen.add(id(C._tc)); u[f'T{t}R{r}C{c}'] = C.text
    return u
do, df = docx.Document(ORIG), docx.Document(FINAL); uo, uf = units(do), units(df)

ALLOWED = {'P63', 'P114', 'P137', 'P145', 'P208', 'P211', 'T3R2C1', 'T4R3C0', 'T4R3C1', 'T4R6C1', 'T8R5C1', 'T8R5C2', 'T9R1C1',
           'T12R6C3', 'T17R1C0', 'T17R2C0', 'T17R3C0', 'T17R4C0', 'T17R5C0', 'T17R6C0', 'T21R5C1', 'T25R1C3',
           'T27R1C2', 'T27R2C2', 'T27R4C1', 'T27R4C2', 'T27R6C1', 'T29R4C0', 'T29R4C1', 'T30R1C0'}
log = J('edit-log.json'); decl = J('declaration.json')
logged = {}
for loc, old, new in log:
    if loc == 'T27 new row': continue
    loc = re.sub(r'T(\d+)R(\d+)C(\d+)', r'T\1R\2C\3', loc); logged.setdefault(loc, []).append((old, new))
check('1 every logged edit is in an allowed location', set(logged) <= ALLOWED, str(set(logged) - ALLOWED))
def fmap(uid):
    m = re.match(r'T27R(\d+)C(\d+)$', uid)
    return f'T27R{int(m.group(1)) + 1}C{m.group(2)}' if m and int(m.group(1)) >= 3 else uid
def is_toc(uid): return re.fullmatch(r'P([3-9]|[12]\d|3[0-4])', uid) is not None
nparas_o = len(do.paragraphs); decl_i = next(i for i in range(nparas_o) if uo[f'P{i}'].startswith('I acknowledge the use of Claude'))
mapped = set()
for uid, old in uo.items():
    fid = fmap(uid); new = uf.get(fid)
    if new is None: check(f'1 unit {uid} still present', False); continue
    mapped.add(fid)
    if is_toc(uid) and '\t' in old:
        check(f'1 contents entry {uid}: only the page number may change', old.rsplit('\t', 1)[0] == new.rsplit('\t', 1)[0], new); continue
    exp = old
    for a, b in logged.get(uid, []):
        if a not in exp: check(f'1 logged edit applies at {uid}', False, a[:60]); continue
        exp = exp.replace(a, b, 1)
    check(f'1 {uid} equals original plus logged edits', new == exp, '' if new == exp else f'expected {exp[:90]!r} got {new[:90]!r}')
row = [r for r in log if r[0] == 'T27 new row'][0][2].split(' | ')
for c, v in enumerate(row):
    check(f'1 inserted 6.3 row cell {c}', uf.get(f'T27R3C{c}') == v); mapped.add(f'T27R3C{c}')
for k in range(len(decl)):
    fid = f'P{decl_i + 1 + k}'; check(f'1 declaration paragraph {k + 1} as generated', uf.get(fid) == decl[k]); mapped.add(fid)
extra = [k for k in uf if k not in mapped and not (k.startswith('P') and int(k[1:]) > decl_i + len(decl) and not uf[k].strip())]
check('1 no unaccounted unit in the final report', not extra, ', '.join(extra[:10]))
check('1 same number of tables', len(do.tables) == len(df.tables))

# ---------------- 2 quotes ----------------
low = ' '.join(uf.values()).lower()
for q in J('quotes.json'): check(f'2 quote present: {q[:50]}', q.lower() in low)

# ---------------- 3 content ----------------
f = uf
for rid, name in [('T27R1C2', 'main-line'), ('T27R2C2', 'customers kept'), ('T27R5C2', 'visitor')]:
    check(f'3 6.3 {name} baseline has method and month', 'month 1' in f[rid].lower() and 'measured' in f[rid].lower())
check('3 37% anchor with [10] kept', '37% multi-SIM on the network [10]' in f['T27R1C2'])
for r in range(1, 7): check(f'3 culture point {r} has evidence type', any(t in f[f'T17R{r}C0'] for t in ('web page', 'press release', 'report')))
check('3 Hierarchy counter-evidence kept', 'a Hierarchy trait' in f['P106'])
for k, t in f.items():
    if re.search(r'about 65|65 plans', t): check(f'3 "65" labelled at {k}', 'comparison site' in t)
    if '10 to 15' in t: check(f'3 kiosk time labelled at {k}', 'travel guide' in t)
check('3 plan-choice claims cite [2]', '[2]' in f['P114'] and '[2]' in f['T4R3C1'])
check('3 A1: study replaces only the 20 minutes', 'replaces only the assumed 20 minutes' in f['P208'] and 'separate benchmark' in f['P208'])

# ---------------- figures: identity, references ----------------
def seq(d):
    out = []
    for el in d.element.body.iter(qn('w:p')):
        for b in el.iter(qn('a:blip')):
            part = d.part.related_parts[b.get(qn('r:embed'))]; node = b
            while node.tag not in (qn('wp:inline'), qn('wp:anchor')): node = node.getparent()
            out.append(('img', part.blob, int(node.find(qn('wp:extent')).get('cx')) / 914400))
        m = re.match(r'Figure (\d+)\.', ''.join(t.text or '' for t in el.iter(qn('w:t'))))
        if m: out.append(('cap', int(m.group(1))))
    return out
so, sf = seq(do), seq(df)
def bind(s):
    res, last = [], None
    for e in s:
        if e[0] == 'img': last = e
        elif last: res.append((e[1], last)); last = None
    return res
bo, bf = bind(so), bind(sf)
tr = J('tool-record.json'); illus = set(tr['image_generation'].get('hashes', []))
K = tr['image_generation'].get('count_included', 0)
check('4 caption numbers are 1..14+K in order', [n for n, _ in bf] == list(range(1, 15 + K)), str([n for n, _ in bf]))
orig_ids = [n for n, _ in bo]; final_non_illus = [n for n, e in bf if sha(e[1]) not in illus]
numap = dict(zip(orig_ids, final_non_illus)); check('4 every original figure maps to one final number', len(numap) == 14 and len(final_non_illus) == 14)
rec = J('render-record.json'); by_src = {os.path.basename(v['source']): v for v in rec.values()}
REDRAW = {2: 'fig02', 4: 'fig04', 5: 'fig05', 6: 'fig06', 7: 'fig07', 8: 'fig08', 9: 'fig09', 10: 'fig10', 11: 'fig11', 12: 'fig12', 13: 'fig13', 14: 'fig14'}
ofig = dict(bo); ffig = dict(bf)
expected_png = {}
for n in range(1, 15):
    m = numap[n]; blob, width_in = ffig[m][1], ffig[m][2]
    if n in REDRAW:
        png = os.path.join(BUILD, 'figs', REDRAW[n] + '.png'); expected_png[m] = png
        check(f'4 Figure {n} (final {m}) is its redraw', sha(blob) == sha(open(png, 'rb').read()))
        meta = json.load(open(png + '.json')); htm = os.path.join(BUILD, 'figs', meta['html'])
        check(f'4 Figure {n} PNG was rendered from the current HTML', sha(open(htm, 'rb').read()) == meta['html_sha256'])
        w = Image.open(BytesIO(blob)).size[0]
        check(f'5 Figure {n} DOCX >= 300 dpi', w / width_in >= 300, f'{w / width_in:.0f}')
        if width_in >= 6: check(f'5 Figure {n} DOCX >= 2400 px', w >= 2400, str(w))
    else:
        check(f'4 Figure {n} screenshot part unchanged', sha(blob) == sha(ofig[n][1])); expected_png[m] = ofig[n][1]
canvas_png = os.path.join(BUILD, 'canvas', 'canvas.png')
check('4 canvas part is the rebuilt composite', any(e[0] == 'img' and sha(e[1]) == sha(open(canvas_png, 'rb').read()) for e in sf))
meta = json.load(open(canvas_png + '.json')); check('4 canvas PNG rendered from current HTML', sha(open(os.path.join(BUILD, 'canvas', meta['html']), 'rb').read()) == meta['html_sha256'])
def refs(t): return [int(x) for x in re.findall(r'Figure (\d+)', t)] if not re.match(r'Figure \d+\.', t) else []
for uid, t in uo.items():
    r0 = refs(t)
    if r0: check(f'4 references at {uid} resolve to the same figures', refs(uf[fmap(uid)]) == [numap[x] for x in r0], f'{r0} -> {refs(uf[fmap(uid)])}')

# ---------------- PDF ----------------
pdfb = open(PDF, 'rb').read(); docxb = open(FINAL, 'rb').read()
npg = int(re.search(r'Pages:\s+(\d+)', subprocess.run(['pdfinfo', PDF], capture_output=True, text=True).stdout).group(1))
check('8 PDF has at most 17 pages', npg <= 17, str(npg))
pages = [re.sub(r'\s+', ' ', subprocess.run(['pdftotext', '-f', str(i), '-l', str(i), PDF, '-'], capture_output=True, text=True).stdout) for i in range(1, npg + 1)]
lst = subprocess.run(['pdfimages', '-list', PDF], capture_output=True, text=True).stdout.splitlines()[2:]
imgs = [dict(page=int(x.split()[0]), w=int(x.split()[3]), h=int(x.split()[4]), xppi=int(x.split()[12])) for x in lst if x.split()[2] == 'image']
tmp = tempfile.mkdtemp(); subprocess.run(['pdfimages', '-png', PDF, os.path.join(tmp, 'i')], check=True)
ext = sorted(glob.glob(os.path.join(tmp, 'i-*.png')))
docx_imgs = [e for e in sf if e[0] == 'img']
check('5 PDF holds one image per DOCX image', len(imgs) == len(docx_imgs) == len(ext), f'{len(imgs)} / {len(docx_imgs)}')
arr = lambda src: np.asarray((Image.open(src) if isinstance(src, str) else Image.open(BytesIO(src))).convert('RGB'))
for k, e in enumerate(docx_imgs):
    same = arr(ext[k]).shape == arr(e[1]).shape and np.array_equal(arr(ext[k]), arr(e[1])) if k > 0 else True
    if k > 0: check(f'5 PDF image {k} pixels equal the DOCX image', same)
cap_page = {}
for m in range(1, 15 + K):
    pg = next((i + 1 for i, t in enumerate(pages) if f'Figure {m}.' in t), None); cap_page[m] = pg
    check(f'4 PDF caption Figure {m}. present', pg is not None)
for m, (n_, e) in enumerate(bf, start=1):
    k = next(i for i, x in enumerate(docx_imgs) if x is e[0:3] or (x[1] is e[1]))
    check(f'4 PDF Figure {m} image is on its caption page', imgs[k]['page'] == cap_page[m], f"image p{imgs[k]['page']} caption p{cap_page[m]}")
    if REDRAW.get(next(o for o, f2 in numap.items() if f2 == m)) or True:
        if e[2] >= 6: check(f'5 PDF Figure {m} >= 2400 px', imgs[k]['w'] >= 2400, str(imgs[k]['w']))
        check(f'5 PDF Figure {m} >= 300 ppi', imgs[k]['xppi'] >= 300, str(imgs[k]['xppi']))
ci = next(i for i, x in enumerate(docx_imgs) if sha(x[1]) == sha(open(canvas_png, 'rb').read()))
check('5 PDF canvas >= 300 ppi', imgs[ci]['xppi'] >= 300, str(imgs[ci]['xppi']))
# contents read from the PDF's own contents page
toc = subprocess.run(['pdftotext', '-f', '2', '-l', '2', '-layout', PDF, '-'], capture_output=True, text=True).stdout
entries = [(re.sub(r'\s+', ' ', m.group(1)).strip(), m.group(2)) for m in re.finditer(r'^\s*(\S.*?)\s*\.{3,}\s*(\d+)\s*$', toc, re.M)]
check('4 PDF contents page has 32 entries', len(entries) == 32, str(len(entries)))
for head, num in entries:
    key = head[:45]; found = next((i for i, t in enumerate(pages[2:], start=3) if key in t), None)
    check(f'4 PDF contents "{key[:30]}" -> printed page', found is not None and str(found - 1) == num, f'contents {num}, heading on {found - 1 if found else None}')

# ---------------- 6 figure data vs inventory ----------------
INV = J('inventory.json')['figures']
def htm(n): return open(os.path.join(BUILD, 'figs', f'fig{n:02d}.html')).read()
bars = re.findall(r"data-label='([^']*)' data-value='([^']*)'", htm(6))
exp6 = [(a, float(b)) for a, b in INV['6']['share'] + INV['6']['multisim'] + INV['6']['growth']]
check('6 Figure 6 bars equal inventory (label, value, order)', [(a, float(b)) for a, b in bars] == exp6, str(bars))
f6t = re.sub(r'<[^>]+>', ' ', htm(6))
for a, b in INV['6']['share']: check(f'6 Figure 6 prints {a} {b:.1f}', f'{b:.1f}' in f6t)
cells = dict(re.findall(r"data-risk='(R\d)' data-cell='([^']*)'", htm(10)))
for rid, rv in INV['10']['risks'].items():
    check(f'6 Figure 10 {rid} in {rv["likelihood"]}-{rv["impact"]}', cells.get(rid) == f"{rv['likelihood']}-{rv['impact']}", cells.get(rid, ''))
    check(f'6 Figure 10 {rid} label', rv['label'] in htm(10))
pts = {a: (float(x), float(y)) for a, x, y in re.findall(r"data-label='([^']*)' data-x='([^']*)' data-y='([^']*)'", htm(7))}
M = INV['7']['measured']; gy = sorted(M['grey'], key=lambda p: -p[1])
exp7 = {'Yaqoot today': M['aub'][0], 'Jawwy (stc)': gy[0], 'Virgin Mobile': gy[1], 'Lebara': gy[2], 'Main operator brands': gy[3], 'Airport kiosk, second SIM': gy[4], 'Yaqoot, target': M['burg'][0][:2]}
for a, p in exp7.items(): check(f'6 Figure 7 {a} at measured position', a in pts and max(abs(pts[a][0] - p[0]), abs(pts[a][1] - p[1])) <= 0.005, str(pts.get(a)))
for n, labs in INV['labels'].items():
    t = H.unescape(re.sub(r'<[^>]+>', ' ', htm(int(n)))); t = re.sub(r'\s+', ' ', t)
    for l in labs: check(f'6 Figure {n} label "{l[:30]}"', l in t)
check('6 Figure 12 uses 13 voice packages', '13 voice packages' in htm(12) and not re.search(r'about 65|65 plans', htm(12)))
check('6 Figure 14 uses 13 voice packages', '13 voice packages' in htm(14) and '65 plans' not in htm(14))
check('6 Figure 4 elapsed-time headings', 'from landing to a working line' in htm(4) and 'from arrival to first data' in htm(4))

# ---------------- 7 declaration ----------------
rv = tr['review_tool']; dtext = ' '.join(decl)
check('7 original Claude disclosure unchanged', uf[f'P{decl_i}'] == uo[f'P{decl_i}'])
check('7 declaration states plan review rounds, findings and input access', f"{rv['plan_review']['rounds']} rounds" in dtext and f"{rv['plan_review']['findings']} findings" in dtext and f"from round {rv['plan_review']['inputs_from_round']}" in dtext)
check('7 declaration separates the finished-report inspection', f"inspected the finished report ({rv['inspection']['first']} findings)" in dtext)
check('7 declaration discloses Claude revision and redraws', 'redraw the figures' in dtext)
check('7 model named matches execution record', rv['effective_model'] in dtext)
check('7 image statement matches record', ('No image-generation tool was used' in dtext) == (tr['image_generation']['status'] == 'none'))
n_findings = len(set(re.findall(r'\*\*(A21-\d+)\*\*|^- (A21-\d+)', open(os.path.join(HERE, 'PLAN-REVIEW-LOG.md')).read(), re.M)))
plan_ids = set(re.findall(r'A21-(\d+)', open(os.path.join(HERE, 'PLAN-REVIEW-LOG.md')).read().split('## Build')[0]))
check('7 plan-review finding count matches the log', len(plan_ids) == rv['plan_review']['findings'], str(len(plan_ids)))

# ---------------- 9 gate logic ----------------
p = f['P137']
check('9 Gate 1 rule in 6.2', all(s in p for s in ['early retention', '5 points above the matched control', 'revenue per customer is at least 97% of control']))
check('9 Gate 2 rule in 6.2 has population, clock, end event, 60-minute score', all(s in p for s in ['complete a purchase', 'actual arrival', 'first Yaqoot data', '60 minutes counts as 60', '97% of a 10% holdout']))
check('9 Gate 2 failure responses', all(s in p for s in ['fails on visitor time', 'fails on revenue', 'holdout ends only when Gate 2 passes']))
check('9 R1 mitigation: Gate 1 rule and Gate 2 revenue response', all(s in f['T25R1C3'] for s in ['revenue per customer at least 97% of control', 'revenue failure at Gate 2']))
check('9 R1 warning keeps the two-cycle trigger', f['T25R1C2'] == uo['T25R1C2'] and 'two cycles' in f['T25R1C2'])
check('9 6.3 early-retention row', '+5 points over control' in f['T27R3C3'] and 'Month 6' in f['T27R3C4'] and 'Pending' in f['T27R3C2'])
check('9 guardrail row names the holdout', '10% holdout' in f['T27R7C1'] and 'month 12' in f['T27R7C1'])
check('9 visitor row definition', all(s in f['T27R5C1'] for s in ['actual arrival', 'first data session', '60 minutes', 'complete a purchase']))
check('9 target policy note', '65%, 70%, 5 minutes, 10% and 4.6' in f['P145'] and 'planning assumptions' in f['P145'])
check('9 5.3 visitor baseline is elapsed time', 'from landing to a working line' in f['T21R5C1'])
f9 = re.sub(r'<[^>]+>', ' ', htm(9)); f9 = re.sub(r'\s+', ' ', f9)
check('9 Figure 9 gate rules with unit and comparator', all(s in f9 for s in ['early retention +5 pts vs control', 'revenue per customer at least 97% of control', 'at most 5 minutes', 'revenue per customer at least 97% of holdout', '10% holdout']))
cv = open(os.path.join(BUILD, 'canvas', 'canvas.html')).read()
check('9 canvas Gate 1 and holdout', 'early retention after 3 cycles +5 pts vs control' in cv and '10% holdout' in cv)
check('9 canvas weak-source citations', "(SAR 67 to 385) [2]" in cv and "comparison site's count [23]" in cv and "travel guide's estimate [36]" in cv)
for t in ['65% by month 18', '70% by month 18', '5 by month 12', '10% by month 18', '4.3 to 4.6']: check(f'9 canvas target {t}', t in cv)
check('9 targets in 5.2', '65%' in f['P118'] and '10% a year' in f['P119'] and '70%' in f['P120'])

# ---------------- visual audit ----------------
va = os.path.join(BUILD, 'visual-audit.md')
vt = open(va).read() if os.path.exists(va) else ''
check('V visual audit recorded against this PDF', sha(pdfb) in vt and 'pages 1-17 at 150 dpi' in vt and 'crops at 200 dpi' in vt)

fail = [r for r in results if not r[1]]
with open(os.path.join(BUILD, 'verify-report.md'), 'w') as fh:
    fh.write(f'# verify.py report\n\nDOCX sha256 {sha(docxb)}\nPDF sha256 {sha(pdfb)}\n\n{len(results)} checks, {len(fail)} failed\n\n')
    for n, ok, det in results: fh.write(f"- {'PASS' if ok else 'FAIL'} {n}{(': ' + det) if det else ''}\n")
print(f'{len(results)} checks, {len(fail)} failed'); [print('FAIL', n, d) for n, ok, d in fail]
sys.exit(1 if fail else 0)
