"""Hybrid retrieval: personal language -> clinical KB search."""

from __future__ import annotations

import re
from dataclasses import dataclass

from rag.search import KBChunkHit

# Common phone-keyboard misspellings of clinical words. Applied in _normalize so
# "anxios" / "panik" still route the same as the tidy spelling.
TYPO_MAP = (
    ("anxios", "anxious"),
    ("anxeity", "anxiety"),
    ("worryin", "worrying"),
    ("depressd", "depressed"),
    ("panik", "panic"),
    ("flashbaks", "flashbacks"),
    ("flashbak", "flashback"),
    ("chekin", "checking"),
    ("focuss", "focus"),
    ("evrything", "everything"),
    ("latly", "lately"),
    ("reasn", "reason"),
    ("feelin", "feeling"),
    ("happend", "happened"),
)

CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "adhd": (
        "adhd",
        "attention",
        "focus",
        "distract",
        "hyperactiv",
        "hyperfocus",
        "concentrat",
        "forget",
        "losing track",
        "lose track",
        "zoning out",
        "zone out",
        "procrastinat",
        "time blindness",
        "always late",
        "can't start",
        "cant start",
        "organiz",
        "multi-step",
        "finishing tasks",
        "never finishing",
        "finish none",
        "missing deadlines",
        "lost my keys",
        "tabs open",
        "brain feels like static",
        "brain is completely fried",
        "cant hold a thought",
        "can't hold a thought",
        "talk over people",
        "sit through",
        "read the same paragraph",
        "four times longer",
        "times longer than i think",
        "not filling out",
        "carrying that list",
        "without doing any of it",
        "forgot it on the stove",
        "sitting next to me",
        "take my medication",
        "six hours had gone",
        "won't cooperate",
        "wont cooperate",
        "brain just won",
        "finish assignments",
    ),
    "depression": (
        "depress",
        "hopeless",
        "sad",
        "empty",
        "worthless",
        "motivation",
        "sleeping all day",
        "no energy",
        "numb",
        "nothing matters",
        "pointless",
        "no appetite",
        "isolate",
        "out of bed",
        "cry",
        "teared up",
        "used to enjoy",
        "pulling away",
        "snap at",
        "mood swings",
        "can't make myself",
        "cant make myself",
        "avoiding my inbox",
        "getting dressed feels",
        "stopped answering",
        "doesn't really taste",
        "doesnt really taste",
        "feel nothing",
        "feel guilty",
        "since i showered",
        "cancel plans",
        "cancelled on",
        "canceled on",
        "collecting dust",
        "burnt out",
        "burned out",
        "brushing my teeth feels",
        "tired of themselves",
        "fall apart",
        "struggle to shower",
        "eat regularly",
        "flat and far away",
        "skipped a couple of doses",
        "whole weekend in bed",
        "can't picture next month",
        "cant picture next month",
        "sleep twelve hours",
        "wake up feeling wrecked",
        "remember almost none",
        "all over the place",
        "then it crashes",
        "hasn't helped",
        "hasnt helped",
        "fall back asleep",
        "lonely",
        "grief",
        "mourning",
        "hate myself",
        "not good enough",
    ),
    "anxiety": (
        "anxious",
        "anxiety",
        "worry",
        "worried",
        "nervous",
        "panic",
        "on edge",
        "racing thoughts",
        "scared",
        "heart races",
        "heart going crazy",
        "can't breathe",
        "cant breathe",
        "crowds",
        "can't keep up",
        "lie awake",
        "dread",
        "hands shake",
        "voice shakes",
        "replay conversations",
        "rehearse",
        "stomach drops",
        "worst possible outcome",
        "can't settle",
        "cant settle",
        "clenching my jaw",
        "reread the message",
        "won't switch off",
        "wont switch off",
        "chest has been tight",
        "chest gets tight",
        "apologize for things",
        "staring at one email",
        "spiraling",
        "something wrong with me",
        "how everyone feels",
    ),
    "ocd": (
        "ocd",
        "compuls",
        "check",
        "intrusive thought",
        "ritual",
        "obsess",
        "reassurance",
        "over and over",
        "wash my hands",
        "feel right",
        "re-read",
        "rewriting",
        "replaying",
        "popping into my head",
        "doorknob",
        "have to be even",
        "turned the car around",
        "horrible image",
        "same question every",
        "feel like they're clean",
        "feel like theyre clean",
        "tap the doorframe",
        "count things",
        "ask people to confirm",
        "mentally reviewing",
        "didn't count",
        "didnt count",
        "bump the right one",
        "something terrible will happen",
    ),
    "ptsd": (
        "ptsd",
        "trauma",
        "flashback",
        "nightmare",
        "triggered",
        "hypervigil",
        "reliving",
        "loud noises",
        "loud sounds",
        "loud restaurants",
        "the accident",
        "the incident",
        "deployment",
        "avoid certain places",
        "happening again",
        "jump at",
        "startle",
        "flinch",
        "back to the door",
        "sent me right back",
        "outside my own body",
        "avoid that intersection",
        "every noise",
        "car backfired",
        "calendar hit that date",
        "whole body went cold",
        "car accident",
        "abusive",
        "abuse",
        "domestic abuse",
        "emotional abuse",
        "verbal abuse",
        "childhood",
        "foster care",
    ),
}

