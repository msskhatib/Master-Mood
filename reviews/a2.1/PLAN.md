# Plan: Final revision of A2.1 Product Strategy Canvas (Yaqoot Fit)

## Goal
Produce the final, submission-ready revision of assignment A2.1 (IE / Zain 2023 Fast Track 1, Tech Product Management): the Product Strategy Canvas for Yaqoot (Zain KSA) and the proposed development "Yaqoot Fit, the line that fits itself". The revision keeps the analysis that the self-evaluation rates at 73 to 75 of 75, closes the marks still at risk, and upgrades every figure to print quality, with a small number of illustrations made by nano-banana (Gemini image models).

## Inputs (read-only)
- Current report: `A2_1_Product_Strategy_Canvas_Yaqoot_Mohammad_Alkhatib_261121.docx` (cover + 16 numbered pages, 14 figures, 36 references, 9 assumptions, AI declaration).
- Self-evaluation: `A2_1_Yaqoot_Evaluation_with_Evidence_261121.pdf` (rubric mapping, marks at risk in its section 6).
- Course materials: `TPM_Workbook_v18_261120_2.docx`, `3_Essential_Product_Strategy_Frameworks_for_Product_Success.pdf`, the course note on readings.
- Rubric (from the evaluation): 5Cs depth 30, Risks and Resources 20, Success Metrics 15, Strategic Coherence 10; total 75.

## Acceptance criteria (observable)
1. Every rubric criterion keeps its full-mark evidence: each quote listed in evaluation section 2 still appears in the revised text, with no loss of a number, source or table.
2. Marks at risk (evaluation section 6) addressed:
   a. The three (A) baselines (main-line share 50%, customers kept 55%, visitor steps 20 min) each gain a stated measurement method and the date the measured baseline replaces the estimate, in the 6.3 table.
   b. The culture reading (4.5) states the evidence type of each of the six points (public page, results report, press release) and keeps the Hierarchy counter-evidence.
   c. The two weak sources (comparison-site "about 65 plans", travel-guide kiosk time) are labelled as secondary in-text, and no conclusion rests on them alone (the 13 official voice packages carry the argument).
   d. Length: body stays at or under 16 numbered pages; no new prose section is added. Images replace no tables.
   e. Cover carries the professor's name field and the AI declaration lists image generation (nano-banana / Gemini) and the review loop tools.
3. Figures: all 14 own-illustration figures are redrawn at at least 300 dpi at their printed width (no source PNG under 2400 px wide for full-width figures), in the existing palette sampled from yaqoot.sa (burgundy #8B2A2E family, aubergine #3B2E4F, warm grey), with the same data and labels as the originals, checked value-by-value against the text and tables. Screenshots (Figures 1, 3) are kept as evidence but sharpened/cropped only, never regenerated, because they are evidence of the real product.
4. Illustrations: at most 3 nano-banana images, each clearly captioned "Illustrative image generated with Gemini (nano-banana); not a product screenshot", placed only where they help a non-technical reader: (i) the visitor landing with a working line (section 2.4 Arrive), (ii) the resident receiving the best-plan credit (2.4 Fit), (iii) optional cover visual. No Zain/Yaqoot logos, no real people's likeness, no invented UI presented as real.
5. Canvas page (Figure on page 5, course template) is re-exported at full resolution with all ten boxes legible at 100% zoom in the PDF.
6. Outputs: revised `.docx` and `.pdf`, same file-name pattern with date 261121 suffix `_final`; figure numbering, cross-references and the contents page are consistent (14 numbered figures + any illustrations numbered in order).

## Approach
1. Extract the docx (pandoc for text audit, python-docx for editing in place so styles, tables and the course canvas are preserved).
2. Redraw figures 2, 4 to 14 with matplotlib (charts, matrices) and a small diagram helper (boxes/arrows) at 300 dpi; replace image parts in the docx keeping the same size and caption.
3. Generate up to 3 illustrations with nano-banana (`gemini-3.1-flash-image-preview`, fallback `gemini-2.5-flash-image`; no silent fallback to another provider). Shared style sheet: editorial, warm daylight, burgundy accents, no logos, no text in image.
4. Apply the text edits in 2a to 2e only. No change to the strategy, numbers, risks or metrics.
5. Render PDF with LibreOffice; check page count, figure resolution and cross-references.

## Non-goals
- No change to the strategy, the proposal, the rubric evidence or the reference list beyond labelling sources.
- No new data claims. No regenerated screenshots.

## Assumptions and risks
- Gemini key reachable from the environment (requires `x-goog-api-key` network secret). If unavailable, illustrations are skipped, not substituted, and the plan reports it.
- Generated images could be read as product evidence: mitigated by caption rule in criterion 4.
- Page count may grow with illustrations: mitigated by the 16-page cap and dropping illustration (iii) first.

## Verification
- `python3 verify.py final.docx final.pdf` (written during build) checks: page count <= 17 including cover; every image in the docx >= 300 dpi at its rendered width; caption sequence Figure 1..N without gaps; all evaluation section-2 quotes present (string match); "(A)" count unchanged or explained; AI declaration mentions Gemini.
- Data check: for Figures 6 and 10 the plotted values are read back from the plotting script and compared with the numbers in the text (49.0/23.8/14.6/6.2/4.8/0.8/0.8; 17/27/37; 13/1; risk positions R1 to R7).
- Visual check: render each PDF page to PNG at 150 dpi and inspect every figure page.
