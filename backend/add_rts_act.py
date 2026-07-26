"""Ingest RTS_Act.pdf into the prose knowledge base — incremental & idempotent.

The Haryana Right to Service Act notification lists the DESIGNATED OFFICER and
stipulated time limit per service — content the compendium extraction didn't
surface cleanly, so questions like "who is the designated officer for a new
connection?" previously clarified. This APPENDS the RTS chunks to
`knowledge_db.pkl` WITHOUT re-embedding the existing corpus (each machine has its
own pkl — dev and prod differ, so never copy one over the other; run this on each).

Safe to re-run: prior `RTS_Act.pdf` entries are removed first, and the pkl is
backed up to `*.bak`. After running, restart the service (the KB is loaded at
startup).

    python add_rts_act.py            # from backend/, venv active, OPENAI_API_KEY set
"""

from __future__ import annotations

import os
import pickle
import re
import shutil
import sys

from pypdf import PdfReader

from app import config, rag

SRC = os.getenv("RTS_PDF", os.path.join(config.BACKEND_DIR, "RTS_Act.pdf"))
# Keep English content; drop the legacy-Hindi-font pages (they embed as noise).
_EN = re.compile(r"\b(?:the|and|shall|of|to|in|for|service|officer|days|within|"
                 r"authority|section|act|connection|meter)\b", re.I)

# The RTS schedule is a 7-column table (…Designated officer | First GRA | Second
# GRA). Flattened prose makes the LLM confuse the columns, so we parse each row
# into a self-describing, labelled sentence — the designated officer can't be
# mistaken for the appellate authority.
_OFF = r"(?:SDO|XEN|SE|CE|JE|AEE|AE)\s*\[[^\]]{1,25}\]"
_LEAF = re.compile(rf"(\d+)\s*days?\s+({_OFF})\s+({_OFF})\s+({_OFF})", re.I)
_SUB = re.compile(r"\(i{1,3}v?\)|Above\s*33\s*KV|33\s*KV|11\s*KV|LT\s*supply|\bLT\b", re.I)
# a sub-service header like "a) Shifting of meter/ services connection"
_SUBSVC = re.compile(r"\b[ab]\)\s*([A-Za-z][A-Za-z /]{4,45})")


def _labeled_rows(text: str) -> list[str]:
    norm = re.sub(r"\s+", " ", text)
    norm = re.sub(r"HARYANA GOVT\. GAZ\..*?1 2 3 4 5 6 7", " ", norm)
    norm = re.sub(r"Sr\. No\. Name of the Department.*?1 2 3 4 5 6 7", " ", norm)
    rows = []
    for b in re.split(r"\bEnergy Department\b", norm)[1:]:
        sm = re.match(r"\s*(.+?)(?=\s*(?:\(i\)|a\)|from receipt|Approval|\d+\s*days))", b, re.I)
        parent = re.sub(r"\s+", " ", (sm.group(1) if sm else b[:60])).strip(" .")
        if len(parent) < 4:
            continue
        last, cur_sub = 0, ""
        for lm in _LEAF.finditer(b):
            time, do, fgra, sgra = (re.sub(r"\s+", " ", g).strip() for g in lm.groups())
            seg = b[last:lm.start()]; last = lm.end()
            ssm = _SUBSVC.search(seg)          # distinct a)/b) sub-service, e.g. meter vs lines
            if ssm:
                cur_sub = ssm.group(1).strip(" /")
            vm = _SUB.search(seg)              # voltage tier
            volt = vm.group(0).strip() if vm else ""
            service = parent + (f" — {cur_sub}" if cur_sub else "")
            rows.append(
                f"Right to Service Act — {service}" + (f" ({volt})" if volt else "")
                + f": Designated Officer is {do}; First Grievance Redressal Authority "
                + f"is {fgra}; Second Grievance Redressal Authority is {sgra}; "
                + f"stipulated time limit {time} days.")
    return rows


def _intro_chunks(text: str) -> list[str]:
    """The notification's intro paragraph (before the schedule) for general RTS
    questions — char-chunked, English only."""
    head = text[:text.find("Release of Temporary")] if "Release of Temporary" in text else text[:1500]
    step = max(1, config.CHUNK_SIZE - config.CHUNK_OVERLAP)
    return [c.strip() for i in range(0, len(head), step)
            if (c := head[i:i + config.CHUNK_SIZE]).strip() and len(_EN.findall(c)) >= 4]


def _chunks(text: str) -> list[str]:
    return _labeled_rows(text) + _intro_chunks(text)


def main() -> int:
    if not os.path.exists(SRC):
        print(f"RTS PDF not found at {SRC} (set RTS_PDF=... to override)."); return 1
    pkl = config.KNOWLEDGE_DB_PATH
    if not os.path.exists(pkl):
        print(f"knowledge_db.pkl not found at {pkl}."); return 1

    text = "\n".join((p.extract_text() or "") for p in PdfReader(SRC).pages)
    chunks = _chunks(text)
    if not chunks:
        print("No English chunks extracted; aborting (is the PDF scanned?)."); return 1

    shutil.copy(pkl, pkl + ".bak")
    with open(pkl, "rb") as f:
        db = pickle.load(f)
    template = {k: None for k in db[0].keys()} if db else {"source": None, "text": None, "embedding": None}
    db = [d for d in db if d.get("source") != "RTS_Act.pdf"]  # idempotent refresh
    before = len(db)

    for c in chunks:
        entry = dict(template)
        entry["source"], entry["text"] = "RTS_Act.pdf", c
        entry["embedding"] = rag.create_embedding(c)
        db.append(entry)

    with open(pkl, "wb") as f:
        pickle.dump(db, f)
    print(f"RTS_Act.pdf ingested: {len(chunks)} chunks | knowledge_db {before} -> {len(db)}")
    print(f"backup: {pkl}.bak  —  restart the service to load the new KB.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
