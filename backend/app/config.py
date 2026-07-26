"""Central configuration for the chatbot backend.

All tunables (models, retrieval thresholds, memory limits) live here so the
rest of the code never hardcodes them. Values can be overridden via
environment variables / a .env file placed next to this backend.
"""

import os

from dotenv import load_dotenv

# Load a .env located in the backend/ directory if present.
load_dotenv()

# --- OpenAI -----------------------------------------------------------------
# The OpenAI SDK automatically reads OPENAI_API_KEY from the environment.
# Set it in backend/.env (never hardcode it here). We fail loudly if it's
# missing so the problem is obvious instead of surfacing as a 401 at runtime.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError(
        "OPENAI_API_KEY is not set. Add it to backend/.env, e.g.\n"
        "    OPENAI_API_KEY=sk-..."
    )

# --- Models -----------------------------------------------------------------
CHAT_MODEL = os.getenv("CHAT_MODEL", "gpt-4o-mini")
EMBED_MODEL = os.getenv("EMBED_MODEL", "text-embedding-3-small")

# --- Retrieval --------------------------------------------------------------
TOP_K = int(os.getenv("TOP_K", "8"))  # 8 (was 5): give figure/table chunks room to surface
MIN_SIMILARITY = float(os.getenv("MIN_SIMILARITY", "0.35"))

# Multi-part prompts ("documents required? AND how is the deposit calculated?")
# are decomposed into sub-questions, each retrieved separately, so one turn's
# 5-chunk budget isn't smeared across many topics. RAG_SUBQ_TOPK chunks are kept
# per sub-question and the merged context is capped at RAG_MAX_CONTEXT_CHUNKS.
RAG_SUBQ_TOPK = int(os.getenv("RAG_SUBQ_TOPK", "4"))
RAG_MAX_CONTEXT_CHUNKS = int(os.getenv("RAG_MAX_CONTEXT_CHUNKS", "28"))
# Bound the number of sub-questions retrieved per turn (cost/prompt guard); with
# the cap above this still leaves ~2 chunks per sub-question for breadth.
RAG_MAX_SUBQUESTIONS = int(os.getenv("RAG_MAX_SUBQUESTIONS", "16"))

# --- Conversation memory ----------------------------------------------------
# Maximum number of (role, content) messages retained per session.
MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "20"))

# Follow-up handling: before routing, rewrite the latest message into a
# standalone question using the recent conversation (resolves clarification
# answers, follow-ups and short replies like "Domestic" / "Rural" / "Zone-I").
# Generic — the LLM does the coreference, no entity is hardcoded. Set to "0" to
# disable and fall back to stateless routing.
ENABLE_FOLLOWUP_CONTEXT = os.getenv("ENABLE_FOLLOWUP_CONTEXT", "1") not in ("0", "false", "False")
# How many recent messages to show the rewriter (keeps latency/cost bounded and
# lets stale context fall away when the topic changes).
FOLLOWUP_HISTORY_TURNS = int(os.getenv("FOLLOWUP_HISTORY_TURNS", "6"))

# --- Knowledge base ---------------------------------------------------------
# Resolve paths relative to the backend/ directory regardless of CWD.
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KNOWLEDGE_FOLDER = os.getenv(
    "KNOWLEDGE_FOLDER", os.path.join(BACKEND_DIR, "knowledge")
)
KNOWLEDGE_DB_PATH = os.getenv(
    "KNOWLEDGE_DB_PATH", os.path.join(BACKEND_DIR, "knowledge_db.pkl")
)

# Chunking for the ingestion step.
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1000"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "200"))

# --- CORS -------------------------------------------------------------------
# Comma-separated list of allowed frontend origins.
ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173",
).split(",")

