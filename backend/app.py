"""
app.py
------
Campus Connect — Render Web Service (Flask + Gunicorn)

Routes:
  GET  /health  →  liveness check + server status
  POST /chat    →  { "message": "...", "history": [...] }
                ←  { "reply": "..." }
"""

import os
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone, timedelta

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
import requests as http_client

# ── Environment ────────────────────────────────────────────────────────────────
load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
PORT         = int(os.getenv("PORT", 10000))

# ── IST Timezone (UTC+5:30) ───────────────────────────────────────────────────
IST = timezone(timedelta(hours=5, minutes=30))

def get_ist_now() -> datetime:
    return datetime.now(IST)

def get_today_ist() -> str:
    return get_ist_now().strftime("%A")

def get_time_ist() -> str:
    return get_ist_now().strftime("%I:%M %p")

# ── App setup ──────────────────────────────────────────────────────────────────
app = Flask(__name__)

CORS(app, resources={r"/*": {"origins": [
    "https://abhipal2219-tech.github.io",
    "http://localhost:*",
    "http://127.0.0.1:*"
]}})

# ── Data paths ─────────────────────────────────────────────────────────────────
BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
DATA_DIR     = os.path.join(BASE_DIR, "data")
FRONTEND_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "frontend"))


# ==============================================================================
# TF-IDF Vector Store
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
# Knowledge Base Initialization
# ==============================================================================
_schedule_data = []


def build_knowledge_base() -> VectorStore:
    global _schedule_data
    db = VectorStore()

    # 1. Faculty
    faculty_path = os.path.join(DATA_DIR, "faculty.json")
    if os.path.exists(faculty_path):
        with open(faculty_path, encoding="utf-8-sig") as f:
            for entry in json.load(f):
                db.add_document(
                    f"{entry['name']} ({entry.get('code','')}) is a faculty member "
                    f"in {entry['dept']} department. Cabin: {entry.get('room') or 'Not recorded'}.",
                    {"type": "faculty", **entry}
                )

    # 2. Rooms
    rooms_path = os.path.join(DATA_DIR, "rooms.json")
    if os.path.exists(rooms_path):
        with open(rooms_path, encoding="utf-8-sig") as f:
            for entry in json.load(f):
                db.add_document(
                    f"{entry['use']} is located in {entry['bld']}, "
                    f"{entry['floor']}, Room {entry['room']}.",
                    {"type": "room", **entry}
                )

    # 3. Sections
    sections_path = os.path.join(DATA_DIR, "sections.json")
    if os.path.exists(sections_path):
        with open(sections_path, encoding="utf-8-sig") as f:
            for entry in json.load(f):
                db.add_document(
                    f"Section {entry['section']} is in {entry['block']}, "
                    f"{entry['floor']}, Room {entry['room']}. "
                    f"Class teacher: {entry['classTeacher']['name']}. "
                    f"Mentors: {', '.join(entry.get('mentors', []))}.",
                    {"type": "section", **entry}
                )

    # 4. Weekly Schedules (Auto-loads any *_schedule*.json found in DATA_DIR)
    import glob
    sched_files = glob.glob(os.path.join(DATA_DIR, "*schedule*.json"))
    for s_file in sched_files:
        try:
            with open(s_file, encoding="utf-8-sig") as f:
                raw = json.load(f)
            class_name = raw.get("class") or raw.get("section") or "IoT 2B"
            entries = [
                e for e in raw.get("schedule", [])
                if e.get("subject") not in ("BREAK", "EAA") and e.get("subject")
            ]
            for e in entries:
                e_class = e.get("class") or class_name
                e["class"] = e_class
                _schedule_data.append(e)
                fac  = ", ".join(e.get("faculty", [])) or "TBA"
                room = e.get("room") or "TBA"
                db.add_document(
                    f"{e_class} schedule: On {e['day']} period {e['period']} "
                    f"({e['time']}), subject is {e['subject']}. "
                    f"Faculty: {fac}. Room: {room}.",
                    {"type": "schedule", "class": e_class,
                     "day": e["day"], "period": e["period"],
                     "time": e["time"], "subject": e["subject"],
                     "faculty": e.get("faculty", []), "room": room}
                )
        except Exception as err:
            print(f"[Warn] Could not load schedule {s_file}: {err}")

    db.build_index()
    print(f"[READY] Knowledge base: {len(db.documents)} documents indexed.")
    return db


print("[*] Building knowledge base...")
_db = build_knowledge_base()


