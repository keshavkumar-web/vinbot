import sys
from app import chat
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def run(title, msgs):
    print("\n" + "=" * 70 + f"\n{title}\n" + "=" * 70)
    h = []
    for m in msgs:
        resolved = chat.contextualize(h, m)
        ans = "".join(chat.stream_answer(h, m))
        h.append({"role": "user", "content": m})
        h.append({"role": "assistant", "content": ans})
        first = [l for l in ans.splitlines() if l.strip() and not l.startswith("(Source")][:2]
        print(f"  Q: {m!r}   (rewritten: {resolved!r})")
        print(f"     A: {' | '.join(first)}")


run("SEQ1: metric/entity inheritance chain", [
    "Domestic count in Ambala",
    "And for Karnal?",
    "Total?",
    "Zone-I?",
])

run("SEQ2: segregation follow-up", [
    "Total connection count",
    "Segregation on connection type",
])

run("SEQ3: Domestic -> Total -> Load -> Breakup", [
    "Domestic connections in Ambala",
    "Total?",
    "Load?",
    "Breakup?",
])
