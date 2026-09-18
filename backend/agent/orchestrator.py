"""Main agent loop for /chat."""

from __future__ import annotations

import asyncio
import logging
import time
from functools import lru_cache

from google import genai
from google.genai import types
from google.genai.errors import APIError

from agent.injection_filter import reply_violates_safety
from agent.persona import (
    UserPersona,
    build_profile_data_block,
    build_system_instruction,
    closing_instruction,
    new_profile_nonce,
)
from agent.pipeline_trace import PipelineTrace
from agent.preference_extract import extract_preference_knobs
from agent.prompts import (
    CRISIS_RESPONSE,
    RECENT_FACT_REUSE_PROMPT,
    RETRIEVED_UNTRUSTED_NOTICE,
    SAFETY_SANDWICH,
    UNSAFE_REPLY_FALLBACK,
)
from agent.routers import Path, get_router
from agent.routers.base import RouteDecision
from agent.tools.extract_docs import extract_unstructured
from agent.tools.semantic_search import format_chunks_for_prompt
from agent.tools.structured_db import query_structured_db
from agent.tools.web_search import web_search
from agent.types import AgentResult
from config import settings
from rag.journal_retrieve import search_journal_chunks
from rag.retrieve import RetrievalPlan, RetrievedChunk, retrieve_with_strategy

logger = logging.getLogger(__name__)

# HTTP codes where we should try the next model instead of failing the request.
# 404 = retired / unknown model id (e.g. gemini-2.5-flash-lite).
RETRYABLE_API_CODES = frozenset({429, 500, 502, 503, 504, 404})


def _should_try_next_model(exc: APIError) -> bool:
    return exc.code in RETRYABLE_API_CODES