# ==============================================================================
# Real-Time Schedule Handler (IST Date-Aware)
# ==============================================================================
_ORDINAL_MAP = {
    "first": 1, "second": 2, "third": 3, "fourth": 4,
    "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
    "1st": 1, "2nd": 2, "3rd": 3, "4th": 4,
    "5th": 5, "6th": 6, "7th": 7, "8th": 8
}
_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def handle_schedule_query(text: str) -> str | None:
    if not _schedule_data:
        return None

    q = text.lower()

    # 1. Detect period number (handles "3 rd period", "3rd period", "3 period", "period 3", "p3", "3 rd class", "third period", etc.)
    period_num = None
    m = re.search(r'\b(?:period|class|slot|p)\s*(\d)\b|\b(\d)\s*(?:st|nd|rd|th)?\s*(?:period|class|slot)\b|\b(\d)\s*(?:st|nd|rd|th)\b', q)
    if m:
        period_num = int(m.group(1) or m.group(2) or m.group(3))
    if not period_num:
        for word, num in _ORDINAL_MAP.items():
            if f"{word} period" in q or f"period {word}" in q or f"{word} class" in q:
                period_num = num
                break

    # 2. Detect explicit day name
    matched_day = None
    for d in _DAYS:
        if d in q:
            matched_day = d.capitalize()
            break

    # 3. Detect relative date terms (today, tomorrow, yesterday)
    now_ist = get_ist_now()
    today_weekday = now_ist.strftime("%A")
    current_time_str = now_ist.strftime("%I:%M %p")

    wants_all_days = bool(re.search(r'\ball days\b|\bevery day\b|\bwhole week\b|\bweekly\b|\ball day\b', q))
    wants_today = bool(re.search(r'\btoday\b|\bnow\b|\bcurrent\b|\bthis period\b', q))
    wants_tomorrow = bool(re.search(r'\btomorrow\b|\bnext day\b', q))
    wants_schedule_general = bool(re.search(r'\bschedule\b|\btimetable\b|\bclasses\b|\broutine\b|\bmy class\b', q))

    # Subject keywords & aliases
    SUBJECT_ALIASES = {
        'dsa': ['data structure', 'dsa'],
        'data structure': ['data structure', 'dsa'],
        'analog': ['analog electronic circuits', 'analog'],
        'digital': ['digital electronic circuits', 'digital'],
        'math': ['mathematics', 'math'],
        'mathematics': ['mathematics', 'math'],
        'management': ['principles of management', 'management', 'pom'],
        'placement': ['pre-placement training', 'placement', 'ppt'],
        'pre-placement': ['pre-placement training', 'placement', 'ppt'],
        'ppt': ['pre-placement training', 'placement', 'ppt'],
        'workshop': ['it workshop', 'workshop'],
        'it workshop': ['it workshop', 'workshop'],
        'esep': ['esep'],
        'skill': ['technical skill development', 'skill development', 'tsd'],
        'technical skill': ['technical skill development', 'skill development', 'tsd'],
        'tsd': ['technical skill development', 'skill development', 'tsd']
    }

    def _subject_matches(entry_subj: str, key: str) -> bool:
        s_low = entry_subj.lower()
        aliases = SUBJECT_ALIASES.get(key, [key])
        return any(a in s_low for a in aliases)

    matched_subject = None
    for kw in SUBJECT_ALIASES:
        if re.search(rf'\b{re.escape(kw)}\b', q):
            matched_subject = kw
            break

    # Guard: check if this is genuinely a schedule query
    is_schedule_query = (
        period_num is not None or
        matched_day is not None or
        wants_today or
        wants_tomorrow or
        (wants_schedule_general and ("iot" in q or "2b" in q or "class" in q or "period" in q or "today" in q or "tomorrow" in q)) or
        (matched_subject is not None and ("class" in q or "schedule" in q or "when" in q or "room" in q or "faculty" in q or "time" in q or "lab" in q or "timing" in q))
    )
    if not is_schedule_query:
        return None

    # Case 1: Subject query across all days (when NO day and not "today" requested)
    if matched_subject and not matched_day and not wants_today and not wants_tomorrow:
        matches = [e for e in _schedule_data if _subject_matches(e["subject"], matched_subject)]
        if matches:
            lines = []
            for e in matches:
                fac = ", ".join(e.get("faculty", [])) or "TBA"
                lines.append(f"**{e['day']}** P{e['period']} ({e['time']}): **{e['subject']}**\n   📍 Room: **{e['room'] or 'TBA'}** | 👨‍🏫 Faculty: **{fac}**")
            return f"📚 **{matches[0]['subject']} Schedule (IoT 2B)**\n\n" + "\n\n".join(lines)

    # Case 2: Multi-day period query (e.g. "3rd period all days")
    if period_num is not None and wants_all_days:
        matches = [e for e in _schedule_data if int(e["period"]) == period_num]
        if not matches:
            return f"😔 No Period {period_num} classes found."
        lines = []
        for e in matches:
            fac = ", ".join(e.get("faculty", [])) or "TBA"
            lines.append(f"**{e['day']}** ({e['time']}): **{e['subject']}** (Room: {e['room']}, Faculty: {fac})")
        return f"🕐 **Period {period_num} Across the Week (IoT 2B)**\n\n" + "\n\n".join(lines)

    # Resolve target day for single-day queries
    target_day = matched_day
    is_today = False

    if not target_day:
        if wants_tomorrow:
            tomorrow_dt = now_ist + timedelta(days=1)
            target_day = tomorrow_dt.strftime("%A")
        elif not wants_all_days:
            # Default to TODAY (IST)
            target_day = today_weekday
            is_today = True

    # Case 3: Weekend Handling
    if target_day in ("Saturday", "Sunday") and not wants_all_days:
        day_label = f"Today ({target_day})" if is_today else target_day
        return (
            f"📅 **{day_label}** — No classes scheduled for IoT 2B.\n"
            f"Enjoy your weekend! 🎉\n\n"
            f"💡 *Tip: Ask `Monday schedule` to see upcoming classes.*"
        )

    # Case 4: Single day schedule queries
    if target_day and not wants_all_days:
        day_entries = [e for e in _schedule_data if e["day"] == target_day]
        if not day_entries:
            return f"😔 No schedule records found for IoT 2B on {target_day}."

        # Specific period
        if period_num is not None:
            match = [e for e in day_entries if int(e["period"]) == period_num]
            if not match:
                return f"😔 No Period {period_num} scheduled for IoT 2B on {target_day}."
            e = match[0]
            fac = ", ".join(e.get("faculty", [])) or "TBA"
            day_text = f"Today ({target_day})" if is_today else target_day
            return (
                f"🕐 **Period {e['period']}** — {day_text}\n\n"
                f"📚 **{e['subject']}**\n"
                f"⏰ **Time:** {e['time']}\n"
                f"📍 **Room:** {e['room'] or 'TBA'}\n"
                f"👨‍🏫 **Faculty:** {fac}"
            )

        # Specific subject on this day
        if matched_subject:
            sub_matches = [e for e in day_entries if _subject_matches(e["subject"], matched_subject)]
            if sub_matches:
                cards = []
                for e in sub_matches:
                    fac = ", ".join(e.get("faculty", [])) or "TBA"
                    cards.append(
                        f"📚 **{e['subject']}**\n"
                        f"⏰ Period {e['period']} ({e['time']})\n"
                        f"📍 Room: **{e['room'] or 'TBA'}** | 👨‍🏫 Faculty: **{fac}**"
                    )
                day_text = f"Today ({target_day})" if is_today else target_day
                return f"📅 **{day_text}** — IoT 2B\n\n" + "\n\n".join(cards)

        # Full day schedule
        lines = []
        for e in day_entries:
            fac = ", ".join(e.get("faculty", [])) or "TBA"
            lines.append(
                f"**P{e['period']}** ({e['time']}) : **{e['subject']}**\n"
                f"   📍 Room {e['room'] or 'TBA'}  |  👨‍🏫 {fac}"
            )
        header = f"📅 **IoT 2B Schedule — {'Today (' + target_day + ')' if is_today else target_day}**"
        if is_today:
            header += f"\n*(Current IST: {current_time_str})*"
        return header + "\n\n" + "\n\n".join(lines)

    # Case 5: Full weekly timetable
    if wants_schedule_general or wants_all_days:
        by_day = {}
        for e in _schedule_data:
            by_day.setdefault(e["day"], []).append(e)
        day_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
        blocks = []
        for d in day_order:
            if d in by_day:
                items = [f"P{e['period']} ({e['time']}): {e['subject']} (Room: {e['room']})" for e in by_day[d]]
                blocks.append(f"**{d}**\n • " + "\n • ".join(items))
        return "📅 **IoT 2B Weekly Timetable**\n\n" + "\n\n".join(blocks)

    return None