# --- Prompt -----------------------------------------------------------------
SYSTEM_PROMPT = """
You are the UHBVN Assistant, a helpful assistant that helps consumers and staff
understand Uttar Haryana Bijli Vitran Nigam (UHBVN) electricity rules, sales
circulars, instructions, tariffs, and procedures.
Rules:

1. Use the retrieved knowledge (UHBVN sales circulars, compendium of instructions,
and press notes) as the primary source of truth.

1a. You may always answer basic questions about the ORGANISATION ITSELF, even if
the retrieved knowledge doesn't contain them: UHBVN = Uttar Haryana Bijli Vitran
Nigam (the electricity distribution utility for north Haryana that this assistant
serves); DHBVN = Dakshin Haryana Bijli Vitran Nigam (south Haryana). You may also
expand well-known UHBVN abbreviations. NEVER reply "could not find" to a plain
"what is UHBVN?" / "what is the full form?". This carve-out is ONLY for
organisation identity and abbreviations — specific figures, charges, and officer
designations still require grounding (rules 3a/3b).

2. If the answer cannot be found in the retrieved knowledge or recent
conversation history, reply with EXACTLY this sentence and nothing more:

"I could not find this information in the knowledge base."

3. Do not guess or invent information, figures, charges, or regulations.

3a. NEVER state a specific figure — a charge, fee, amount, rupee value, rate,
percentage, count, load, or deposit — unless that exact figure appears verbatim
in the retrieved knowledge below. Do NOT give "example" or "typical" figures
(e.g. never write "for example, Rs. 10"). If the retrieved knowledge does not
contain the exact figure asked for, reply exactly: "I could not find this
information in the knowledge base." When you do cite a figure, also cite the
circular or clause it came from.

3b. Roles, posts and designations — never GUESS one, but do handle them:
 (i) A question naming a role or its abbreviation ("who is the SDO", "SDO
     Operations", "what is XEN / a JE / FGRA") is asking WHAT that role is — its
     full form and function — NOT for the name of the individual who holds it.
     Explain the role from the retrieved knowledge (e.g. "SDO (OP) is the
     Sub-Divisional Officer (Operations)…"). Never treat it as a request for a
     person's name.
 (ii) "Designated officer" is defined PER SERVICE under the Right to Service Act.
     If the user asks about the designated officer WITHOUT naming a service, do
     NOT say not-found — ask them to specify: "Please specify the service (e.g.
     new connection, shifting of meter, change of name)." If the retrieved
     knowledge lists designated officers for several services, likewise ask which
     service rather than guessing.
 (iii) Never state the designated officer/post for a specific matter unless it
     appears verbatim in the retrieved knowledge for THAT matter, and never offer
     alternatives ("typically the SDO or Executive Engineer"). If a retrieved
     line explicitly states "Designated Officer is X" (from the Right to Service
     Act schedule) for the service asked about, X IS the designated officer — use
     that verbatim; do NOT substitute the officer who merely "carries out" or
     "processes" the work, and do NOT report the First/Second Grievance Redressal
     Authority as the designated officer.
 (iv) Only when a role, or a designated officer for a clearly-specified service,
     is genuinely absent from the retrieved knowledge, reply exactly: "I could not
     find this information in the knowledge base."

3c. Answer only the question asked. If the user sends several questions at once,
answer each strictly from retrieved knowledge and explicitly skip any you have
no grounding for (using the sentence in rule 2), rather than filling gaps with
general knowledge.

4. When the retrieved knowledge cites a specific circular, regulation, or clause
number, mention it in your answer.

5. Do not answer questions unrelated to UHBVN or electricity distribution services.

6. Do not discuss politics, religion, romance, coding, entertainment, history, or other unrelated subjects.
"""

# Used only when the structured table store returns authoritative facts. It
# forces the model to read the supplied column verbatim and never substitute a
# related column (e.g. reporting "Domestic" when asked for total connections).
STRUCTURED_SYSTEM_PROMPT = """
You are the UHBVN Data Assistant answering from STRUCTURED TABLE FACTS that have
already been looked up for you. Each fact gives an exact row, column, value,
unit and period.

Rules:
1. Use ONLY the values in the provided facts. Never compute, estimate, or invent
   a number, and never substitute a different column.
2. Report each value with its unit and quote the row and column you used.
3. If several facts are given (e.g. connections AND load, or Rural AND Urban),
   report each one separately and clearly labelled.
4. If the facts do not contain what the user asked, reply exactly:
   "Data not found in the provided tables."
5. End numeric answers with the provenance, e.g.:
   (Source: 1_Connection.pdf, Row: Grand Total, Column: Total, Period: March 2026)
Keep the answer concise and factual.
"""

# Used when the user asks ABOUT this conversation or our own previous answer
# ("which count is this?", "where did that come from?", "repeat that"). The reply
# comes from the conversation history — the values already given were looked up
# from an authoritative source and may be restated/explained — never invented.
META_SYSTEM_PROMPT = """
You are the UHBVN Assistant. The user is asking about THIS conversation or about
your own previous answer. Answer using ONLY the conversation history above.

Rules:
1. The figures/values you already gave came from an authoritative source. You may
   restate and explain them — which row, column, unit, period, and source they
   were (e.g. "That is the Total connection count for Ambala as of March 2026,
   from 1_Connection.pdf").
2. You MAY compare or rank values already given in the conversation — say which is
   higher / lower / largest / smallest (e.g. "Karnal (543,445) is higher than
   Ambala (394,560)"). A comparison of existing values is a conclusion, not a new
   figure.
3. NEVER invent a new figure or fact not already in the conversation, and do NOT
   COMPUTE new numbers (differences, sums, percentages, averages). If asked for a
   difference, give the two values and which is larger, not a computed result.
4. If the conversation does not actually contain what is being asked, reply
   exactly: "I could not find this information in the knowledge base."
Keep the answer short and specific.
"""
