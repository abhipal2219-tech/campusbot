from knowledge_base import build_knowledge_base
from vector_store import VectorStore

import requests
import json

GROQ_KEY = "YOUR_GROQ_API_KEY_HERE"

WELCOME_BANNER = """
========================================
    🎓 UEM KOLKATA CAMPUS AI BOT 🎓
========================================
Powered by Groq Llama-3 & Local RAG
(Type 'quit' to exit)
"""

def call_groq(query: str, context: str) -> str:
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_KEY}",
        "Content-Type": "application/json"
    }
    system_prompt = (
        "You are 'Campus Connect' — the official AI assistant for UEM Kolkata campus ONLY.\n"
        "STRICT RULES:\n"
        "1. ONLY use the [CAMPUS DATA] below. NEVER use training knowledge.\n"
        "2. If the answer is NOT in the data, say: 'I don't have that information. Please check the notice board.'\n"
        "3. NEVER answer about celebrities, sports, maths, coding, or anything outside UEM campus.\n"
        "4. Use bold (**text**) for key values. Keep answers concise.\n\n"
        "[CAMPUS DATA]\n" + context
    )
    
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query}
        ],
        "temperature": 0,
        "max_tokens": 400
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"Error calling AI: {e}"

def generate_answer(query: str, results: list[dict]) -> str:
    # High confidence threshold
    high_confidence_results = [r for r in results if r["score"] > 0.15]
    
    if not high_confidence_results:
        # Check for campus relevance keywords
        campus_keywords = ["section", "room", "block", "floor", "teacher", "faculty", "mentor", "cabin", "where", "find", "who", "list", "dept", "library", "cafeteria", "gym", "office"]
        is_relevant = any(kw in query.lower() for kw in campus_keywords)
        
        if not is_relevant:
            return (
                "👋 I'm specifically trained as a Campus Navigator for UEM Kolkata.\n"
                "I couldn't find a confident answer for your query. Try asking about a room, section, or teacher!"
            )
        return "I'm sorry, I couldn't find any specific information for that query."

    # Process only high confidence results
    results = high_confidence_results

    answer_lines = [f">> Results for: \"{query}\"\n"]

    for i, result in enumerate(results, 1):
        score = result["score"]
        meta = result["metadata"]
        src_type = meta.get("type", "")

        if src_type == "room":
            line = f"  {i}. 🏛️  {meta['use']}\n     📍 {meta['bld']} | {meta['floor']} | Room {meta['room']}"
        elif src_type == "section":
            line = f"  {i}. [SECTION] Section {meta['section']}\n     📍 {meta['block']} | {meta['floor']} | Room {meta['room']}\n     👨‍🏫 Teacher: {meta['classTeacher']['name']}"
        elif src_type == "faculty":
            line = f"  {i}. [FACULTY] {meta['name']} ({meta['code']})\n     🏢 Dept: {meta['dept']}\n     🚪 Cabin: {meta['room'] or 'Not recorded'}"
        else:
            line = f"  {i}. {result['text']}"

        answer_lines.append(line)
        answer_lines.append(f"     [Score: {score:.2f}]\n")

    return "\n".join(answer_lines)

def main():
    print(WELCOME_BANNER)
    db = build_knowledge_base()

    while True:
        try:
            query = input("You: ").strip()
            if not query: continue
            if query.lower() in ("quit", "exit", "bye", "q"): break
            
            results = db.search(query, top_k=5)
            
            if results:
                context = "\n".join([r["text"] for r in results])
                ai_answer = call_groq(query, context)
                print(f"\nBot:\n{ai_answer}\n")
            else:
                print("\nBot:\nI'm sorry, I couldn't find any information on that. Try asking about a specific section or room.\n")
        except (EOFError, KeyboardInterrupt):
            break

if __name__ == "__main__":
    main()
