import pickle
import numpy as np
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
# The OpenAI SDK reads OPENAI_API_KEY from the environment / .env file.
# Never hardcode the key here.
client = OpenAI()

###==> Config
CHAT_MODEL = "gpt-4o-mini"
EMBED_MODEL = "text-embedding-3-small"

TOP_K = 5
MIN_SIMILARITY = 0.35

MAX_HISTORY_MESSAGES = 20

SYSTEM_PROMPT = """
You are a helpful assistant, that is helps clients understand the requirement of the bank.
Rules:

1. Use the retrieved knowledge as the primary source of truth.

2. If the answer cannot be found in the retrieved knowledge or recent conversation history, say:

"I don't have information about that in my knowledge base."

3. Do not guess or invent information.

4. Do not answer general knowledge questions unrelated to your role.

5. Do not discuss politics, religion, romance, coding, entertainment, history, or other unrelated subjects.

"""



# Load Knowledge


with open("knowledge_db.pkl", "rb") as f:
    knowledge_db = pickle.load(f)

conversation_history = []


#Question to Embedding

def create_embedding(text):

    response = client.embeddings.create(
        model=EMBED_MODEL,
        input=text
    )

    return response.data[0].embedding

#==> Cosine Similiarity

def cosine_similarity(a, b):

    a = np.array(a)
    b = np.array(b)

    return np.dot(a, b) / (
        np.linalg.norm(a) * np.linalg.norm(b)
    )



def retrieve_context(question):

    question_embedding = create_embedding(question)

    scored = []

    for item in knowledge_db:

        score = cosine_similarity(
            question_embedding,
            item["embedding"]
        )

        if score >= MIN_SIMILARITY:
            scored.append((score, item))

    scored.sort(reverse=True)

    context = []

    for score, item in scored[:TOP_K]:

        context.append(
            f"[Source: {item['source']}]\n"
            f"{item['text']}"
        )

    return "\n\n".join(context)



# Chat Loop


while True:

    user_input = input("\nYou: ")

    if user_input.lower() in ["exit", "quit"]:
        break

    retrieved_context = retrieve_context(user_input)

    messages = [

        {
            "role": "system",
            "content": SYSTEM_PROMPT
        }

    ]

    messages.extend(conversation_history)

    if retrieved_context:

        messages.append({

            "role": "system",

            "content":
f"""
Use the retrieved knowledge when relevant.

If the retrieved knowledge is not useful,
use the conversation history and your own reasoning.
Answer question relevant to the 

Retrieved knowledge:

{retrieved_context}
"""
        })

    messages.append({

        "role": "user",
        "content": user_input

    })

    response = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=messages
    )

    answer = response.choices[0].message.content

    print("\nAssistant:", answer)

    conversation_history.append({
        "role": "user",
        "content": user_input
    })

    conversation_history.append({
        "role": "assistant",
        "content": answer
    })

    conversation_history = conversation_history[
        -MAX_HISTORY_MESSAGES:
    ]