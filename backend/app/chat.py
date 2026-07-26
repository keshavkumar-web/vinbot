"""Chat orchestration: assemble the prompt and stream the model's reply.

This is the streaming equivalent of the message-building block in the original
CLI loop, extracted so the API can reuse it per request/session.
"""

import re
from collections.abc import Iterator

from . import config, followup, glossary, rag, tables
from .rag import client

# A transformer DAMAGE/FAILURE RATE question (either word order). Routed
# deterministically to the "% Damage rate" column so a contextualise hiccup or a
# "could not find" prior can't derail it.
_TRANSFORMER_RATE_RE = re.compile(
    r"\b(?:transformer|dt|dtr)\b.{0,25}\b(?:damage|failure)\s+rate\b"
    r"|\b(?:damage|failure)\s+rate\b.{0,25}\b(?:transformer|dt|dtr)\b", re.I)

# A single-term DEFINITION / abbreviation question ("what is PT?", "define OA",
# "full form of SAIFI", "what does DSM stand for"). Deliberately NARROW: the subject
# must be a SINGLE token, so a numeric "what is the collection efficiency?" and
# multi-word terms ("what is AT&C Loss?", handled downstream) never match — only the
# lone-abbreviation case, which a stale numeric context must not be able to hijack.
_ABBREV_Q_RE = re.compile(
    r"^\s*(?:"
    r"what(?:'s|\s+is|\s+are|\s+does|\s+do)?\s+"
    r"|define\s+|expand\s+"
    r"|(?:full\s*form|meaning|expansion|long\s*form|abbreviation)\s+(?:of\s+)?"
    r")"
    r"(?:the\s+)?(?P<term>[A-Za-z][\w&./-]{0,15})"
    r"(?:\s+(?:stands?\s+for|means?|abbreviation))?"
    r"\s*[?.!]*\s*$", re.I)


def contextualize(history: list[dict], user_input: str, *,
                  rewriter: "followup.Rewriter | None" = None) -> str:
    """Resolve the latest message into a standalone question via conversation.

    Returns ``user_input`` unchanged when there is no history, when the feature
    is disabled, or if the rewriter errors — so routing never regresses to worse
    than the stateless behaviour. ``rewriter`` is injectable for offline tests.
    """
    if not history or not config.ENABLE_FOLLOWUP_CONTEXT:
        return user_input
    # A clearly self-contained question is routed as-is (deterministic), so stale
    # context can't leak into it and we skip an unnecessary LLM call.
    if followup.is_self_contained(user_input):
        return user_input
    rewriter = rewriter or followup.default_rewriter
    try:
        return rewriter(history, user_input) or user_input
    except Exception as exc:  # noqa: BLE001 — never fail the turn on a rewrite hiccup
        print(f"[chat] follow-up contextualisation failed: {exc}")
        return user_input


def build_messages(history: list[dict], user_input: str, context: str) -> list[dict]:
    """Construct the message list sent to the chat model.

    Order: system prompt -> prior history -> (optional) retrieved knowledge ->
    the new user message.
    """
    messages: list[dict] = [{"role": "system", "content": config.SYSTEM_PROMPT}]
    messages.extend(history)

    if context:
        messages.append(
            {
                "role": "system",
                "content": (
                    "Use the retrieved knowledge when relevant.\n\n"
                    "If the retrieved knowledge is not useful, use the conversation "
                    "history and your own reasoning, staying within your role.\n\n"
                    "Retrieved knowledge:\n\n"
                    f"{context}"
                ),
            }
        )

    messages.append({"role": "user", "content": user_input})
    return messages


