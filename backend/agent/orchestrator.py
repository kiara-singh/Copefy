"""Main agent loop for /chat."""

from __future__ import annotations

import asyncio
import logging
from functools import lru_cache

from google import genai
from google.genai import types
from google.genai.errors import ClientError

from agent.prompts import CRISIS_RESPONSE, SYSTEM_PROMPT
from agent.routers import Path, get_router
from agent.routers.base import RouteDecision
from agent.tools.extract_docs import extract_unstructured
from agent.tools.semantic_search import format_chunks_for_prompt
from agent.tools.structured_db import query_structured_db
from agent.tools.web_search import web_search
from agent.types import AgentResult
from config import settings
from rag.retrieve import RetrievalPlan, RetrievedChunk, retrieve_with_strategy

logger = logging.getLogger(__name__)

CHAT_MODEL_FALLBACKS = (
    "gemini-flash-latest",
)


def _generation_configs() -> list[types.GenerateContentConfig]:
    """Flash models spend hundreds of tokens on internal thinking — budget for both."""
    return [
        types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.7,
            max_output_tokens=1024,
        ),
    ]


@lru_cache
def _client() -> genai.Client:
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is required for chat")
    return genai.Client(api_key=settings.gemini_api_key)


def _chat_models() -> list[str]:
    models = [settings.gemini_chat_model, *CHAT_MODEL_FALLBACKS]
    seen: set[str] = set()
    ordered: list[str] = []
    for model in models:
        if model and model not in seen:
            seen.add(model)
            ordered.append(model)
    return ordered


def _format_history(messages: list[dict[str, str]], limit: int = 6) -> str:
    recent = messages[-limit:]
    if not recent:
        return ""
    lines = [f"{msg['role'].upper()}: {msg['content']}" for msg in recent]
    return "Recent conversation:\n" + "\n".join(lines)


def _chunks_to_sources(chunks: list[RetrievedChunk]) -> list[dict]:
    return [
        {
            "title": chunk.title,
            "source_url": chunk.source_url,
            "category": chunk.category,
            "similarity": round(chunk.similarity, 4),
            "excerpt": chunk.content[:400].strip(),
        }
        for chunk in chunks
    ]


def _build_user_prompt(
    user_message: str,
    history: list[dict[str, str]],
    chunks: list[RetrievedChunk],
    tool_note: str | None,
) -> str:
    sections = [_format_history(history), f"USER: {user_message}"]

    if chunks:
        sections.append(
            "Background reference (generic — not about this user):\n"
            + format_chunks_for_prompt(chunks)
        )

    if tool_note:
        sections.append(f"Tool note: {tool_note}")

    if history:
        last_assistant = next(
            (m["content"] for m in reversed(history) if m["role"] == "assistant"),
            "",
        )
        if last_assistant:
            sections.append(
                f"Your last reply was: \"{last_assistant[:200]}\"\n"
                "Use a different opening and structure — do not repeat the same pattern."
            )

    sections.append("Reply as Copefy.")
    return "\n\n".join(section for section in sections if section)


def _extract_response_text(response) -> str:
    """Return visible reply text; warn if the model hit the output token cap."""
    text = (response.text or "").strip()
    if response.candidates:
        finish = response.candidates[0].finish_reason
        if finish and str(finish).endswith("MAX_TOKENS"):
            logger.warning(
                "gemini reply truncated by token limit (len=%s): %r",
                len(text),
                text[:80],
            )
    return text


def _generate_reply(prompt: str) -> tuple[str, str | None]:
    client = _client()
    last_error: ClientError | None = None

    for model in _chat_models():
        for config in _generation_configs():
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=config,
                )
                text = _extract_response_text(response)
                if text:
                    logger.info("chat model=%s", model)
                    return text, model
            except ClientError as exc:
                last_error = exc
                logger.warning("gemini model=%s code=%s", model, exc.code)
                if exc.code == 429:
                    break  # daily/minute quota — try next model
                if exc.code == 400:
                    continue  # e.g. thinking mode unsupported — try next config
                raise

    if last_error is not None:
        raise last_error

    return (
        "Thank you for sharing that with me. I'm here to listen. "
        "Would you like to tell me a bit more about what's been on your mind?",
        None,
    )


def _log_retrieval(result: AgentResult) -> None:
    trace = result.to_debug_dict()
    logger.info(
        "agent trace path=%s router=%s tools=%s kb=%s reason=%s model=%s sources=%s",
        trace["path"],
        trace["router"],
        trace["tools_used"],
        trace["kb_used"],
        trace["route_reason"],
        trace["model"],
        [s.get("source_url") for s in trace["sources"]],
    )


async def _run_stub_tool(decision: RouteDecision, user_message: str) -> dict:
    """Paths whose backends aren't built yet still report what they would have done."""
    if decision.path is Path.WEB_SEARCH:
        return await web_search(decision.web_query or user_message)
    if decision.path is Path.STRUCTURED_QUERY:
        return await query_structured_db(user_message)
    return await extract_unstructured(user_message)


async def run_agent(
    user_message: str,
    *,
    user_id: str,
    history: list[dict[str, str]] | None = None,
) -> AgentResult:
    """Run the therapy companion agent for one user turn."""
    history = history or []

    router = get_router(settings.agent_router)
    decision = await router.decide(user_message, history=history)

    if decision.path is Path.CRISIS:
        return AgentResult(
            response=CRISIS_RESPONSE,
            path=decision.path.value,
            router=decision.router,
            route_reason=decision.reason,
        )

    chunks: list[RetrievedChunk] = []
    tool_note: str | None = None
    tool_status: str | None = None
    tools_used: list[str] = []

    if decision.path is Path.SEARCH_DATABASE:
        tools_used.append("semantic_search_kb")
        plan = RetrievalPlan(
            search_query=decision.search_query,
            categories=decision.categories,
            reason=decision.reason,
        )
        _, all_chunks = await retrieve_with_strategy(
            user_message, history=history, plan=plan
        )
        chunks = all_chunks[:3]
    elif decision.path is not Path.DIRECT_ANSWER:
        tools_used.append(decision.path.value)
        tool_result = await _run_stub_tool(decision, user_message)
        tool_note = tool_result["message"]
        tool_status = tool_result["status"]

    prompt = _build_user_prompt(user_message, history, chunks, tool_note)
    reply, model = await asyncio.to_thread(_generate_reply, prompt)

    result = AgentResult(
        response=reply,
        path=decision.path.value,
        router=decision.router,
        route_reason=decision.reason,
        kb_used=bool(chunks),
        categories=list(decision.categories),
        sources=_chunks_to_sources(chunks),
        tools_used=tools_used,
        search_query=decision.search_query or None,
        model=model,
        tool_status=tool_status,
    )
    _log_retrieval(result)
    return result
