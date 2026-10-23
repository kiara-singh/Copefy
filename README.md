# Copefy

Copefy is a personalized mental-health companion that utilizes a RAG pipeline. A person signs in, keeps a journal, and talks with an assistant that can look back at those notes. When a message looks like a current crisis, the app skips the model and returns a fixed message that points to emergency services and the U.S. 988 Suicide & Crisis Lifeline.

## Demo

<!-- Replace the link with the hosted walkthrough. -->

[Watch the demo]([https://your-demo-video-url](https://www.youtube.com/watch?v=0Nwf5jQzqKY))

## Features

- Email and password sign-up, onboarding (preferred name, communication style, wellness goal), settings, and custom personas.
- Multi-session chat, with history stored for the signed-in account.
- Text journals, plus audio (wav, mp3, m4a, ogg, webm, flac, up to 10 MB) and video (mp4, mov, webm, up to 25 MB). Media stays in private storage. Search uses the transcript. Video journals need ffmpeg on the server `PATH`; frames are not sent to the model.
- Browser speech input on the chat composer. It types into the message box and needs Chrome, Edge, or Safari on localhost or https.
- Private PDF uploads in Settings (`.pdf`, up to 10 MB), stored under that account.
- Clinical answers from a shared knowledge base (ADHD, depression, anxiety, OCD, and PTSD) after that base is ingested.

## Architecture

The browser is a React app. It signs in with Supabase Auth and sends each chat turn to a FastAPI backend with the user's access token. The API checks that token, then:

1. **Routing.** The default router is a rule set. An optional model router can be selected with `AGENT_ROUTER=ai`. A crisis route returns the fixed helpline text and does not call Gemini.
2. **Journal retrieval.** Journal questions embed the message with Gemini and search that user's rows in `journal_chunks` through pgvector. Dated snippets are passed into the prompt as untrusted context, along with recent exchanges from the same chat.
3. **Reply.** Gemini writes the reply. A narrow check replaces text that claims a diagnosis or a therapist identity. The user and assistant messages are stored on the session.

Clinical lookup calls `match_kb_chunks` and reads `kb_documents`. Both are created by `database/setup.sql`. The tables stay empty until the ingest command below has run.

Vector search uses a direct Postgres connection. Auth, sessions, profiles, storage, and row inserts use the Supabase client. The browser holds only the anon key, so the row-level security policies in `database/setup.sql` apply to those reads and writes.

## Tech stack

- **Frontend:** React 18, TypeScript, Vite, Tailwind CSS, React Router
- **Backend:** Python, FastAPI, Gemini for chat, embeddings, and transcription
- **Data:** Supabase Auth, Postgres with pgvector, Supabase Storage

## Run locally

1. Create a project at [supabase.com](https://supabase.com/).
2. In the Supabase SQL editor, run `database/setup.sql`. It creates the app tables, row-level security, three private storage buckets (`medical-documents`, `journal-audio`, `journal-video`), and the clinical knowledge-base tables. `database/db.sql` and `database/schema_rag.sql` are older scratch schemas; leave them unused.

3. Copy the env examples and fill in the values they ask for. Both files are gitignored once copied.

```powershell
copy frontend\.env.example frontend\.env
copy backend\.env.example backend\.env
```

4. Install dependencies and start the two processes. The frontend lockfile expects Node.js 18 or newer. The backend needs Python 3.10 or newer.

From `frontend/`:

```powershell
npm install
npm run dev
```

From `backend/`, in a second terminal:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --reload
```

On macOS or Linux, activate with `source venv/bin/activate`. Run uvicorn from `backend/` so `main:app` resolves.

Sign up in the browser, finish onboarding, then open chat or the journal.

Clinical search needs documents in the knowledge base. From `backend/`, with the virtualenv active:

```powershell
python -m rag.ingest --discover-only --limit 20
python -m rag.ingest --max-embeds 500
```

The first command samples source URLs and does not call Gemini. The second crawls public sources and stores 768-dimensional embeddings in `kb_chunks` until `--max-embeds` embedding calls have been made. If `GEMINI_INGEST_API_KEY` is set, that key is used and `--max-embeds` is required.

Crawl4AI needs a browser install once, after the Python packages are installed. With the virtualenv active, run `crawl4ai-setup`. If that browser is missing, HTML fetches use the plain HTTP fallback.

## Safety

Copefy is a portfolio project, not a medical device, clinician, or crisis service. If you are in immediate danger, call your local emergency number; in the United States, call or text 988.
