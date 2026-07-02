# Thesis — Topic-driven vs. Question-driven Research

Working notes / thought process on whether the engine can answer a *question*
(not just survey a *topic*), and what it would take. Captured 2026-07-02.

---

## The question being examined

"Can this engine only produce summary reports on a topic, or can I ask it a
question and get a report that answers it?"

## What the code actually does today (evidence)

`planner/planner.py` is topic-driven. It takes the input string as a `topic` and
slots it into fixed, domain-agnostic templates:

```
"Overview and definition of {topic}"
"History and background of {topic}"
"Key concepts and components of {topic}"
"Current state and developments in {topic}"
"Challenges and open problems in {topic}"
"Applications and impact of {topic}"
"Future directions of {topic}"
```

Then a synthesis task converges over all angles. There is **no** step that:
- recognizes the input is a question,
- extracts the underlying subject/intent,
- or produces a *direct answer* to a question.

## Conclusion

- **Topic → broad multi-angle survey report:** yes (this is the design).
- **Question → direct answer report:** no, not yet.

If a question is passed, it doesn't crash — the whole question string becomes the
`{topic}`, yielding clumsy angles like *"Overview and definition of what are the
risks of X to Y"* and a generic survey rather than a pointed answer.

## What it would take (architecture-friendly, no redesign)

Two focused changes behind existing seams:

1. **Planner upgrade** — detect question input, extract subject + intent, and
   generate angles *targeted at answering it* instead of the generic facets.
   (Deterministic heuristic first; optional LLM query-understanding as a drop-in,
   mirroring the pattern already used for extraction/relevance.)
2. **Reasoning upgrade** — add a **"Direct Answer"** synthesis section that answers
   the question from the verified evidence, alongside existing findings.

Why it fits well: a question is a *sharper relevance signal* than a broad topic,
so the v0.3 machinery (relevance filtering, cross-source corroboration,
deterministic confidence) would make the answer stronger, not weaker.

## Governance note

This is **outside the current `OBJECTIVE.md` (v0.3)**, which is scoped to evidence
quality + verification, not input modality. Per CLAUDE.md ("do not implement
features outside the current objective"), the right move is to propose
**"question-driven research (Q&A mode)"** as a candidate *next* objective (v0.4)
for the owner to fold into `OBJECTIVE.md` — not to bolt it on mid-objective unless
the owner explicitly authorizes a scope change.

## Related clarification (terminology, same session)

"Verification" in this project = **cross-source corroboration** (do independent
sources agree?), not fact-checking against ground truth. "Offline-verified" = the
*code* was validated via the deterministic `--offline` synthetic-source test mode;
it is not the engine researching offline. Real evidence verification needs the
live sources (Wikipedia + arXiv + DuckDuckGo).
