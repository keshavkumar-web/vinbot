# Vinbot — Demo Presentation

**An AI chatbot platform by Vinbox Martech Pvt Ltd. This configuration answers
questions from UHBVN's sales circulars, compendiums, and press notes.**

> Suggested length: 15–20 min. Audience: UHBVN stakeholders/management + technical reviewers.
> Slides marked 🗣 have speaker notes. Slide 6 is the LIVE DEMO.

---

## Slide 1 — Title

**Vinbot**
An AI-powered knowledge assistant for electricity rules, tariffs & procedures.
This deployment: UHBVN configuration.

- Presented by: _[Your name / team]_
- Date: _[date]_

🗣 *One line: "This is a chatbot that lets consumers and staff ask plain-language questions and get answers straight from official UHBVN documents — with the source circular cited."*

---

## Slide 2 — The Problem

- UHBVN policy lives across **hundreds of pages**: sales circulars, compendiums of instructions, press notes (2018 → 2026).
- Staff & consumers struggle to find the **right clause** quickly.
- Searching PDFs is slow; interpreting them needs expertise.
- Wrong/outdated information leads to disputes and rework.

🗣 *Anchor it: "Today, finding the tariff for a registered Gaushala means knowing which circular, then reading it. We made that a single question."*

---

## Slide 3 — The Solution

A chat interface where you **ask in plain language** and get:

- A direct answer grounded in **official UHBVN documents**.
- The **source circular/clause cited** in the response.
- "I don't have information about that" when it's not in the documents — **no guessing**.

✅ Available 24/7 · ✅ Consistent answers · ✅ Always cites the source

---

## Slide 4 — How It Works (RAG, in plain English)

**Retrieval-Augmented Generation** — the AI only answers from *your* documents.

```
   UHBVN PDFs ──▶ Extracted text ──▶ Split into chunks ──▶ Embeddings (knowledge_db)
                                                                    │
   User question ──▶ Embedding ──▶ Find most similar chunks ◀───────┘
                                          │
                                          ▼
                         AI writes an answer using ONLY those chunks  ──▶ User
```

Key point: the AI is **constrained to the knowledge base** — it can't invent figures or regulations.

🗣 *Contrast with ChatGPT: "A generic chatbot guesses from the internet. This one only speaks from UHBVN's own circulars, and tells you which one."*

---

## Slide 5 — What It Knows Today

- **55 official UHBVN documents** already loaded, including:
  - Sales Circulars (U-series & I-series), 2018–2026
  - Compendium of Instructions (2022, 2023, 2025)
  - Press Notes & CGRF notes
  - RAPDRP / GIS module references
- Easily extended — drop in a new PDF and re-run one command (see Slide 9).

---

## Slide 6 — 🔴 LIVE DEMO

**Demo script (run these in order):**

1. **Simple lookup** — "What is the subsidized electricity tariff for registered Gaushalas?"
   → Show the answer + the cited circular (SC U-01/2026).
2. **Follow-up (memory)** — "When did that take effect?"
   → Shows it remembers context within the conversation.
3. **Out-of-scope guardrail** — "Who won the cricket match yesterday?"
   → Shows it refuses politely: *"I don't have information about that…"*
4. **Citation** — point out the `[Source: ...]` reference in a technical answer.
5. **Streaming** — note the answer types out live (token-by-token), like a real assistant.

🗣 *Have these questions pre-typed. If the network/API is down, fall back to the screenshots on Slide 7.*

---

## Slide 7 — Demo Screenshots (backup)

_[Paste 2–3 screenshots here as a fallback in case live demo fails:]_
- A grounded answer with a citation
- The "no information" guardrail response
- The chat UI on screen

---

## Slide 8 — Under the Hood (for technical reviewers)

| Layer | Technology |
|---|---|
| Frontend | Vue 3 + Vite + Tailwind |
| Backend | FastAPI (Python), streaming responses (SSE) |
| AI models | OpenAI `gpt-4o-mini` (chat) + `text-embedding-3-small` (search) |
| Retrieval | Cosine similarity over embedded document chunks |
| Sessions | Per-user chat memory (last 20 messages) |

- Clean separation: config, retrieval, chat, sessions, API.
- Runs as **one server** in production (API + UI on one origin).

---

## Slide 9 — Keeping It Up to Date

Adding a new circular is a **one-command** operation:

```
1. Drop the new PDF into the UHBVN/ folder
2. Run:  python ingest.py --pdf-dir ../UHBVN --append
3. Restart the backend
```

- Extracts text → chunks → embeds → merges into the knowledge base.
- Only processes *new* files (fast, low cost).
- No code changes, no AI retraining needed.

🗣 *Message for management: "Policy changes? The bot is current the same day — no developer needed."*

---

## Slide 10 — Trust & Safety

- **Grounded answers only** — refuses anything outside UHBVN documents.
- **Always cites the source** circular/clause.
- **No hallucinated figures** — the system prompt forbids inventing charges or regulations.
- Stays on-topic — declines politics, general knowledge, etc.
- API keys kept in environment config, never in code _(recently hardened)_.

---

## Slide 11 — Benefits / Impact

| For Consumers | For UHBVN Staff |
|---|---|
| Instant, plain-language answers | Faster clause lookup |
| 24/7 availability | Consistent, citable responses |
| Less dependence on office visits | Less time spent searching PDFs |
| Reduced disputes | Reduced training overhead |

---

## Slide 12 — Roadmap / What's Next

- **Scale**: move from in-memory store to a database/vector DB for many concurrent users.
- **Coverage**: auto-ingest new circulars from the UHBVN website.
- **Access**: deploy on UHBVN portal / WhatsApp / IVR.
- **Languages**: Hindi + Haryanvi support.
- **Analytics**: track top questions to spot policy confusion.
- **Auth & audit logs** for staff-facing version.

---

## Slide 13 — Q&A / Thank You

**Likely questions & quick answers:**

- *"Can it make mistakes?"* — It only answers from official docs and cites them; if unsure, it says so.
- *"What does it cost to run?"* — Pay-per-use AI API; small per-query cost, no infrastructure to maintain.
- *"How do we add the latest circular?"* — One command, same day (Slide 9).
- *"Is our data safe?"* — Documents are public circulars; no consumer PII is stored.

**Thank you — Questions?**
_[Contact / next steps]_
