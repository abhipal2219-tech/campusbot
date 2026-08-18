"""
app.py
------
Campus Connect — Render Web Service (Flask + Gunicorn)

Routes:
  GET  /health  →  liveness check
  POST /chat    →  { "message": "...", "history": [...] }
                ←  { "reply": "..." }
"""

import os
import json
import math
import re
from collections import Counter

from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import requests as http_client

# ── Environment ────────────────────────────────────────────────────────────────
load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
PORT         = int(os.getenv("PORT", 10000))

# ── App setup ──────────────────────────────────────────────────────────────────
app = Flask(__name__)

# Allow requests from GitHub Pages and localhost (dev)
CORS(app, resources={r"/*": {"origins": [
    "https://abhipal2219-tech.github.io",
    "http://localhost:*",
    "http://127.0.0.1:*"
]}})

# ── Data paths ─────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")


# ==============================================================================
# TF-IDF Vector Store (no external ML libraries)
# ==============================================================================
def _tokenize(text: str) -> list:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return text.split()


class VectorStore:
    def __init__(self):
        self.documents  = []
        self.metadata   = []
        self.tf_vectors = []
        self.idf        = {}
        self._dirty     = True

    def add_document(self, text: str, metadata: dict = None):
        tokens = _tokenize(text)
        counts = Counter(tokens)
        total  = len(tokens) or 1
        tf     = {t: c / total for t, c in counts.items()}
        self.documents.append(text)
        self.metadata.append(metadata or {})
        self.tf_vectors.append(tf)
        self._dirty = True

    def build_index(self):
        N = len(self.documents)
        if not N:
            return
        df = Counter()
        for tf in self.tf_vectors:
            for t in tf:
                df[t] += 1
        self.idf = {
            t: math.log((N + 1) / (count + 1)) + 1
            for t, count in df.items()
        }
        self._dirty = False

    def _tfidf(self, tf: dict) -> dict:
        return {t: v * self.idf.get(t, 0) for t, v in tf.items()}

    @staticmethod
    def _cosine(a: dict, b: dict) -> float:
        common = set(a) & set(b)
        if not common:
            return 0.0
        dot   = sum(a[k] * b[k] for k in common)
        normA = math.sqrt(sum(v ** 2 for v in a.values()))
        normB = math.sqrt(sum(v ** 2 for v in b.values()))
        return dot / (normA * normB) if normA and normB else 0.0

    def search(self, query: str, top_k: int = 5) -> list:
        if self._dirty:
            self.build_index()
        tokens  = _tokenize(query)
        counts  = Counter(tokens)
        total   = len(tokens) or 1
        q_tf    = {t: c / total for t, c in counts.items()}
        q_vec   = self._tfidf(q_tf)
        scored  = [
            (self._cosine(q_vec, self._tfidf(tf)), i)
            for i, tf in enumerate(self.tf_vectors)
        ]
        scored.sort(reverse=True)
        return [
            {"text": self.documents[i], "score": round(s, 4), "metadata": self.metadata[i]}
            for s, i in scored[:top_k] if s > 0
        ]


