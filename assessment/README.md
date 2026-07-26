# Vinbot — RITES GeM Live Assessment Kit

This folder is the single place to look during the live assessment. It does
not introduce any new functionality — it's a curated index into the real
testing framework built in Phase 3.

## Contents

| File | Use it for |
|---|---|
| `screens-to-show.md` | Which screen/window to have open for each part of the assessment |
| `terminal-commands.md` | Every command to run, in order, copy-pasteable |
| `expected-output.md` | What a successful run of each command actually looks like, so a deviation is obvious |
| `checklist.md` | Tick-through readiness checklist to run through before the assessor arrives |

## Related documents (not duplicated here)

- Full demo script with narrative: `docs/testing/RITES_DEMO_SCRIPT.md`
- Gap analysis / SDLC status: see the Phase 1 audit (conversation record) and `TEST_MATRIX.md`
- Requirement-to-test mapping: `docs/testing/REQUIREMENT_TRACEABILITY_MATRIX.md`
- Real, generated results from the last run: `reports/test-summary-report.md`, `reports/dashboard.html`

## Golden rule for this folder

Nothing in here should ever show a result that wasn't actually produced by
running the commands in `terminal-commands.md` against the real codebase. If
the assessor asks to see something not listed, it is faster and more
credible to run the real command live than to point at a canned screenshot.