CLINICAL_EXPANSIONS: dict[str, str] = {
    "adhd": "attention difficulty focus executive function coping strategies",
    "depression": "low mood anhedonia fatigue depressive symptoms coping support",
    "anxiety": "excessive worry anxiety symptoms grounding coping techniques",
    "ocd": "obsessive compulsive intrusive thoughts checking rituals coping",
    "ptsd": "trauma stress hypervigilance flashbacks coping grounding safety",
}

VENTING_PATTERNS = (
    r"\btoday was\b.*\bhard\b",
    r"\bi don'?t know where to start\b",
    r"\bi just need to vent\b",
    r"\bnothing specific\b",
    r"\brough day\b",
)

# A check-in is only "vague" while it stays a bare mood word. Once someone names
# what it is about ("nervous about flying next week") there is enough to search on.
VAGUE_CHECKIN_MAX_WORDS = 4

SITUATIONAL_MARKERS = (
    "exam",
    "test",
    "work",
    "job",
    "school",
    "class",
    "partner",
    "friend",
    "family",
    "sleep",
    "deadline",
    "interview",
    "doctor",
    "money",
    "breakup",
    "fight",
    "meeting",
    "presentation",
    "fail",
    "grade",
    "boss",
    "parent",
    "mom",
    "dad",
    "because",
    "when",
    "after",
    "before",
)

VAGUE_EMOTIONAL_WORDS = (
    "anxious",
    "anxiety",
    "sad",
    "depressed",
    "stressed",
    "overwhelmed",
    "worried",
    "nervous",
    "exhausted",
    "tired",
    "down",
    "low",
    "focus",
    "on edge",
)

# Replies to the assistant's question that are too short to search on alone.
FRAGMENT_MAX_WORDS = 4

# Below this length, naming a topic ("work", "my mom") is still just a fragment.
FRAGMENT_TOPIC_MIN_WORDS = 3

CONTEXT_FRAGMENT_MAX_WORDS = 2

# Keep these specific. Bare words like "sleep" / "tired" / "what should i" pull
# ordinary chat into the KB ("I'd kill for eight hours of sleep", "what should I
# say to my therapist") and inflate false search_database rates.
CLINICAL_SIGNALS = (
    "is it normal",
    "can't stop",
    "cant stop",
    "can't sleep",
    "cant sleep",
    "cnt sleep",
    "what can i do",
    "how do i cope",
    "how can i cope",
    "how do i deal",
    "how can i deal",
    "how do i handle",
    "how can i handle",
    "what should i do when",
    "i need help",
    "worried",
    "anxious",
    "anxiety",
    "stressed",
    "nervous",
    "depressed",
    "checking",
    "flashback",
    "panic",
    "overwhelmed",
    "hopeless",
    "intrusive",
    "compuls",
    "trauma",
    "nightmare",
    "therapy session",
    "prescription",
    "medication",
    "doses",
    "symptoms",
    "can't even think straight",
    "cant even think straight",
    "eating disorder",
    "addiction",
    "abusive",
    "abuse",
    "grief",
    "lonely",
    "toxic relationship",
    "borderline",
)


@dataclass(frozen=True)
class RetrievalPlan:
    """How to search the KB. Whether to search at all is the router's call."""

    search_query: str
    categories: tuple[str, ...]
    reason: str = "search_database"


@dataclass(frozen=True)
class RetrievedChunk:
    content: str
    source_url: str | None
    title: str | None
    category: str | None
    similarity: float
    document_id: str | None = None


def _normalize(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text.strip().lower())
    for typo, fix in TYPO_MAP:
        normalized = normalized.replace(typo, fix)
    return normalized


def _detect_categories(text: str) -> list[str]:
    normalized = _normalize(text)
    scores: list[tuple[str, int]] = []

    for category, keywords in CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in normalized)
        if score:
            scores.append((category, score))

    scores.sort(key=lambda item: item[1], reverse=True)
    return [category for category, _ in scores[:2]]


def looks_like_venting(text: str) -> bool:
    normalized = _normalize(text)
    if any(re.search(pattern, normalized) for pattern in VENTING_PATTERNS):
        return True
    words = normalized.split()
    if len(words) <= 8 and not _detect_categories(text):
        emotional = ("hard", "rough", "awful", "overwhelmed", "exhausted", "tired")
        return any(word in normalized for word in emotional)
    return False


