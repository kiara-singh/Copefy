"""AI-driven router: the model picks the path from the same six options."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time

from google import genai
from google.genai import types
from google.genai.errors import ClientError

from agent.routers.base import PATH_VALUES, Path, RouteDecision
from agent.routers.rule import sanitize_web_query
from config import settings
from rag.retrieve import build_retrieval_plan

logger = logging.getLogger(__name__)

ROUTER_INSTRUCTION = """You route messages for Copefy, a mental health companion app.
Users mostly talk about themselves: their feelings, symptoms, and daily life.

Pick exactly one path:

- crisis: any mention or hint of suicide, self-harm, or not wanting to be alive.
  Includes indirect phrasing (feeling like a burden, giving possessions away,
  writing goodbye notes, having a plan). When unsure, choose crisis.
- direct_answer: venting, vague check-ins, short replies, chit-chat, or anything
  best met with conversation rather than a lookup.
- search_database: the user shares symptoms, asks how to cope, or asks whether
  something is normal. The app has a curated clinical knowledge base covering
  ADHD, depression, anxiety, OCD, and PTSD.
- structured_query: the user asks about their own logged data — mood scores,
  journal counts, streaks, profile settings.
- document_extraction: the user refers to a file they uploaded or attached.
- web_search: LAST RESORT. Only when the user wants an external fact the model
  plausibly does not know and the clinical knowledge base would not cover:
  current events, new guidance, prices, local services, specific organisations.

Preference order when torn: crisis, then direct_answer, then search_database,
then web_search. Never send someone's personal or emotional disclosure to
web_search. A question about symptoms is search_database, not web_search.

Respond with JSON only: {"path": "<one of the six>", "reason": "<short phrase>"}"""

RESPONSE_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "path": types.Schema(type=types.Type.STRING, enum=list(PATH_VALUES)),
        "reason": types.Schema(type=types.Type.STRING),
    },
    required=["path", "reason"],
)


# The Gemini client is not safe to share across threads, and eval runs fan out over
# asyncio.to_thread, so keep one client per thread.
_local = threading.local()

RATE_LIMIT_RETRIES = 4
RATE_LIMIT_BACKOFF_S = 15


def _retry_delay_s(exc: ClientError, attempt: int) -> float:
    """Prefer the delay the API asks for; fall back to linear backoff."""
    fallback = RATE_LIMIT_BACKOFF_S * (attempt + 1)
    details = (exc.details or {}).get("error", {}).get("details", [])
    for detail in details:
        raw = detail.get("retryDelay")
        if raw:
            try:
                return max(fallback, float(str(raw).rstrip("s")) + 1)
            except ValueError:
                break
    return fallback


def _client() -> genai.Client:
    api_key = settings.agent_router_api_key or settings.gemini_api_key
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is required for the AI router")
    client = getattr(_local, "client", None)
    if client is None:
        client = genai.Client(api_key=api_key)
        _local.client = client
    return client


def _format_history(history: list[dict[str, str]], limit: int = 4) -> str:
    recent = history[-limit:]
    if not recent:
        return ""
    lines = [f"{entry['role'].upper()}: {entry['content']}" for entry in recent]
    return "Recent conversation:\n" + "\n".join(lines) + "\n\n"


def _call_model(prompt: str) -> tuple[str, str]:
    config = types.GenerateContentConfig(
        system_instruction=ROUTER_INSTRUCTION,
        temperature=0.0,
        response_mime_type="application/json",
        response_schema=RESPONSE_SCHEMA,
        max_output_tokens=256,
    )

    for attempt in range(RATE_LIMIT_RETRIES + 1):
        try:
            response = _client().models.generate_content(
                model=settings.agent_router_model,
                contents=prompt,
                config=config,
            )
            break
        except ClientError as exc:
            if exc.code != 429 or attempt == RATE_LIMIT_RETRIES:
                raise
            time.sleep(_retry_delay_s(exc, attempt))

    payload = json.loads(response.text or "{}")
    return str(payload.get("path", "")), str(payload.get("reason", ""))


class AIRouter:
    name = "ai"

    async def decide(
        self,
        message: str,
        *,
        history: list[dict[str, str]] | None = None,
    ) -> RouteDecision:
        history = history or []
        text = message.strip()
        if not text:
            return RouteDecision(
                path=Path.DIRECT_ANSWER, reason="empty_message", router=self.name
            )

        prompt = f"{_format_history(history)}USER: {text}"

        try:
            raw_path, reason = await asyncio.to_thread(_call_model, prompt)
            path = Path(raw_path)
        except Exception as exc:  # noqa: BLE001 - never fail a chat turn on routing
            logger.warning("ai router fell back to direct_answer: %s", exc)
            return RouteDecision(
                path=Path.DIRECT_ANSWER, reason="router_error", router=self.name
            )

        return self._enrich(path, reason or "ai_choice", text, history)

    def _enrich(
        self,
        path: Path,
        reason: str,
        message: str,
        history: list[dict[str, str]],
    ) -> RouteDecision:
        """Attach whatever the chosen path needs to actually run."""
        if path is Path.SEARCH_DATABASE:
            plan = build_retrieval_plan(message, history)
            return RouteDecision(
                path=path,
                reason=reason,
                router=self.name,
                search_query=plan.search_query,
                categories=plan.categories,
                corpus="clinical",
            )

        if path is Path.WEB_SEARCH:
            return RouteDecision(
                path=path,
                reason=reason,
                router=self.name,
                web_query=sanitize_web_query(message),
            )

        return RouteDecision(path=path, reason=reason, router=self.name)
