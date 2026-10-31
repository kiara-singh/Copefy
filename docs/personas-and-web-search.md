# Personas and grounded web search

The chat Persona selector applies a saved persona to subsequent messages, alongside
profile communication preferences. The backend checks ownership and filters persona
text. Core System Prompt V1 remains authoritative. The selection is browser-wide,
remembered in local storage, and is not persisted separately for each chat.

Only web search uses GEMINI_WEB_SEARCH_API_KEY. It never substitutes for ordinary
chat, routing, embeddings, transcription, or evaluation credentials. Configure the
dedicated key privately using the placeholders in backend/.env.example.
GEMINI_WEB_SEARCH_MODEL defaults to gemini-3.1-flash-lite. Set
GEMINI_WEB_SEARCH_ENABLED=false and restart to disable search.

The grounded Gemini request produces the final response. Titles and HTTP(S) URLs
from grounding chunks are returned by /chat and rendered as clickable Sources.
Provider failure or missing grounding returns an explicit unavailable response.
Sources are not persisted with message history, so reopening a chat loads text
without its Sources list.

The local SQLite usage counter reserves ten units per attempt and stops at 4500
units per UTC month by default: at most 450 attempts, including failed calls.
Keep GEMINI_WEB_SEARCH_USAGE_DB on persistent storage shared by local workers.
Separate hosts with separate files have independent counters. This is a conservative
local guard, not a guaranteed provider billing cap: Google controls its internal
query count, and other usage in the paid project is outside this counter. Verify
current pricing and included allowances with Google before deployment.

To check manually, select a persona, ask a conversational question, then explicitly
ask to search the web for current information with sources. Look for clickable
Sources and, with tracing enabled, the web_search path and served model. This makes
a paid API request.

The integration retains exchange-based history, dated journal memory instructions,
current-message journal retrieval, metadata-only public traces, voice input, and
audio/video journal endpoints. Historical V1 evaluation reports remain incomplete;
they predate this integration and are not evidence of its live model quality.