def is_vague_checkin(text: str) -> bool:
    """Short emotional openers with no situational detail — listen first, don't retrieve."""
    normalized = _normalize(text)
    words = normalized.split()
    if len(words) > VAGUE_CHECKIN_MAX_WORDS:
        return False
    if any(marker in normalized for marker in SITUATIONAL_MARKERS):
        return False
    return any(word in normalized for word in VAGUE_EMOTIONAL_WORDS)


def has_clinical_content(text: str) -> bool:
    """True when text mentions symptoms, coping, or normalization — worth KB search."""
    if _detect_categories(text):
        return True
    normalized = _normalize(text)
    return any(signal in normalized for signal in CLINICAL_SIGNALS)


def _is_context_noise(text: str) -> bool:
    """Drop very short prior user turns that are usually bot follow-ups, not topics."""
    normalized = _normalize(text)
    if len(normalized.split()) > CONTEXT_FRAGMENT_MAX_WORDS:
        return False
    if has_clinical_content(text):
        return False
    if any(marker in normalized for marker in SITUATIONAL_MARKERS):
        return False
    return True


def recent_user_context(
    history: list[dict[str, str]] | None,
    message: str,
    *,
    limit: int = 3,
) -> str:
    prior: list[str] = []
    if history:
        prior = [
            entry["content"]
            for entry in history
            if entry["role"] == "user" and not _is_context_noise(entry["content"])
        ][-(limit - 1) :]
    parts = [*prior, message.strip()]
    return " ".join(part for part in parts if part)


def _last_assistant_asked_question(history: list[dict[str, str]]) -> bool:
    for entry in reversed(history):
        if entry["role"] == "assistant":
            return "?" in entry["content"]
        if entry["role"] == "user":
            break
    return False


def is_fragment_reply(message: str, history: list[dict[str, str]] | None) -> bool:
    """Short answer to the assistant's question — don't search KB on the fragment alone."""
    if not history:
        return False

    normalized = _normalize(message)
    words = normalized.split()
    if len(words) > FRAGMENT_MAX_WORDS:
        return False
    if len(words) >= FRAGMENT_TOPIC_MIN_WORDS and any(
        marker in normalized for marker in SITUATIONAL_MARKERS
    ):
        return False
    if has_clinical_content(message):
        return False
    return _last_assistant_asked_question(history)


def _build_search_query(
    message: str,
    history: list[dict[str, str]] | None,
) -> tuple[str, tuple[str, ...]]:
    context = recent_user_context(history, message)
    categories = _detect_categories(context)
    expansion = " ".join(CLINICAL_EXPANSIONS.get(cat, "") for cat in categories)
    search_query = f"{context} {expansion}".strip()
    return search_query, tuple(categories)


def build_retrieval_plan(
    user_message: str,
    history: list[dict[str, str]] | None = None,
    *,
    reason: str = "symptom_or_grounding",
) -> RetrievalPlan:
    """Phrase the KB search for a message the router already routed to the DB."""
    search_query, categories = _build_search_query(user_message.strip(), history)
    return RetrievalPlan(
        search_query=search_query,
        categories=categories,
        reason=reason,
    )


def _tokenize(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9']+", text.lower()) if len(token) > 2}


def _rerank_hits(query: str, hits: list[KBChunkHit], top_k: int) -> list[KBChunkHit]:
    query_tokens = _tokenize(query)
    best_by_doc: dict[str, KBChunkHit] = {}

    for hit in hits:
        chunk_tokens = _tokenize(hit.content)
        overlap = len(query_tokens & chunk_tokens)
        coping_boost = (
            0.05
            if any(
                word in hit.content.lower()
                for word in ("coping", "strategy", "support", "helpful")
            )
            else 0.0
        )
        adjusted = hit.similarity + (overlap * 0.01) + coping_boost

        current = best_by_doc.get(hit.document_id)
        if current is None or adjusted > current.similarity:
            best_by_doc[hit.document_id] = KBChunkHit(
                id=hit.id,
                document_id=hit.document_id,
                content=hit.content,
                metadata=hit.metadata,
                similarity=adjusted,
                title=hit.title,
                source_url=hit.source_url,
                category=hit.category,
            )

    ranked = sorted(best_by_doc.values(), key=lambda h: h.similarity, reverse=True)
    return ranked[:top_k]


async def retrieve_with_strategy(
    user_message: str,
    *,
    history: list[dict[str, str]] | None = None,
    strategy_name: str | None = None,
    plan: RetrievalPlan | None = None,
) -> tuple[RetrievalPlan, list[RetrievedChunk], dict]:
    """Run retrieval using a named strategy (default from settings)."""
    from config import settings
    from rag.strategies import get_strategy

    name = strategy_name or settings.rag_strategy
    strategy = get_strategy(name)
    result = await strategy.retrieve(user_message, history=history, plan=plan)
    metadata = dict(result.metadata)
    metadata["strategy"] = name
    return result.plan, result.chunks, metadata
