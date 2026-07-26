"""Build / rebuild the knowledge database for the UHBVN Assistant.

Pipeline:  PDFs / text files  ->  chunks  ->  embeddings  ->  knowledge_db.pkl

Usage (from the backend/ directory, with the venv active):

    python ingest.py                 # rebuild from everything in backend/knowledge
    python ingest.py --pdf-dir ../UHBVN   # also extract any *.pdf found there first
    python ingest.py --append        # keep existing DB, only embed NEW/changed files

Notes
-----
* Reads the OpenAI key + all tunables (models, chunk size, paths) from app.config,
  so there is a single source of truth and no hardcoded secrets here.
* PDF extraction needs ``pypdf`` (``pip install pypdf``). Text files need nothing.
* Embeddings are sent in batches to be fast and cheap.
"""

from __future__ import annotations

import argparse
import os
import pickle
from pathlib import Path

from app import config
from app.rag import client  # reuse the single configured OpenAI client

BATCH_SIZE = 100  # how many chunks to embed per API call


# --------------------------------------------------------------------------- #
# 1. Turn source files into plain text
# --------------------------------------------------------------------------- #
def extract_pdfs(pdf_dir: Path, out_dir: Path) -> int:
    """Extract every *.pdf in ``pdf_dir`` to a matching *.txt in ``out_dir``.

    Returns the number of PDFs extracted. Skips PDFs whose .txt already exists.
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        print("[ingest] pypdf not installed; skipping PDF extraction. "
              "Run 'pip install pypdf' to enable it.")
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for pdf in sorted(pdf_dir.glob("*.pdf")):
        txt_path = out_dir / (pdf.stem + ".txt")
        if txt_path.exists():
            continue
        try:
            reader = PdfReader(str(pdf))
            pages = [page.extract_text() or "" for page in reader.pages]
            text = f"Source document: {pdf.name}\n\n" + "\n".join(pages)
            txt_path.write_text(text, encoding="utf-8")
            print(f"[ingest] Extracted {pdf.name} -> {txt_path.name}")
            count += 1
        except Exception as exc:  # noqa: BLE001
            print(f"[ingest] FAILED to extract {pdf.name}: {exc}")
    return count


# --------------------------------------------------------------------------- #
# 2. Chunk text
# --------------------------------------------------------------------------- #
def chunk_text(text: str, size: int, overlap: int) -> list[str]:
    """Split text into overlapping windows; drop blank tail chunks."""
    chunks, start = [], 0
    while start < len(text):
        chunk = text[start:start + size].strip()
        if chunk:
            chunks.append(chunk)
        start += size - overlap
    return chunks


# --------------------------------------------------------------------------- #
# 3. Embed in batches
# --------------------------------------------------------------------------- #
def embed_batch(texts: list[str]) -> list[list[float]]:
    resp = client.embeddings.create(model=config.EMBED_MODEL, input=texts)
    return [d.embedding for d in resp.data]


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> None:
    parser = argparse.ArgumentParser(description="Build the UHBVN knowledge DB.")
    parser.add_argument("--pdf-dir", help="Extract *.pdf from here before ingesting.")
    parser.add_argument("--append", action="store_true",
                        help="Keep existing DB; only embed files not already in it.")
    args = parser.parse_args()

    knowledge_dir = Path(config.KNOWLEDGE_FOLDER)
    db_path = Path(config.KNOWLEDGE_DB_PATH)

    # Optionally extract PDFs into the knowledge folder first.
    if args.pdf_dir:
        extract_pdfs(Path(args.pdf_dir), knowledge_dir)

    # Load existing DB if appending, so we can skip already-ingested sources.
    database: list[dict] = []
    existing_sources: set[str] = set()
    if args.append and db_path.exists():
        with open(db_path, "rb") as f:
            database = pickle.load(f)
        existing_sources = {item["source"] for item in database}
        print(f"[ingest] Appending to existing DB with {len(database)} chunks.")

    # Collect all chunks that still need embedding.
    pending: list[dict] = []  # {source, chunk_id, text}
    for path in sorted(knowledge_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".txt", ".md"}:
            continue
        source = str(path)
        if source in existing_sources:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            print(f"[ingest] Skipping {path.name}: {exc}")
            continue
        for i, chunk in enumerate(chunk_text(text, config.CHUNK_SIZE, config.CHUNK_OVERLAP)):
            pending.append({"source": source, "chunk_id": i, "text": chunk})

    if not pending:
        print("[ingest] Nothing new to embed.")
    else:
        print(f"[ingest] Embedding {len(pending)} chunks "
              f"in batches of {BATCH_SIZE}...")
        for start in range(0, len(pending), BATCH_SIZE):
            batch = pending[start:start + BATCH_SIZE]
            vectors = embed_batch([c["text"] for c in batch])
            for item, vec in zip(batch, vectors):
                item["embedding"] = vec
                database.append(item)
            print(f"[ingest]   {min(start + BATCH_SIZE, len(pending))}/{len(pending)}")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    with open(db_path, "wb") as f:
        pickle.dump(database, f)
    print(f"\n[ingest] Done. {len(database)} total chunks written to {db_path}")


if __name__ == "__main__":
    main()
