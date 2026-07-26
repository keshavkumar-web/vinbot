"""Build the knowledge base: read documents, chunk, embed (batched) and pickle.

Run from the backend/ directory:

    python knowledge_maker.py

Reads every file under ``KNOWLEDGE_FOLDER`` and writes ``KNOWLEDGE_DB_PATH``
(both configured in ``app/config.py``). Embeddings are sent in batches to the
OpenAI API so that thousands of chunks ingest in dozens of calls, not thousands.
"""

from pathlib import Path
import pickle

from app import config
from app.rag import client

EMBED_BATCH = 100  # chunks per embeddings API call


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Split text into overlapping character windows."""
    chunks: list[str] = []
    start = 0
    step = max(1, chunk_size - overlap)  # guard against zero/negative step
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start += step
    return chunks


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts in one API call."""
    response = client.embeddings.create(model=config.EMBED_MODEL, input=texts)
    # Preserve input order (API returns items with .index).
    ordered = sorted(response.data, key=lambda d: d.index)
    return [d.embedding for d in ordered]


def build() -> None:
    folder = Path(config.KNOWLEDGE_FOLDER)
    if not folder.exists():
        raise SystemExit(
            f"Knowledge folder not found: {folder}. "
            f"Create it and add some .txt documents first."
        )

    # 1) Collect all chunks (with their source metadata) up front.
    records: list[dict] = []
    for path in sorted(folder.rglob("*")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as exc:
            print(f"Skipping {path.name}: {exc}")
            continue
        for i, chunk in enumerate(chunk_text(text, config.CHUNK_SIZE, config.CHUNK_OVERLAP)):
            records.append({"source": path.name, "chunk_id": i, "text": chunk})

    total = len(records)
    print(f"Collected {total} chunks from {folder}. Embedding in batches of {EMBED_BATCH}...")

    # 2) Embed in batches.
    database: list[dict] = []
    for start in range(0, total, EMBED_BATCH):
        batch = records[start:start + EMBED_BATCH]
        embeddings = embed_batch([r["text"] for r in batch])
        for rec, emb in zip(batch, embeddings):
            rec["embedding"] = emb
            database.append(rec)
        print(f"  embedded {min(start + EMBED_BATCH, total)}/{total}", flush=True)

    # 3) Persist.
    with open(config.KNOWLEDGE_DB_PATH, "wb") as f:
        pickle.dump(database, f)

    print(f"\nKnowledge database created: {config.KNOWLEDGE_DB_PATH} "
          f"({len(database)} chunks).")


if __name__ == "__main__":
    build()