def stream_answer(history: list[dict], user_input: str) -> Iterator[str]:
    """Retrieve context and yield the assistant's reply token-by-token.

    Routing puts correctness first:
      * answer    -> a verified figure exists: return it deterministically
                     (the number never passes through the LLM, so it can't be
                     altered) with row/column provenance.
      * clarify   -> the question hit a table but is ambiguous: ask which
                     metric/circle, rather than guessing a column.
      * not_found -> the question hit a table but that exact cell is absent:
                     say so plainly instead of fabricating a value.
      * prose     -> not a verified-table question: fall back to vector RAG over
                     the circulars, under a prompt that forbids inventing stats.
    """
    # PENDING transformer clarification: if our last message was the transformer
    # clarification, this message is the user PICKING an option ("Damaged transformer
    # count", "damage rate") — resolve it FIRST, remembering the clarified district.
    # Fires only immediately after that clarification, so nothing else is affected.
    if history:
        pend = followup.pending_transformer_reply(history, user_input)
        if pend:
            yield pend
            return

    # A BATCH of definition questions ("What is ACS?\nWhat is ARR?\n…") is resolved
    # deterministically from the glossary — reliable, unlike the RAG multi-question
    # path which refused several. Only fires when >=2 segments are known terms, so a
    # numeric multi-part prompt ("connections and total load") is left untouched.
    batch = glossary.define_multi(user_input)
    if batch:
        yield batch
        return

    # A category-list request ("show safety abbreviations", "list metering terms")
    # is answered deterministically from the glossary's Category fields, avoiding the
    # RAG hallucination (e.g. SE mislabelled "Safety Engineer"). Requires an explicit
    # "…terms/abbreviations/categories" phrasing + a real category match, so numeric
    # and follow-up queries are never affected.
    cat_list = glossary.list_category(user_input)
    if cat_list:
        yield cat_list
        return

    # A single-term DEFINITION question ("what is PT?", "define OA", "full form of
    # SAIFI") is resolved from the glossary on the RAW input HERE — before the numeric
    # slot/contextualise path — so a stale numeric turn can't rewrite an abbreviation
    # question into a "name the circle" clarify. Known term -> definition; an explicit
    # but UNKNOWN term ("what is ABCXYZ?") -> RAG (a clean "could not find"), never the
    # numeric clarify. Scoped to a single-token subject, so numeric "what is the
    # collection efficiency?" and slot follow-ups are untouched.
    if _ABBREV_Q_RE.match(user_input):
        gloss = glossary.define(user_input)
        if gloss:
            yield gloss
            return
        yield from _stream_rag_answer(history, user_input)
        return

    # A question ABOUT this conversation / our own previous answer ("which count
    # is this?", "where did that come from?") is answered from the history — no
    # new SQLite or RAG lookup — so we never wrongly say "not found" for a value
    # we just gave. The history's figures came from SQLite; we only restate them.
    # A non-comparison question about our own prior answer is answered from the
    # history (no new SQLite/RAG lookup) so we never wrongly say "not found".
    if (history and followup.is_meta_question(user_input)
            and not followup.is_comparison_question(user_input)):
        yield from _stream_meta_answer(history, user_input)
        return

    # Comparisons ("which is higher?", "which is greater between A and B?") are
    # answered DETERMINISTICALLY — never by the LLM, which could invent numbers.
    # ``compare_answer`` compares the grounded history, but RE-FETCHES from SQLite
    # when the question's subject differs from the recent facts (e.g. "which has
    # more CONNECTIONS?" after a LOAD comparison fetches connection counts, not KW).
    if followup.is_comparison_question(user_input):
        result = followup.compare_answer(history, user_input)
        if result:
            yield result
            return
        # Nothing numeric to compare — a CONCEPTUAL "what is the difference?" between
        # two DEFINED terms (SLDC vs RLDC). Resolve it against the conversation and
        # let RAG explain, instead of a flat "could not find".
        if history and config.ENABLE_FOLLOWUP_CONTEXT:
            try:
                resolved = followup.default_rewriter(history, user_input) or user_input
            except Exception as exc:  # noqa: BLE001
                print(f"[chat] comparison rewrite failed: {exc}")
                resolved = user_input
            yield from _stream_rag_answer(history, resolved)
            return

    # Domain-switch guard: an elliptical follow-up naming the TRANSFORMER domain
    # ("DT failure rate", "transformer damage") while the active context is a
    # different dataset must NOT inherit the old metric (which would return an
    # unrelated Domestic count). Route to the transformer dataset, or ASK when the
    # metric is ambiguous. Scoped to transformer keywords — all other follow-ups
    # are untouched. Runs BEFORE prose-continuation so a prior transformer
    # clarification doesn't get mistaken for a prose anchor.
    if history and config.ENABLE_FOLLOWUP_CONTEXT and not followup.is_self_contained(user_input):
        switched = followup.transformer_domain_switch(history, user_input)
        if switched:
            yield switched
            return

    # A transformer DAMAGE/FAILURE RATE query -> deterministic damaged_transformers
    # route on the RAW input (so a contextualise hiccup or a "could not find" prior
    # can't derail it). Runs AFTER the follow-up guard, so a connection->transformer
    # follow-up still gets that guard's clarification.
    if _TRANSFORMER_RATE_RE.search(user_input):
        rated = tables.respond(user_input)
        if rated.get("status") in ("answer", "clarify"):
            yield rated["text"]
            return

    # Prose continuation: if the last answer was a PROSE/RAG reply and this is an
    # elliptical follow-up, stay in prose so the numeric path can't hijack a shared
    # word — "security deposit" then "for domestic?" gives the domestic DEPOSIT
    # rate, not the domestic connection count.
    if (history and config.ENABLE_FOLLOWUP_CONTEXT
            and followup.is_prose_followup(history, user_input)):
        resolved = contextualize(history, user_input)
        gloss = glossary.define(user_input) or glossary.define(resolved)
        if gloss:  # a known abbreviation -> deterministic definition, no RAG guess
            yield gloss
            return
        yield from _stream_rag_answer(history, resolved)
        return

    # Superlative refinement: after "which circle has the highest X?", a follow-up
    # naming a sub-group ("what about rural?", "and urban?") re-runs the SAME
    # ranking within that group (top rural circle), not the aggregate Total Rural.
    if history and config.ENABLE_FOLLOWUP_CONTEXT and not followup.is_self_contained(user_input):
        refined = followup.superlative_refinement(history, user_input)
        if refined:
            yield refined
            return

    # Deterministic conversational slots FIRST: recover the active dataset /
    # entity / metric from the last grounded answer and update only the dimension
    # this message names ("Total?", "Zone-I?", "Load?", "Breakup?"). This survives
    # a chain the LLM rewriter can drop. It only short-circuits on a definitive
    # answer; anything else falls through to the LLM path below, so it can only
    # add correct answers, never regress.
    if history and config.ENABLE_FOLLOWUP_CONTEXT and not followup.is_self_contained(user_input):
        try:
            plan = followup.resolve_followup(history, user_input)
        except Exception as exc:  # noqa: BLE001 — never fail the turn on the slot path
            print(f"[chat] slot follow-up failed: {exc}")
            plan = None
        if plan:
            slotted = tables.respond(
                plan["query"], extractor=lambda q, s, i=plan["intent"]: i)
            if slotted.get("status") == "answer":
                yield slotted["text"]
                return

    # Resolve follow-ups / short replies against the conversation FIRST, then
    # route the standalone question exactly as a fresh one. Numbers still come
    # from SQLite and prose from RAG — this only clarifies *what* was asked.
    resolved = contextualize(history, user_input)

    routed = tables.respond(resolved)
    status = routed["status"]

    if status == "answer":
        yield routed["text"]
        return

    # Deterministic glossary definition BEFORE giving a clarify / not-found / RAG
    # answer, so a known abbreviation ("AT&C Loss", "what is SAIFI?") reliably
    # resolves. Runs after the numeric path, so it never overrides a real data
    # answer (e.g. "what is the collection efficiency?").
    gloss = glossary.define(user_input) or glossary.define(resolved)
    if gloss:
        yield gloss
        return

    if status in ("clarify", "not_found"):
        yield routed["text"]
        return

    yield from _stream_rag_answer(history, resolved)


def _stream_rag_answer(history: list[dict], resolved: str) -> Iterator[str]:
    """Vector-RAG over the circulars, under the figure-forbidding prompt.

    Multi-part prompts are decomposed and retrieved per sub-question so a turn
    asking several things doesn't starve most of them of grounding."""
    scored = rag.retrieve_context_multi(resolved)
    context = rag.format_context(scored)
    messages = build_messages(history, resolved, context)

    stream = client.chat.completions.create(
        model=config.CHAT_MODEL,
        messages=messages,
        temperature=0,  # deterministic: don't improvise figures the docs don't have
        stream=True,
    )
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


def _stream_meta_answer(history: list[dict], user_input: str) -> Iterator[str]:
    """Answer a question about the conversation itself, grounded in the history."""
    messages: list[dict] = [{"role": "system", "content": config.META_SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_input})
    stream = client.chat.completions.create(
        model=config.CHAT_MODEL, messages=messages, temperature=0, stream=True,
    )
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta

