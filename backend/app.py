"""
app.py
------
Campus Connect — Render Web Service (Flask + Gunicorn)

Routes:
  GET  /health  ->  liveness check
  POST /chat    ->  { "message": "...", "history": [...] }
                <-  { "reply": "..." }
"""

import os
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone, timedelta

from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import requests as http_client

# -- Environment ---------------------------------------------------------------
load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
PORT         = int(os.getenv("PORT", 10000))

# -- IST timezone (UTC+5:30) ---------------------------------------------------
IST = timezone(timedelta(hours=5, minutes=30))

def get_ist_now():
    return datetime.now(IST)

def get_today_ist():
    return get_ist_now().strftime("%A")   # e.g. "Monday"

def get_time_ist():
    return get_ist_now().strftime("%I:%M %p")  # e.g. "10:30 AM"

# -- App setup -----------------------------------------------------------------
app = Flask(__name__)

CORS(app, resources={r"/*": {"origins": [
    "https://abhipal2219-tech.github.io",
    "http://localhost:*",
    "http://127.0.0.1:*"
]}})

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")


# ==============================================================================
# TF-IDF Vector Store
# ==============================================================================
def _tokenize(text):
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

    def add_document(self, text, metadata=None):
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

    def _tfidf(self, tf):
        return {t: v * self.idf.get(t, 0) for t, v in tf.items()}

    @staticmethod
    def _cosine(a, b):
        common = set(a) & set(b)
        if not common:
            return 0.0
        dot   = sum(a[k] * b[k] for k in common)
        normA = math.sqrt(sum(v ** 2 for v in a.values()))
        normB = math.sqrt(sum(v ** 2 for v in b.values()))
        return dot / (normA * normB) if normA and normB else 0.0

    def search(self, query, top_k=5):
        if self._dirty:
            self.build_index()
        tokens = _tokenize(query)
        counts = Counter(tokens)
        total  = len(tokens) or 1
        q_tf   = {t: c / total for t, c in counts.items()}
        q_vec  = self._tfidf(q_tf)
        scored = [
            (self._cosine(q_vec, self._tfidf(tf)), i)
            for i, tf in enumerate(self.tf_vectors)
        ]
        scored.sort(reverse=True)
        return [
            {"text": self.documents[i], "score": round(s, 4), "metadata": self.metadata[i]}
            for s, i in scored[:top_k] if s > 0
        ]


# ==============================================================================
# Knowledge Base
# ==============================================================================
_schedule_data = []   # raw list kept for real-time queries


def build_knowledge_base():
    global _schedule_data
    db = VectorStore()

    # Faculty
    with open(os.path.join(DATA_DIR, "faculty.json"), encoding="utf-8") as f:
        for entry in json.load(f):
            db.add_document(
                f"{entry['name']} ({entry.get('code','')}) is a faculty member "
                f"in {entry['dept']} department. Cabin: {entry.get('room') or 'Not recorded'}.",
                {"type": "faculty", **entry}
            )

    # Rooms
    with open(os.path.join(DATA_DIR, "rooms.json"), encoding="utf-8") as f:
        for entry in json.load(f):
            db.add_document(
                f"{entry['use']} is located in {entry['bld']}, "
                f"{entry['floor']}, Room {entry['room']}.",
                {"type": "room", **entry}
            )

    # Sections
    with open(os.path.join(DATA_DIR, "sections.json"), encoding="utf-8") as f:
        for entry in json.load(f):
            db.add_document(
                f"Section {entry['section']} is in {entry['block']}, "
                f"{entry['floor']}, Room {entry['room']}. "
                f"Class teacher: {entry['classTeacher']['name']}. "
                f"Mentors: {', '.join(entry.get('mentors', []))}.",
                {"type": "section", **entry}
            )

    # IoT 2B Schedule
    sched_path = os.path.join(DATA_DIR, "iot_2b_schedule.json")
    if os.path.exists(sched_path):
        with open(sched_path, encoding="utf-8") as f:
            raw = json.load(f)
        _schedule_data = [
            e for e in raw.get("schedule", [])
            if e.get("subject") not in ("BREAK", "EAA") and e.get("subject")
        ]
        for e in _schedule_data:
            fac  = ", ".join(e.get("faculty", [])) or "TBA"
            room = e.get("room") or "TBA"
            db.add_document(
                f"IoT 2B schedule: On {e['day']} period {e['period']} "
                f"({e['time']}), subject is {e['subject']}. "
                f"Faculty: {fac}. Room: {room}.",
                {"type": "schedule", "class": "IoT 2B",
                 "day": e["day"], "period": e["period"],
                 "time": e["time"], "subject": e["subject"],
                 "faculty": e.get("faculty", []), "room": room}
            )

    db.build_index()
    print(f"[READY] Knowledge base: {len(db.documents)} documents indexed.")
    return db


print("[*] Building knowledge base...")
_db = build_knowledge_base()


# ==============================================================================
# Real-time Schedule Handler (IST date-aware)
# ==============================================================================
_ORDINAL_MAP = {
    "first": 1, "second": 2, "third": 3, "fourth": 4,
    "fifth": 5, "sixth":  6, "seventh": 7, "eighth": 8
}
_DAYS = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]


def _parse_schedule_intent(text):
    q = text.lower()

    # Detect period number: "period 3", "p3", "3rd period", "third period"
    period_num = None
    m = re.search(r'\bperiod\s*(\d)\b|\bp(\d)\b|(\d)(st|nd|rd|th)\s*period', q)
    if m:
        period_num = int(m.group(1) or m.group(2) or m.group(3))
    if not period_num:
        for word, num in _ORDINAL_MAP.items():
            if f"{word} period" in q or f"period {word}" in q:
                period_num = num
                break

    # Detect explicit day name
    day_name = None
    for d in _DAYS:
        if d in q:
            day_name = d.capitalize()
            break

    wants_today = bool(re.search(
        r'\btoday\b|\bnow\b|\bcurrent\b|\bgoing on\b|\bthis period\b|\bmy class\b', q))

    wants_full = bool(re.search(
        r'\bschedule\b|\btimetable\b|\ball class\b|\bweekly\b|\broutine\b', q))

    return period_num, day_name, wants_today, wants_full


def handle_schedule_query(text):
    """
    Returns formatted reply if schedule-related, else None.
    Auto-uses IST real-time date when no day is specified.
    """
    if not _schedule_data:
        return None

    period_num, day_name, wants_today, wants_full = _parse_schedule_intent(text)

    is_schedule_query = (
        period_num is not None
        or wants_today
        or wants_full
        or (day_name and re.search(
            r'\bclass\b|\bperiod\b|\bschedule\b|\bsubject\b', text.lower()))
    )
    if not is_schedule_query:
        return None

    # Resolve day — use IST today if not mentioned
    now_ist  = get_ist_now()
    today    = now_ist.strftime("%A")    # e.g. "Tuesday"
    time_str = now_ist.strftime("%I:%M %p")

    target_day = day_name if day_name else today
    using_today = (target_day == today)

    # Weekend
    if target_day in ("Saturday", "Sunday"):
        return (
            f"📅 Today is **{target_day}** — no classes for IoT 2B.\n"
            f"Enjoy your weekend! 🎉"
        )

    entries = [e for e in _schedule_data if e["day"] == target_day]
    if not entries:
        return f"😔 No classes found for IoT 2B on {target_day}."

    day_label = f"Today — {target_day}" if using_today else target_day
    time_note = f"  _(now: {time_str} IST)_" if using_today else ""

    # Specific period
    if period_num is not None:
        match = [e for e in entries if int(e["period"]) == period_num]
        if not match:
            return f"😔 No Period {period_num} on {target_day} for IoT 2B."
        e   = match[0]
        fac = ", ".join(e.get("faculty", [])) or "TBA"
        return (
            f"🕐 **Period {e['period']}** — {day_label}{time_note}\n\n"
            f"📚 **{e['subject']}**\n"
            f"🕐 {e['time']}\n"
            f"📍 Room: **{e['room'] or 'TBA'}**\n"
            f"👨‍🏫 Faculty: **{fac}**"
        )

    # Full day schedule
    lines = []
    for e in entries:
        fac = ", ".join(e.get("faculty", [])) or "TBA"
        lines.append(
            f"**P{e['period']}** {e['time']} — {e['subject']}\n"
            f"   📍 {e['room'] or 'TBA'}  |  👨‍🏫 {fac}"
        )
    return (
        f"📅 **IoT 2B — {day_label}**{time_note}\n\n"
        + "\n\n".join(lines)
    )


# ==============================================================================
# Groq API call
# ==============================================================================
SYSTEM_PROMPT = (
    "You are 'Campus Connect' — the official AI assistant for UEM Kolkata campus ONLY.\n\n"
    "## STRICT RULES:\n"
    "1. ONLY use the [CAMPUS DATA] section below. NEVER use training knowledge.\n"
    "2. If the answer is NOT in [CAMPUS DATA], reply EXACTLY:\n"
    '   "I don\'t have that information. Please check the notice board."\n'
    "3. NEVER answer questions about celebrities, sports, maths, coding, history, "
    "or anything outside UEM campus.\n"
    "4. Use **bold** for room numbers, names, and key values.\n"
    "5. Keep replies concise (3-5 lines max).\n\n"
    "[CAMPUS DATA]\n{context}"
)


def call_groq(query, context, history):
    if not GROQ_API_KEY:
        return None
    messages = [{"role": "system", "content": SYSTEM_PROMPT.format(context=context)}]
    for msg in (history or [])[-4:]:
        if isinstance(msg, dict) and "role" in msg and "content" in msg:
            messages.append({"role": msg["role"], "content": str(msg["content"])[:300]})
    messages.append({"role": "user", "content": query})
    try:
        resp = http_client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": "llama-3.3-70b-versatile", "messages": messages,
                  "temperature": 0, "max_tokens": 400},
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
    return jsonify({
        "status":    "ok",
        "documents": len(_db.documents),
        "ist_time":  get_ist_now().strftime("%Y-%m-%d %H:%M:%S"),
        "today":     get_today_ist()
    }), 200


@app.route("/chat", methods=["POST"])
def chat():
    body    = request.get_json(silent=True) or {}
    message = (body.get("message") or "").strip()
    history = body.get("history", [])

    if not message:
        return jsonify({"error": "message is required"}), 400

    # 1. Real-time schedule handler (IST-aware, no Groq needed)
    sched_reply = handle_schedule_query(message)
    if sched_reply:
        return jsonify({"reply": sched_reply})

    # 2. TF-IDF context search
    results = _db.search(message, top_k=8)
    if not results:
        return jsonify({"reply": "I don't have that information. Please check the notice board."})

    context = "\n".join(r["text"] for r in results)[:5000]

    # 3. Groq AI
    ai_reply = call_groq(message, context, history)
    if ai_reply:
        return jsonify({"reply": ai_reply})

    # 4. Fallback
    return jsonify({"reply": f"📋 {results[0]['text']}"})


# ==============================================================================
# Entry point
# ==============================================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
