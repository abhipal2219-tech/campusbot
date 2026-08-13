# 🐍 Campus Connect — Python Backend

Flask-based chatbot backend for the UEM Kolkata Campus Connect bot.
Deployed on **Render** as a Web Service.

## Architecture

```
Frontend (GitHub Pages) → POST /chat → Backend (Render) → Groq API
```

## Local Setup

```bash
# 1. Create virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Mac/Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment variables
copy .env.example .env       # Windows
# cp .env.example .env       # Mac/Linux
# Then edit .env and add your GROQ_API_KEY

# 4. Run the dev server
python app.py
# Server starts at http://localhost:10000
```

## API Endpoints

### `GET /health`
Liveness check — confirms the backend is running.

**Response:**
```json
{ "status": "ok", "documents": 150 }
```

### `POST /chat`
Send a message and receive an AI-powered campus response.

**Request body:**
```json
{
  "message": "Where is Section E?",
  "history": []
}
```

**Response:**
```json
{
  "reply": "Section E is in Block 2, 2nd Floor, Room B2 LG 2.3..."
}
```

## Render Deployment

1. Create a new **Web Service** on [Render](https://render.com)
2. Connect your GitHub repo
3. Set the **Root Directory** to `backend`
4. Set the **Start Command** to:
   ```
   gunicorn app:app --bind 0.0.0.0:$PORT
   ```
5. Add environment variable:
   - `GROQ_API_KEY` → your Groq API key from [console.groq.com](https://console.groq.com)
6. Copy your Render URL (e.g. `https://campusbot-xyz.onrender.com`)
7. Update `BACKEND_URL` in `frontend/script.js` with this URL

## Data Files

Campus data is stored in `backend/data/`:
- `faculty.json` — faculty names, departments, cabin numbers
- `rooms.json` — room allocations across all blocks
- `sections.json` — section locations, class teachers, and mentors
