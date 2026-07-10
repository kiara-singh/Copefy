# Copefy

Copefy is an AI mental health and wellness companion. It leverages multimodal AI
and a Retrieval-Augmented Generation (RAG) architecture to provide supportive,
context-aware conversations.

> This repo is an early scaffold. The three frontend pages currently render only
> their names, and the backend exposes basic health endpoints. Auth, the RAG
> pipeline, and multimodal features come later.

## Tech stack

- **Frontend:** React + TypeScript (Vite), Tailwind CSS, React Router
- **Backend:** FastAPI (Python)
- **Database / Vector store:** Supabase (Postgres) + pgvector

## Repo layout

```
Copefy/
  frontend/   # React + TypeScript app (Vite + Tailwind)
  backend/    # FastAPI app
  README.md
  .gitignore
```

## Prerequisites

Install these before you start:

- [Node.js](https://nodejs.org/) LTS (v18+) and npm
- [Python](https://www.python.org/) 3.11+ and pip
- [git](https://git-scm.com/)
- A [Supabase](https://supabase.com/) account and project (for env values below)

## First-time setup

After cloning the repo, set up each app once.

```bash
git clone <your-repo-url>
cd Copefy
```

### 1. Frontend

```bash
cd frontend
npm install
cp .env.example .env      # Windows PowerShell: copy .env.example .env
```

Then open `.env` and fill in your Supabase values (see [Environment variables](#environment-variables)).

### 2. Backend

```bash
cd backend

# Create and activate a virtual environment
python -m venv venv

# Activate it:
#   Windows (PowerShell):   .\venv\Scripts\Activate.ps1
#   Windows (cmd):          venv\Scripts\activate.bat
#   macOS / Linux:          source venv/bin/activate

pip install -r requirements.txt
cp .env.example .env      # Windows PowerShell: copy .env.example .env
```

Then open `.env` and fill in your Supabase values.

## Running in development

Run the frontend and backend in **two separate terminals**.

### Frontend

```bash
cd frontend
npm run dev
```

Serves on http://localhost:5173

### Backend

```bash
cd backend
# activate your venv first (see setup above)
uvicorn main:app --reload
```

Serves on http://localhost:8000 — interactive API docs at http://localhost:8000/docs

## Environment variables

`.env` files are gitignored and must **never** be committed. Each app ships an
`.env.example` documenting the required keys; copy it to `.env` and fill in the
values.

Find these in your Supabase dashboard under **Project Settings -> API** and
**Project Settings -> Database**.

### `frontend/.env`

| Variable                 | Description                                            |
| ------------------------ | ------------------------------------------------------ |
| `VITE_SUPABASE_URL`      | Supabase project URL (e.g. `https://xxxx.supabase.co`) |
| `VITE_SUPABASE_ANON_KEY` | Public anon key (safe for the browser)                 |

### `backend/.env`

| Variable               | Description                                                   |
| ---------------------- | ------------------------------------------------------------ |
| `SUPABASE_URL`         | Supabase project URL                                         |
| `SUPABASE_SERVICE_KEY` | Service role key (server-side only, keep secret)             |
| `DATABASE_URL`         | Direct Postgres connection string (used for pgvector / RAG)  |
| `CORS_ORIGINS`         | Comma-separated allowed frontend origins (default dev value) |

## Conventions

- Use `snake_case` for file names, variables, and functions across the codebase.
  (React component identifiers stay `PascalCase`, as required by JSX.)

## Common gotchas

- Run the frontend and backend in separate terminals.
- Activate the Python virtual environment before running the backend.
- Make sure you're on Python 3.11+.
- If the frontend can't reach the backend, confirm the backend origin is listed
  in `CORS_ORIGINS`.
