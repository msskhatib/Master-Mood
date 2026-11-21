# Review plan: Assignment A2.1, Leading a Culturally Diverse Team

## Goal

Get an independent review of the submission (`submission.md`, from the .docx) against the brief and rubric (`brief.txt`) before the deadline (Sat 21 Nov 2026, 23:59). The review should find anything that would cost marks, and each fix must stay within the word limits.

This is a review of a written assignment, not code. "Build" means editing the .docx.

## Acceptance criteria

1. Every requirement in the brief is addressed in the right part:
   - Part 1: three decision points, each with a decision and rationale of 150–200 words, and each referencing leadership styles, GLOBE dimensions, communication principles and emotional intelligence concepts.
   - Part 2: four perspectives, about 100 words each, covering every bullet listed for that perspective.
   - Part 3: about 200 words covering what was learned, how the author's cultural background influences them, and specific prevention strategies.
2. Word limits hold: Part 1 ≤ 500, Part 2 ≤ 400, Part 3 ≤ 200, total ≤ 1,100 (headings, references and the AI declaration excluded).
3. Cultural claims are accurate to the cited frameworks (Hofstede and GLOBE power distance, GLOBE Humane and Performance Orientation, Meyer's Culture Map: Communicating, Deciding and Trusting) and are not stereotyping.
4. Each rubric criterion (Decision Quality, Cultural Analysis, Multi-Perspective Insight, Reflection & Application) is at the "Excellent" level, or the gap is named with a fix.

## Current measurements (host check, Claude; revision 2 after round 1 fixes)

| Section | Words | Limit |
|---|---|---|
| Decision Point 1 | 166 | 150–200 |
| Decision Point 2 | 167 | 150–200 |
| Decision Point 3 | 164 | 150–200 |
| **Part 1 total** | **497** | 500 |
| Cultural Interpreter | 95 | 100 |
| Signal Reader | 98 | 100 |
| Strategic Evaluator | 92 | 100 |
| Change Management | 100 | 100 |
| **Part 2 total** | **385** | 400 |
| **Part 3** | **200** | 200 |
| **Total** | **1,082** | 1,100 |

Proof command (recount after any edit):
`python -c "import docx,re;d=docx.Document('A2_1_Leading_Culturally_Diverse_Team_Mohammad_Alkhatib.docx');print(sum(len(re.findall(r'\S+',p.text)) for p in d.paragraphs))"`. This gives the whole-document count, so recount per section by hand or with the host's script.

## Host's preliminary findings (Claude), for the reviewer to confirm or reject

- **F1 (medium): no in-text citations.** The reference list has four sources, but the body never cites them, for example "(Meyer, 2014)". Markers may treat references without in-text citations as weak framework referencing. Trade-off: Part 1 has only 5 words of headroom, so adding citations requires trimming.
- **F2 (low–medium): gender assumed for the product lead.** "I ask him", "he expected" and "himself" are used, but the brief doesn't give a gender. That reads oddly in an inclusion assignment. Fix: "the product lead" or "they" (word-neutral).
- **F3 (low): course concepts are uncited.** BLUF, servant leadership, empowering leadership, the nurturant-task model (Sinha), PAUSE and the "communication bridge" are named without a source. This is fine if they come from course slides, but one citation such as "(course notes, Session X)" would help.
- **F4 (low): possible stereotyping.** DP1 refers to "the low-context communicators" as a group. Part 2 balances this with a non-cultural reading, which is good, but DP1 could hedge with "likely" to match.
- **Strengths to keep:** all three decision points name a leadership style, a GLOBE dimension, a communication principle and an EI concept. Part 2's perspectives are distinct, and the non-cultural reading and the "absent signal" observation stand out. The Part 3 reflection is specific, personal, and names blind spots with actionable strategies.

## Non-goals

Restructuring the essay, changing the author's decisions, or adding content that breaks the word limits.

## Roles

Host and coordinator: Claude. Reviewer: Codex, `gpt-6.2-astra`, effort high. Builder (if edits are approved): Claude. Inspector: a fresh Codex session. Rounds: up to 3. The review is read-only. Edits to the .docx need the author's approval.
