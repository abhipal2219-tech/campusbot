"""Quick test script for the RAG pipeline."""
from knowledge_base import build_knowledge_base

db = build_knowledge_base()
print()

queries = [
    "Where is the cafeteria?",
    "Who is the mentor for Section A?",
    "Where is Section G class?",
    "Where is the library?",
    "Who teaches Section K?",
]

for q in queries:
    results = db.search(q, top_k=2)
    print(f"Q: {q}")
    for r in results:
        snippet = r["text"][:85]
        score   = r["score"]
        src     = r["metadata"].get("type", "?")
        print(f"  [{score:.3f}] [{src}] {snippet}")
    print()