# ==============================================================================
# Groq LLM Generation
# ==============================================================================
SYSTEM_PROMPT = (
    "You are 'Campus Connect' — the official AI assistant for UEM Kolkata campus ONLY.\n\n"
    "## STRICT RULES:\n"
    "1. ONLY use the [CAMPUS DATA] section below. NEVER use training knowledge.\n"
    "2. If the answer is NOT in [CAMPUS DATA], reply EXACTLY:\n"
    '   "😔 I don\'t have that information. Please check the notice board."\n'
    "3. NEVER answer questions about celebrities, sports, maths, coding, history, or anything outside UEM campus.\n"
    "4. Use **bold** for room numbers, names, and key values.\n"
    "5. Keep replies concise (3–5 lines max).\n\n"
    "[CAMPUS DATA]\n{context}"
)


# Models to try in order — update this list if Groq deprecates a model
GROQ_MODELS = [
    "llama-3.3-70b-versatile",     # primary (may be deprecated)
    "openai/gpt-oss-120b",          # Groq's new flagship (Aug 2026)
    "openai/gpt-oss-20b",           # Groq's fast model (Aug 2026)
    "llama3-70b-8192",              # older fallback
]


def call_groq(query: str, context: str, history: list) -> str | None:
    if not GROQ_API_KEY:
        return None
    url = "https://api.groq.com/openai/v1/chat/completions"
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.format(context=context)}
    ]
    for msg in (history or [])[-4:]:
        if isinstance(msg, dict) and "role" in msg and "content" in msg:
            messages.append({"role": msg["role"], "content": str(msg["content"])[:300]})
    messages.append({"role": "user", "content": query})

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type":  "application/json"
    }

    for model in GROQ_MODELS:
        try:
            resp = http_client.post(
                url,
                headers=headers,
                json={
                    "model":       model,
                    "messages":    messages,
                    "temperature": 0,
                    "max_tokens":  400
                },
                timeout=15
            )
            if resp.status_code == 404:
                print(f"[Groq] Model '{model}' not found, trying next...")
                continue
            resp.raise_for_status()
            result = resp.json()["choices"][0]["message"]["content"]
            if model != GROQ_MODELS[0]:
                print(f"[Groq] Used fallback model: {model}")
            return result
        except Exception as e:
            print(f"[Groq Error] model={model}: {e}")
            continue

    print("[Groq] All models failed.")
    return None