# ==============================================================================
# Knowledge Base — load JSON data into VectorStore at startup
# ==============================================================================
def build_knowledge_base() -> VectorStore:
    db = VectorStore()

    # Faculty
    faculty_path = os.path.join(DATA_DIR, "faculty.json")
    with open(faculty_path, encoding="utf-8") as f:
        faculty = json.load(f)
    for entry in faculty:
        text = (
            f"{entry['name']} ({entry.get('code','')}) is a faculty member "
            f"in {entry['dept']} department. Cabin: {entry.get('room') or 'Not recorded'}."
        )
        db.add_document(text, {"type": "faculty", **entry})

    # Rooms
    rooms_path = os.path.join(DATA_DIR, "rooms.json")
    with open(rooms_path, encoding="utf-8") as f:
        rooms = json.load(f)
    for entry in rooms:
        text = (
            f"{entry['use']} is located in {entry['bld']}, "
            f"{entry['floor']}, Room {entry['room']}."
        )
        db.add_document(text, {"type": "room", **entry})

    # Sections
    sections_path = os.path.join(DATA_DIR, "sections.json")
    with open(sections_path, encoding="utf-8") as f:
        sections = json.load(f)
    for entry in sections:
        teacher  = entry["classTeacher"]["name"]
        mentors  = ", ".join(entry.get("mentors", []))
        text = (
            f"Section {entry['section']} is located in {entry['block']}, "
            f"{entry['floor']}, Room {entry['room']}. "
            f"Class teacher: {teacher}. Mentors: {mentors}."
        )
        db.add_document(text, {"type": "section", **entry})

    # IoT 2B Weekly Schedule
    schedule_path = os.path.join(DATA_DIR, "iot_2b_schedule.json")
    if os.path.exists(schedule_path):
        with open(schedule_path, encoding="utf-8") as f:
            schedule_data = json.load(f)
        for entry in schedule_data.get("schedule", []):
            if entry.get("subject") in ("BREAK", "EAA") or not entry.get("subject"):
                continue
            faculty_str = ", ".join(entry.get("faculty", [])) or "TBA"
            room_str    = entry.get("room") or "TBA"
            text = (
                f"IoT 2B schedule: On {entry['day']} period {entry['period']} "
                f"({entry['time']}), subject is {entry['subject']}. "
                f"Faculty: {faculty_str}. Room: {room_str}."
            )
            db.add_document(text, {
                "type":    "schedule",
                "class":   "IoT 2B",
                "day":     entry["day"],
                "period":  entry["period"],
                "time":    entry["time"],
                "subject": entry["subject"],
                "faculty": entry.get("faculty", []),
                "room":    room_str,
            })

    db.build_index()
    print(f"[READY] Knowledge base: {len(db.documents)} documents indexed.")
    return db


# Build the knowledge base once at startup
print("[*] Building knowledge base...")
_db = build_knowledge_base()


# ==============================================================================
# Groq API call
# ==============================================================================
SYSTEM_PROMPT = (
    "You are 'Campus Connect' — the official AI assistant for UEM Kolkata campus ONLY.\n\n"
    "## STRICT RULES:\n"
    "1. ONLY use the [CAMPUS DATA] section below. NEVER use training knowledge.\n"
    "2. If the answer is NOT in [CAMPUS DATA], reply EXACTLY:\n"
    "   \"😔 I don't have that information. Please check the notice board.\"\n"
    "3. NEVER answer questions about celebrities, sports, maths, coding, history, or anything outside UEM campus.\n"
    "4. Use **bold** for room numbers, names, and key values.\n"
    "5. Keep replies concise (3–5 lines max).\n\n"
    "[CAMPUS DATA]\n{context}"
)


def call_groq(query: str, context: str, history: list) -> str | None:
    if not GROQ_API_KEY:
        return None
    url = "https://api.groq.com/openai/v1/chat/completions"
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.format(context=context)}
    ]
    # Inject recent conversation history
    for msg in (history or [])[-4:]:
        if isinstance(msg, dict) and "role" in msg and "content" in msg:
            messages.append({"role": msg["role"], "content": str(msg["content"])[:300]})
    messages.append({"role": "user", "content": query})

    try:
        resp = http_client.post(
            url,
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type":  "application/json"
            },
            json={
                "model":       "llama-3.3-70b-versatile",
                "messages":    messages,
                "temperature": 0,
                "max_tokens":  400
            },
            timeout=15
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"[Groq Error] {e}")
        return None


# ==============================================================================
# Flask routes
# ==============================================================================
@app.route("/health", methods=["GET"])
def health():
    """Liveness check for Render."""
    return jsonify({"status": "ok", "documents": len(_db.documents)}), 200


@app.route("/chat", methods=["POST"])
def chat():
    """
    Accepts:  { "message": "...", "history": [...] }
    Returns:  { "reply": "..." }
    """
    body    = request.get_json(silent=True) or {}
    message = (body.get("message") or "").strip()
    history = body.get("history", [])

    if not message:
        return jsonify({"error": "message is required"}), 400

    # Build context from top search results
    results = _db.search(message, top_k=8)
    if not results:
        return jsonify({"reply": "😔 I don't have that information. Please check the notice board."})

    context_lines = []
    for r in results:
        context_lines.append(r["text"])
    context = "\n".join(context_lines)[:5000]

    # Call Groq
    ai_reply = call_groq(message, context, history)
    if ai_reply:
        return jsonify({"reply": ai_reply})

    # Fallback: return top raw result
    return jsonify({"reply": f"📋 {results[0]['text']}"})


# ==============================================================================
# Entry point
# ==============================================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