def _generation_configs(system_instruction: str) -> list[types.GenerateContentConfig]:
    return [
        types.GenerateContentConfig(
            system_instruction=system_instruction,
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
    models = [
        settings.gemini_chat_model,
        *settings.gemini_chat_model_fallbacks_list,
    ]
    seen: set[str] = set()
    ordered: list[str] = []
    for model in models:
        if model and model not in seen:
            seen.add(model)
            ordered.append(model)
    return ordered


def _group_exchanges(messages: list[dict[str, str]]) -> list[list[dict[str, str]]]:
    """Split history into user/assistant exchanges, preserving order.

    An exchange is a user message plus the following assistant reply when present.
    A leading orphan assistant message is its own exchange.
    """
    exchanges: list[list[dict[str, str]]] = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        if msg.get("role") == "user":
            pair = [msg]
            if i + 1 < len(messages) and messages[i + 1].get("role") == "assistant":
                pair.append(messages[i + 1])
                i += 2
            else:
                i += 1
            exchanges.append(pair)
        else:
            exchanges.append([msg])
            i += 1
    return exchanges


def _recent_exchange_messages(
    messages: list[dict[str, str]],
    exchange_limit: int,
) -> list[dict[str, str]]:
    """Return messages from the last `exchange_limit` exchanges, in order."""
    if exchange_limit <= 0 or not messages:
        return []
    selected = _group_exchanges(messages)[-exchange_limit:]
    return [msg for exchange in selected for msg in exchange]


def _format_history(
    messages: list[dict[str, str]],
    exchange_limit: int | None = None,
) -> str:
    limit = (
        settings.chat_history_exchanges if exchange_limit is None else exchange_limit
    )
    recent = _recent_exchange_messages(messages, limit)
    if not recent:
        return ""
    lines = [f"{msg['role'].upper()}: {msg['content']}" for msg in recent]
    return "Recent conversation:\n" + "\n".join(lines)


def _chunks_to_sources(chunks: list[RetrievedChunk]) -> list[dict]:
    """Internal/eval source records. HTTP responses must strip retrieved text."""
    return [
        {
            "chunk_id": chunk.chunk_id,
            "document_id": chunk.document_id,
            "title": chunk.title,
            "source_url": chunk.source_url,
            "category": chunk.category,
            "similarity": round(chunk.similarity, 4),
            "created_at": chunk.created_at,
            "preview": chunk.content[:200].strip(),
            "excerpt": chunk.content[:400].strip(),
        }
        for chunk in chunks
    ]


def _retrieved_prompt_block(tag: str, heading: str, chunks: list[RetrievedChunk]) -> str:
    body = format_chunks_for_prompt(chunks)
    return (
        f"<{tag}>\n{RETRIEVED_UNTRUSTED_NOTICE}\n{heading}\n{body}\n</{tag}>"
    )


def _build_user_prompt(
    user_message: str,
    history: list[dict[str, str]],
    chunks: list[RetrievedChunk],
    tool_note: str | None,
    persona: UserPersona | None,
) -> tuple[str, bool]:
    sections = [_format_history(history), f"USER: {user_message}"]
    if history:
        sections.append(RECENT_FACT_REUSE_PROMPT)
    retrieved = False

    if chunks:
        clinical_chunks = [c for c in chunks if c.category != "journal"]
        journal_chunks = [c for c in chunks if c.category == "journal"]

        if clinical_chunks:
            retrieved = True
            sections.append(
                _retrieved_prompt_block(
                    "retrieved_clinical",
                    "Background reference (generic — not about this user):",
                    clinical_chunks,
                )
            )

        if journal_chunks:
            retrieved = True
            sections.append(
                _retrieved_prompt_block(
                    "retrieved_journal",
                    "User's past journal entries (personal memory):",
                    journal_chunks,
                )
            )

        if retrieved:
            sections.append(SAFETY_SANDWICH)

    if tool_note:
        sections.append(f"Tool note: {tool_note}")

    anti_repeat = False
    if history:
        last_assistant = next(
            (m["content"] for m in reversed(history) if m["role"] == "assistant"),
            "",
        )
        if last_assistant:
            anti_repeat = True
            sections.append(
                f"Your last reply was: \"{last_assistant[:200]}\"\n"
                "Use a different opening and structure — do not repeat the same pattern."
            )

    profile_block = build_profile_data_block(persona, nonce=new_profile_nonce())
    if profile_block:
        sections.append(profile_block)
        sections.append(SAFETY_SANDWICH)

    sections.append(closing_instruction(persona))
    return "\n\n".join(section for section in sections if section), anti_repeat


def _extract_response_text(response) -> str:
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


def _generate_reply(prompt: str, system_instruction: str) -> tuple[str, str | None]:
    client = _client()
    last_error: APIError | None = None
    models_tried: list[str] = []

    for model in _chat_models():
        models_tried.append(model)
        for config in _generation_configs(system_instruction):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=config,
                )
                text = _extract_response_text(response)
                if text:
                    if model != settings.gemini_chat_model:
                        logger.info(
                            "chat fallback model=%s (primary=%s)",
                            model,
                            settings.gemini_chat_model,
                        )
                    else:
                        logger.info("chat model=%s", model)
                    return text, model
            except APIError as exc:
                last_error = exc
                logger.warning(
                    "gemini model=%s code=%s status=%s",
                    model,
                    exc.code,
                    exc.status,
                )
                if _should_try_next_model(exc):
                    break  # try next model
                if exc.code == 400:
                    continue  # try next config for same model
                raise

    if last_error is not None:
        logger.error(
            "all chat models failed models=%s last_code=%s",
            models_tried,
            last_error.code,
        )
        raise last_error

    return (
        "Thank you for sharing that with me. I'm here to listen. "
        "Would you like to tell me a bit more about what's been on your mind?",
        None,
    )


def _corpus_reason(decision: RouteDecision) -> str:
    if decision.corpus:
        return f"router selected {decision.corpus}"
    return "default clinical"


def _log_pipeline(result: AgentResult) -> None:
    trace = result.to_debug_dict()
    logger.info(
        "agent trace path=%s router=%s tools=%s kb=%s reason=%s model=%s style=%s sources=%s",
        trace["path"],
        trace["router"],
        trace["tools_used"],
        trace["kb_used"],
        trace["route_reason"],
        trace.get("model"),
        trace.get("communication_style"),
        [s.get("source_url") for s in trace["sources"]],
    )
    if result.pipeline is not None and settings.rag_debug:
        result.pipeline.log_to_terminal()


async def _run_stub_tool(decision: RouteDecision, user_message: str) -> dict:
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
    persona: UserPersona | None = None,
) -> AgentResult:
    """Run the therapy companion agent for one user turn."""
    history = history or []
    persona = persona or UserPersona()
    pipeline = PipelineTrace()

    router = get_router(settings.agent_router)
    l1_start = time.perf_counter()
    decision = await router.decide(user_message, history=history)
    pipeline.add_timed(
        1,
        "routing",
        decision.path.value,
        l1_start,
        router=decision.router,
        reason=decision.reason,
    )

    corpus = decision.corpus or "clinical"
    pipeline.add_timed(
        2,
        "corpus",
        corpus,
        l1_start,
        reason=_corpus_reason(decision),
    )

    if decision.path is Path.CRISIS:
        result = AgentResult(
            response=CRISIS_RESPONSE,
            path=decision.path.value,
            router=decision.router,
            route_reason=decision.reason,
            pipeline=pipeline,
        )
        _log_pipeline(result)
        return result

    chunks: list[RetrievedChunk] = []
    tool_note: str | None = None
    tool_status: str | None = None
    tools_used: list[str] = []
    retrieval_meta: dict = {}

    if decision.path is Path.SEARCH_DATABASE:
        l3_start = time.perf_counter()
        corpus = decision.corpus or "clinical"

        if corpus == "journal":
            tools_used.append("search_journal_entries")
            query = user_message
            chunks = await search_journal_chunks(user_id, query, top_k=3)
            retrieval_meta = {"strategy": "journal_mmr", "candidates": len(chunks)}
        elif corpus == "both":
            tools_used.extend(["semantic_search_kb", "search_journal_entries"])
            plan = RetrievalPlan(
                search_query=decision.search_query,
                categories=decision.categories,
                reason=decision.reason,
            )
            kb_task = retrieve_with_strategy(user_message, history=history, plan=plan)
            j_task = search_journal_chunks(user_id, user_message, top_k=3)
            (_, kb_chunks, retrieval_meta), journal_chunks = await asyncio.gather(kb_task, j_task)
            chunks = kb_chunks[:2] + journal_chunks[:2]
        else:  # "clinical"
            tools_used.append("semantic_search_kb")
            plan = RetrievalPlan(
                search_query=decision.search_query,
                categories=decision.categories,
                reason=decision.reason,
            )
            _, all_chunks, retrieval_meta = await retrieve_with_strategy(
                user_message, history=history, plan=plan
            )
            chunks = all_chunks[:3]

        top_similarity = round(chunks[0].similarity, 4) if chunks else None
        if corpus in ("journal", "both"):
            traced_query = user_message
        else:
            traced_query = decision.search_query or (
                plan.search_query if "plan" in locals() else user_message
            )
        pipeline.add_timed(
            3,
            "retrieval",
            retrieval_meta.get("strategy", settings.rag_strategy),
            l3_start,
            strategy=retrieval_meta.get("strategy", settings.rag_strategy),
            search_query=traced_query,
            categories=list(decision.categories),
            candidates=retrieval_meta.get("candidates", 0),
            returned=len(chunks),
            top_similarity=top_similarity,
            sources=_chunks_to_sources(chunks),
        )
    elif decision.path is not Path.DIRECT_ANSWER:
        tools_used.append(decision.path.value)
        tool_result = await _run_stub_tool(decision, user_message)
        tool_note = tool_result["message"]
        tool_status = tool_result["status"]

    journal_memories = any(chunk.category == "journal" for chunk in chunks)
    system_instruction = build_system_instruction(
        persona, journal_memories=journal_memories
    )
    prompt, anti_repeat = _build_user_prompt(
        user_message, history, chunks, tool_note, persona
    )

    l4_start = time.perf_counter()
    reply, model = await asyncio.to_thread(_generate_reply, prompt, system_instruction)
    if reply_violates_safety(reply):
        logger.warning("blocked unsafe generated reply")
        reply = UNSAFE_REPLY_FALLBACK
    knobs = extract_preference_knobs(persona)
    style = knobs.display_style
    pipeline.add_timed(
        4,
        "generation",
        style,
        l4_start,
        communication_style=style,
        preferred_name_set=bool(knobs.preferred_name),
        wellness_goal_set=bool(knobs.wellness_goal),
        coaching_preferences_set=bool(knobs.coaching_notes),
        structured_format_requested=knobs.structured_format,
        model=model,
        history_turns=len(
            _group_exchanges(
                _recent_exchange_messages(history, settings.chat_history_exchanges)
            )
        ),
        kb_chunks_in_prompt=len(chunks),
        anti_repeat=anti_repeat,
    )

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
        communication_style=style,
        pipeline=pipeline,
    )
    _log_pipeline(result)
    return result