# ==============================================================================
# Flask Routes
# ==============================================================================
@app.route("/", methods=["GET"])
def index():
    index_file = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_file):
        return send_from_directory(FRONTEND_DIR, "index.html")
    return jsonify({
        "service":   "Campus Connect Backend API",
        "status":    "running",
        "documents": len(_db.documents),
        "ist_time":  get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST"),
        "today":     get_today_ist()
    }), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status":    "ok",
        "documents": len(_db.documents),
        "ist_time":  get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST"),
        "today":     get_today_ist()
    }), 200


@app.route("/<path:path>", methods=["GET"])
def serve_static(path):
    target = os.path.join(FRONTEND_DIR, path)
    if os.path.exists(target):
        return send_from_directory(FRONTEND_DIR, path)
    return jsonify({"error": f"File not found: {path}"}), 404


@app.route("/chat", methods=["POST"])
def chat():
    try:
        body    = request.get_json(silent=True) or {}
        message = (body.get("message") or "").strip()
        history = body.get("history", [])

        if not message:
            return jsonify({"error": "message is required"}), 400

        # 1. Real-time smart schedule query (zero LLM latency, IST date-aware)
        sched_reply = handle_schedule_query(message)
        if sched_reply:
            return jsonify({"reply": sched_reply})

        # 2. TF-IDF Context Retrieval
        results = _db.search(message, top_k=8)

        # Filter by relevance threshold — discard low-confidence results.
        # Calibrated thresholds from observed scores:
        #   - irrelevant (shahrukh khan, maths count): 0.14 - 0.22
        #   - edge valid (Section G): 0.24
        #   - strong valid (Prof name, room): 0.30+
        CONTEXT_THRESHOLD  = 0.23   # min score to accept as relevant at all
        FALLBACK_THRESHOLD = 0.23   # same — if it's relevant enough for context, show it directly when Groq is down

        relevant = [r for r in results if r["score"] >= CONTEXT_THRESHOLD]

        if not relevant:
            return jsonify({"reply": "😔 I don't have that information. Please check the notice board or ask about faculty, rooms, or sections."})

        context = "\n".join(r["text"] for r in relevant)[:5000]

        # 3. Groq LLM
        ai_reply = call_groq(message, context, history)
        if ai_reply:
            return jsonify({"reply": ai_reply})

        # 4. Fallback: only show raw result if score is high enough to be reliable
        top = relevant[0]
        if top["score"] >= FALLBACK_THRESHOLD:
            return jsonify({"reply": f"📋 {top['text']}"})

        # Score is too low to be reliable — refuse rather than guess
        return jsonify({"reply": "😔 I don't have that information. Please check the notice board."})

    except Exception as e:
        print(f"[Chat Endpoint Error] {e}")
        return jsonify({"reply": "😔 An internal error occurred. Please try again."}), 200


# ==============================================================================
# Entry Point
# ==============================================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
