# Vinbot — UAT Plan

## Purpose

Confirm, from a business/end-user perspective, that Vinbot correctly answers
UHBVN-related questions as described in `USER_MANUAL.md`, before a release is
accepted for production use.

## Scope

The chat UI and its answers, as an end user experiences them — not internal
code structure (covered by unit/integration testing) and not infrastructure
(covered by smoke testing and the Administrator Manual).

## Environment

UAT is executed against **`https://uat-vinbot.vinbox.in`** (per
`DOCUMENTATION.md` §9), never PROD.

## Participants

| Role | Responsibility |
|---|---|
| UAT Coordinator | Schedules the session, tracks execution |
| Business Reviewer(s) | `[PLACEHOLDER — name(s) to be provided by the customer/business owner]` |
| Technical Support | Answers questions, logs defects raised during UAT |

## Entry criteria

- `ACCEPTANCE_CRITERIA.md` items AC-01 through AC-05 are met.
- UAT environment is deployed and its health check passes
  (`backend/tests/smoke/smoke.py --base-url https://uat-vinbot.vinbox.in`).

## Exit criteria

- Every test case in `UAT_TEST_CASES.md` has a recorded result in
  `UAT_EXECUTION_SHEET.md`.
- `UAT_SUMMARY_REPORT.md` is completed.
- `UAT_SIGNOFF_TEMPLATE.md` is signed by the business reviewer, or explicit
  conditions for conditional acceptance are recorded.

## Schedule

`[PLACEHOLDER — UAT window dates to be agreed with the customer]`

## Defect handling during UAT

Any issue found is logged in `DEFECT_LOG_TEMPLATE.md` with severity and
reference back to the relevant `UAT_TEST_CASES.md` ID.
