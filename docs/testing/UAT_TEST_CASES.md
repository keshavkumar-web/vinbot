# Vinbot — UAT Test Cases

Business-facing scenarios, written for a non-technical reviewer. Each maps to
a real, existing capability — see the referenced functional/E2E test case for
the technical detail.

| UAT ID | Scenario (in business terms) | Steps | Expected Result | Ref |
|---|---|---|---|---|
| UAT-TC-01 | Ask a common consumer question | Open Vinbot and ask "What documents do I need for a new domestic connection?" | A clear, plain-language answer citing the relevant circular | TC-E2E-001 |
| UAT-TC-02 | Ask for a specific figure | Ask "How many domestic connections are there in Karnal?" | An exact number with its source stated | TC-FUNC-003 |
| UAT-TC-03 | Ask a follow-up naturally | Ask a count question, then just reply "Domestic" to the bot's clarifying question | The bot understands the short reply in context | TC-E2E-003 |
| UAT-TC-04 | Ask something Vinbot doesn't know | Ask about a topic not in the loaded documents | Vinbot honestly says it doesn't have that information, rather than guessing | TC-E2E-005 |
| UAT-TC-05 | Ask an off-topic question | Ask something unrelated to electricity/UHBVN | Vinbot politely declines and stays on-topic | TC-E2E-006 |
| UAT-TC-06 | Start a new conversation | Use "New chat" after a conversation | The old conversation no longer affects new answers | TC-E2E-007 |
| UAT-TC-07 | Response speed | Ask a question and observe how the answer appears | The answer appears progressively, feels responsive, not a long silent wait then a wall of text | TC-E2E-009 |
| UAT-TC-08 | Recovering from a glitch | If the app shows a connection error, refresh the page | The app recovers and resumes normal use | TC-E2E-008 |

## Result key

**Pass** — behaved exactly as expected. **Fail** — record in
`DEFECT_LOG_TEMPLATE.md`, reference the UAT ID. **Blocked** — could not be
executed (record why in `UAT_EXECUTION_SHEET.md`).
