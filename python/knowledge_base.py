"""
knowledge_base.py
-----------------
Loads campus data from the data/ JSON files and populates the VectorStore.
"""

import json
import os
from vector_store import VectorStore

# ── File paths ──────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(os.path.dirname(BASE_DIR), "data")

FACULTY_FILE  = os.path.join(DATA_DIR, "faculty.json")
ROOMS_FILE    = os.path.join(DATA_DIR, "rooms.json")
SECTIONS_FILE = os.path.join(DATA_DIR, "sections.json")

def load_data(db: VectorStore):
    """Load all JSON data files into the vector store."""
    
    # 1. Faculty
    with open(FACULTY_FILE, encoding="utf-8") as f:
        faculty = json.load(f)
        for entry in faculty:
            text = f"{entry['name']} ({entry['code']}) is a faculty member in {entry['dept']} department. Cabin: {entry['room'] or 'Not recorded'}."
            db.add_document(text, metadata={"type": "faculty", **entry})

    # 2. Rooms
    with open(ROOMS_FILE, encoding="utf-8") as f:
        rooms = json.load(f)
        for entry in rooms:
            text = f"{entry['use']} is located in {entry['bld']}, {entry['floor']}, Room {entry['room']}."
            db.add_document(text, metadata={"type": "room", **entry})

    # 3. Sections
    with open(SECTIONS_FILE, encoding="utf-8") as f:
        sections = json.load(f)
        for entry in sections:
            teacher = entry['classTeacher']['name']
            mentors = ", ".join(entry.get('mentors', []))
            text = f"Section {entry['section']} is located in {entry['block']}, {entry['floor']}, Room {entry['room']}. Class teacher: {teacher}. Mentors: {mentors}."
            db.add_document(text, metadata={"type": "section", **entry})

def build_knowledge_base() -> VectorStore:
    print("[*] Building knowledge base...")
    db = VectorStore()
    load_data(db)
    db.build_index()
    print(f"[READY] Knowledge base ready: {db}")
    return db
