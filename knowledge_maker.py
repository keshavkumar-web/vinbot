import pickle
from pathlib import Path
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
# The OpenAI SDK reads OPENAI_API_KEY from the environment / .env file.
# Never hardcode the key here.
client = OpenAI()

# -----------------------------
# CONFIG
# -----------------------------

KNOWLEDGE_FOLDER = "knowledge"
OUTPUT_FILE = "knowledge_db.pkl"

EMBED_MODEL = "text-embedding-3-small"

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200


# -----------------------------
# HELPERS
# -----------------------------

def chunk_text(text, chunk_size, overlap):

    chunks = []

    start = 0

    while start < len(text):

        end = start + chunk_size

        chunks.append(text[start:end])

        start += chunk_size - overlap

    return chunks


def create_embedding(text):

    response = client.embeddings.create(
        model=EMBED_MODEL,
        input=text
    )

    return response.data[0].embedding


# -----------------------------
# READ DOCUMENTS
# -----------------------------

database = []

for path in Path(KNOWLEDGE_FOLDER).rglob("*"):

    if not path.is_file():
        continue

    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"Skipping {path}: {e}")
        continue

    chunks = chunk_text(
        text,
        CHUNK_SIZE,
        CHUNK_OVERLAP
    )

    for i, chunk in enumerate(chunks):

        print(f"Embedding {path.name} chunk {i}")

        database.append({
            "source": str(path),
            "chunk_id": i,
            "text": chunk,
            "embedding": create_embedding(chunk)
        })


with open(OUTPUT_FILE, "wb") as f:
    pickle.dump(database, f)

print("\nKnowledge database created.")