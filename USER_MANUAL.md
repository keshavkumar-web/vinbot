# Vinbot — User Manual

Vinbot is a chat platform by Vinbox Martech Pvt Ltd. This guide describes the
chat interface as configured for **UHBVN (Uttar Haryana Bijli Vitran Nigam)**
— it answers questions about UHBVN's electricity rules, sales circulars,
tariffs, connections and procedures.

## Opening the assistant

Go to the Vinbot URL for your environment:

| Environment | URL |
|---|---|
| DEV | `https://dev-vinbot.vinbox.in` |
| UAT | `https://uat-vinbot.vinbox.in` |
| PROD | `https://vinbot.vinbox.in` |

The page opens directly into the chat window — no login is required. A
session is created automatically in the background; you'll see a welcome
message: *"Hello! I'm the UHBVN Assistant. Ask me about Uttar Haryana Bijli
Vitran Nigam's electricity rules, sales circulars, tariffs, new connections,
and procedures."*

If you instead see **"Could not reach the backend"**, the service is
temporarily unavailable — try again shortly, or contact your administrator
(see `ADMIN_MANUAL.md`).

## Asking a question

1. Type your question in the box at the bottom (e.g. *"What documents are
   required for a new domestic connection?"*).
2. Press **Enter** to send, or click **Send**.
   - **Shift+Enter** inserts a new line instead of sending — useful for
     multi-part questions.
3. The reply appears and types itself out live, word by word, while three
   dots pulse to show it is still generating.

You can ask follow-up questions naturally — the assistant remembers the
current conversation (e.g. asking "count in Ambala?" then just "Domestic" as
your next message works, because it resolves your reply against what was just
discussed).

## What kinds of answers to expect

- **Grounded answers with a source.** Where the assistant states a specific
  figure or clause, it cites where the figure came from (a circular number,
  or a `(Source: ..., Row: ..., Column: ...)` reference for tabular data).
- **"I could not find this information in the knowledge base."** — the honest
  answer when your question isn't covered by the loaded UHBVN documents. This
  is expected behavior, not an error: the assistant is designed to never
  guess a figure, charge, or regulation it can't verify.
- **A clarifying question** — if your question is ambiguous (e.g. it matches
  a data table but doesn't say which district or year), the assistant asks
  you to specify rather than guessing.
- **A polite decline** for questions unrelated to UHBVN/electricity
  distribution (e.g. general knowledge, other topics) — this is by design.

## Formatting

Assistant replies support **Markdown** — headings, bullet/numbered lists,
bold text, inline code, and links render formatted, not as raw text. Your own
messages are shown exactly as typed.

## Starting over

Click **New chat** (top right) to clear the current conversation and start
fresh. This does not close the page or lose your connection — it just clears
history so old context no longer influences new answers.

## Troubleshooting (end user)

| Symptom | What to do |
|---|---|
| "Could not reach the backend" on load | Refresh the page after a minute; if it persists, notify your administrator |
| A message shows "Sorry, something went wrong: ..." | Try resending the question; if it repeats, notify your administrator with the exact error text |
| Reply seems to be missing a figure you expect | The document that contains it may not be loaded yet — report the specific question to your administrator so the knowledge base can be checked |
