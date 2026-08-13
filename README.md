# 🏫 Campus Connect — UEM Kolkata

AI-powered campus navigation chatbot for UEM Kolkata.

## Architecture

```
┌──────────────────────┐         ┌──────────────────────┐
│    GitHub Pages      │  HTTPS  │       Render         │
│      Frontend        │────────▶│    Python Backend    │
│                      │  /chat  │                      │
│  frontend/           │         │  backend/            │
│  ├── index.html      │         │  ├── app.py           │
│  ├── style.css       │         │  ├── requirements.txt │
│  └── script.js       │         │  └── data/           │
└──────────────────────┘         └──────────┬───────────┘
                                            │
                                            ▼
                                      Groq API (Llama 3)
```

## Project Structure

```
campusbot/
├── frontend/              ← GitHub Pages (static site)
│   ├── index.html
│   ├── style.css
│   └── script.js
│
├── backend/               ← Render Web Service (Python/Flask)
│   ├── app.py
│   ├── requirements.txt
│   ├── .env.example
│   ├── data/
│   │   ├── faculty.json
│   │   ├── rooms.json
│   │   └── sections.json
│   └── README.md
│
└── .github/
    └── workflows/
        └── deploy.yml     ← Auto-deploys frontend/ to GitHub Pages
```

## Deployments

| Component | Platform | URL |
|-----------|----------|-----|
| Frontend  | GitHub Pages | https://abhipal2219-tech.github.io/campusbot |
| Backend   | Render | *(add your Render URL here after deploying)* |

## Quick Start

### Frontend (GitHub Pages)
Push to `main` branch — GitHub Actions automatically deploys `frontend/` to GitHub Pages.

### Backend (Render)
See [`backend/README.md`](backend/README.md) for full setup instructions.

**Required environment variable on Render:**
```
GROQ_API_KEY=your_groq_api_key_here
```

## Connecting Frontend to Backend

After deploying to Render, update `BACKEND_URL` in `frontend/script.js`:
```js
const BACKEND_URL = 'https://your-service.onrender.com';
```

Then push — GitHub Actions will redeploy the frontend automatically.
