"""Rule-based router: pattern matching over the six paths."""

from __future__ import annotations

import re

from agent.prompts import CRISIS_KEYWORDS, CRISIS_PATTERNS
from agent.routers.base import Path, RouteDecision
from rag.retrieve import (
    build_retrieval_plan,
    has_clinical_content,
    is_fragment_reply,
    is_vague_checkin,
    looks_like_venting,
    recent_user_context,
)

# How many recent user turns to re-check for crisis language. A follow-up like
# "yeah, that's what I meant" carries the risk of the turn before it.
CRISIS_HISTORY_TURNS = 2

# Phrases that contain crisis vocabulary but are ordinary speech / media titles.
# Checked before keywords so "Suicide Squad" and "die of embarrassment" stay safe.
CRISIS_FALSE_FRIENDS = (
    r"\bsuicide squad\b",
    r"\bself-harm traps?\b",
    r"\bdie of embarrassment\b",
    r"\bkilling time\b",
    r"\boverdosed? on (?:sugar|chocolate|candy)\b",
    r"\bcut class\b",
    r"\bhanging by a thread\b",
)

# Bare "suicide" / "suicidal" about someone else (grief, partner's history) is not
# the user's own crisis unless they also speak in the first person about risk.
THIRD_PARTY_SUICIDE = (
    r"\blost .{0,40} to suicide\b",
    r"\b(?:friend|roommate|boyfriend|girlfriend|husband|wife|partner|fiance|"
    r"fiancée|mom|dad|mother|father|parent|brother|sister|birth mother|"
    r"adopted (?:mother|father))\b.{0,60}\b(?:suicid|kill(?:ed)? (?:her|him|them)self)",
    r"\b(?:suicid|committed suicide|died by suicide|attempted suicide).{0,60}\b"
    r"(?:friend|roommate|boyfriend|girlfriend|husband|wife|partner|mom|dad|"
    r"mother|father|parent|brother|sister)\b",
)

FIRST_PERSON_RISK = (
    r"\b(?:i|i'm|i am|i've|i have)\b.{0,40}\b(?:suicid|kill myself|hurt myself|"
    r"self[-\s]?harm|want to die|shouldn'?t be here)",
)

DOCUMENT_PATTERNS = (
    r"\b(?:i )?(?:uploaded|attached|sent you)\b",
    r"\b(?:the|my|this) (?:attached|uploaded) \w+",
    r"\bread the (?:pdf|file|document|attachment|referral letter)\b",
    r"\b(?:in|from) the (?:document|file|pdf|attachment) (?:i|you)\b",
    r"\bdocument i sent\b",
    r"\bsummarize the attached\b",
    r"\b(?:the|my|this|assessment) document\b",
    r"\btreatment plan document\b",
    r"\b(?:treatment|assessment) plan\b.*\b(?:say|says|about)\b",
    r"\b(?:report|file|document|notes) i (?:shared|sent|gave)\b",
    r"\bfile i gave\b",
    r"\btherapist notes\b",
    r"\breferral letter\b",
    r"\b(?:scan|screenshot) of\b",
    r"\bdropped a\b.+\b(?:sheet|file|pdf|document|worksheet)\b",
    r"\bi sent a screenshot\b",
    r"\bin the chat\b.+\b(?:scan|file|document|results)\b",
    r"\b(?:scan|file|document|results).+\bin the chat\b",
)

STRUCTURED_PATTERNS = (
    r"\bmy (?:average|avg) (?:mood|sleep)\b",
    r"\baverage (?:mood|sleep)\b",
    r"\bmood (?:logs?|scores?|tags?|trend|numbers?|average)\b",
    # Anchored on a past-tense "I" or on a thing we actually store, so rhetorical
    # venting ("how many times do I have to explain this?") is not read as a query.
    r"\bhow many times (?:did|have) i\b",
    r"\bhow many (?:\w+ ){0,2}(?:entries|logs|sessions|check-?ins|journals)\b",
    r"\bhow many check-?ins\b",
    r"\bhow (?:often|long) have i\b",
    r"\bmy (?:longest )?streak\b",
    r"\bshow me my\b",
    r"\bpull my (?:mood|sleep|journal)\b",
    r"\bmy profile\b",
    r"\bwhen did i (?:sign up|join|start)\b",
    r"\bdid i (?:rate|log|track|journal)\b",
    r"\bmy (?:sleep|mood) tracking\b",
    r"\blast journal entry\b",
    r"\brate(?:d)? my mood\b",
    r"\bmood average\b",
)

# Deliberately narrow: this router should under-fire on web rather than send a
# personal disclosure outward.
WEB_EXPLICIT_PATTERNS = (
    # "look up at the ceiling" is coping, not a search request.
    r"\blook up\b(?!\s+at\b)",
    r"\bsearch online\b",
    r"\bsearch the web\b",
    # "searching for answers in myself" is venting, not web.
    r"\bsearch for\b(?!\s+answers\b)",
    r"\bgoogle\b(?!ing\b)",
    r"\bcan you find\b(?!\s+me\s+(?:some|a little|peace|patience))",
    # "find me some peace / patience" is metaphorical.
    r"\bfind me\b(?!\s+(?:some|a little|peace|patience))",
)

# Weaker signals — only route outward when there is no clinical content to ground on.
WEB_SOFT_PATTERNS = (
    r"\bwhat'?s the news\b",
    r"\blatest (?:research|guidance|news|studies)\b",
    r"\bnewer edition\b",
    r"\bgoing rate\b",
    r"\b(?:clinic|group|therapist|psychiatrist|support).{0,40}\bnear\b",
    r"\bnear\b.{0,40}\b(?:clinic|group|therapist|psychiatrist|support)\b",
    r"\b(?:in )?(?:toronto|vancouver|calgary|ontario|the us|canada)\b",
    r"\b(?:camh|kids help phone)\b",
    r"\b(?:did )?the who\b",
    r"\binsurance plans?\b",
)

# Current-events / price / hours asks. These win even when a condition is named
# ("TMS for depression this year"), but only on questions — a statement like
# "my depression is worse this year" stays in the knowledge base.
WEB_CURRENT_PATTERNS = (
    r"\bthis year\b",
    r"\bthese days\b",
    r"\bstill going on\b",
    r"\bthis month\b",
    r"\bcurrent (?:wait times|guidance|cost|walk-in|hours)\b",
)

QUESTION_STARTERS = (
    r"^(?:what|who|where|when|why|how|is|are|has|have|did|do|can|could|which|are there)\b",
)

# Strip first-person context out of a web query so the outbound search is a
# factual phrase rather than the user's own words.
WEB_QUERY_STRIPS = (
    r"^(?:can you|could you|please)\s+",
    r"^(?:look up|search online for|search for|search|find me|find|google)\s+",
    r"^(?:what'?s|what is|what are)\s+",
    r"\?+$",
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _matches_crisis(text: str) -> bool:
    normalized = _normalize(text)
    if any(re.search(pattern, normalized) for pattern in CRISIS_FALSE_FRIENDS):
        return False

    third_party = any(re.search(pattern, normalized) for pattern in THIRD_PARTY_SUICIDE)
    first_person = any(re.search(pattern, normalized) for pattern in FIRST_PERSON_RISK)

    # "want to die of embarrassment" is idiom, not ideation.
    if not re.search(r"\bwant to die of\b", normalized):
        for keyword in CRISIS_KEYWORDS:
            if not re.search(rf"\b{re.escape(keyword)}\b", normalized):
                continue
            if keyword in ("suicide", "suicidal") and third_party and not first_person:
                continue
            return True
    return any(re.search(pattern, normalized) for pattern in CRISIS_PATTERNS)


def _crisis_in_recent_history(history: list[dict[str, str]]) -> bool:
    recent_user_turns = [entry for entry in history if entry.get("role") == "user"]
    return any(
        _matches_crisis(entry.get("content", ""))
        for entry in recent_user_turns[-CRISIS_HISTORY_TURNS:]
    )


JOURNAL_EXPLICIT_RECALL = (
    r"\bwhat did i (?:say|write|mention|log|share|tell you|note)\b",
    r"\bwhat (?:have i|did i)\s+(?:said|written|wrote|mentioned|logged|shared|noted)\b",
    r"\bwhat i (?:said|wrote|mentioned|logged|shared|noted)\b",
    r"\bwhen (?:have i|did i|was the last time i)\b",
    r"\bdid i (?:say|write|mention|log|share|talk about|journal|note)\b",
    r"\bhave i (?:mentioned|said|written|logged|shared|talked about)\b",
    r"\b(?:what did i|did i|pull up what i|show what i|search my)\b.*\b(?:in|from) my (?:previous |past |last |prior )?(?:journal|entries|entry|notes|check-?ins?)\b",
    r"\bwhat (?:triggers? for my|did i share about|did i write in my|did i say in my)\b",
    r"\bwhat was the presentation i gave\b",
    r"\bwhat did i (?:write|say) in my\b",
)

JOURNAL_PAST_PATTERNS = (
    r"\b(?:felt|been|had|experienced|struggled with|tried|done|practiced)\b.{0,35}\b(?:before|previously|in the past|last time)\b",
    r"\bdid\s+(?:exercise|walking|running|taking a walk|grounding|meditation|sleep|breathing|journaling|a walk|\w+)\s+(?:help|helped|work|worked|make me feel)\b",
    r"\bwhat (?:usually|previously|past) (?:helps|helped|works|worked) (?:for )?me\b",
    r"\bmy (?:past|previous|prior) (?:entries|experiences?|episodes?|habits?|panic|anxiety|notes?|patterns?)\b",
    r"\b(?:getting|started getting|flaring up|creeping in|feeling that familiar|happening|starting up|acting up|started slipping)\b.{0,35}\b(?:again|like before|like last (?:week|month|time))\b",
    r"\b(?:anxiety|insomnia|burnout|conflict|panic|depression|procrastination|sleep problems?|focus|thoughts?|trouble sleeping|heartbeat|panic attack)[\w\s']{0,35}\b(?:again|like before|i've been dealing with|i've experienced before|keeps coming back|keeps happening|documented earlier)\b",
)

CLINICAL_ADVICE_PATTERNS = (
    r"\b(?:what\s+(?:are|is|can|could|might)\b.*\b(?:techniques?|strategies|ways|methods|exercises?|habits?|tips|tools?|solutions?|interventions?|options?)\b)",
    r"\bwhat\s+(?:coping\s+)?(?:strategies|techniques|methods|habits|exercises|ways|tools)\b",
    r"\bwhat\s+(?:strategies|techniques|methods|exercises|tools)\s+(?:can|should|could|might)\s+i\b",
    r"\b(?:suggest|recommend|give\s+me)\b.*\b(?:techniques?|strategies|ways|exercises?|habits?|tips|methods?|advice|coping)\b",
    r"\b(?:how\s+(?:can|do|to|should)\s+(?:i|someone|one)\b.*\b(?:manage|cope|deal|handle|overcome|treat|calm|reduce|improve|stop|address|navigate|tackle)\b)",
    r"\bwhat\s+should\s+i\s+do\b",
    r"\bwhat\s+(?:can|might|could)\s+(?:i\s+do|i\s+try|help)\b",
    r"\bwhat\s+else\s+(?:should|can|could|might)\s+i\s+(?:try|do)\b",
    r"\bhow\s+(?:do|can|should)\s+i\s+(?:handle|manage|cope\s+with|deal\s+with|calm|improve)\b",
    r"\bhow\s+to\s+(?:manage|cope|deal|handle|calm|improve|overcome)\b",
    r"\bwhat\s+(?:methods|strategies|exercises|habits|tools|ways)\s+(?:work|are\s+best)\b",
    r"\bwhat\s+is\s+(?:grounding|cbt|burnout|cognitive\s+distortions?|exposure\s+therapy|mindfulness|sleep\s+hygiene|anxiety|depression|panic\s+disorder|social\s+anxiety)\b",
    r"\b(?:can\s+you\s+)?(?:explain|tell\s+me\s+about)\b.*\b(?:grounding|cbt|cognitive\s+behavioral\s+therapy|exposure\s+therapy|burnout|panic\s+attacks?|distortions?)\b",
    r"\bhow\s+does\s+(?:grounding|cbt|therapy|exposure|mindfulness|deep\s+breathing|meditation|sleep\s+hygiene|this\s+technique|this\s+exercise|diaphragmatic\s+breathing)\s+(?:work|help)\b",
    r"\bwhat\s+(?:are\s+(?:the\s+)?(?:\w+\s+)?)?(?:differences?|difference)\s+between\b",
    r"\bwhat\s+are\s+(?:the\s+)?(?:common\s+)?symptoms\s+of\b",
)


def _has_journal_memory_signal(normalized: str) -> bool:
    return _matches_any(JOURNAL_EXPLICIT_RECALL, normalized) or _matches_any(
        JOURNAL_PAST_PATTERNS, normalized
    )


def _has_clinical_advice_signal(normalized: str) -> bool:
    return _matches_any(CLINICAL_ADVICE_PATTERNS, normalized)


def _matches_any(patterns: tuple[str, ...], text: str) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def _looks_like_question(text: str) -> bool:
    stripped = text.strip()
    if stripped.endswith("?"):
        return True
    return any(re.search(pattern, stripped.lower()) for pattern in QUESTION_STARTERS)


def sanitize_web_query(message: str) -> str:
    query = _normalize(message)
    for pattern in WEB_QUERY_STRIPS:
        query = re.sub(pattern, "", query).strip()
    return query or _normalize(message)


class RuleRouter:
    name = "rule"

    async def decide(
        self,
        message: str,
        *,
        history: list[dict[str, str]] | None = None,
    ) -> RouteDecision:
        history = history or []
        text = message.strip()

        if not text:
            return self._direct("empty_message")

        normalized = _normalize(text)

        if _matches_crisis(text) or _crisis_in_recent_history(history):
            return RouteDecision(path=Path.CRISIS, reason="crisis_language", router=self.name)

        if _matches_any(DOCUMENT_PATTERNS, normalized):
            return RouteDecision(
                path=Path.DOCUMENT_EXTRACTION,
                reason="references_uploaded_document",
                router=self.name,
            )

        if _matches_any(STRUCTURED_PATTERNS, normalized):
            return RouteDecision(
                path=Path.STRUCTURED_QUERY,
                reason="asks_for_own_logged_data",
                router=self.name,
            )

        explicit_lookup = _matches_any(WEB_EXPLICIT_PATTERNS, normalized)
        soft_lookup = _matches_any(WEB_SOFT_PATTERNS, normalized) and not has_clinical_content(
            recent_user_context(history, text)
        )
        current_lookup = _matches_any(WEB_CURRENT_PATTERNS, normalized) and _looks_like_question(
            text
        )
        if explicit_lookup or soft_lookup or current_lookup:
            return RouteDecision(
                path=Path.WEB_SEARCH,
                reason="explicit_external_lookup" if explicit_lookup else "external_fact_lookup",
                router=self.name,
                web_query=sanitize_web_query(text),
            )

        if looks_like_venting(text):
            return self._direct("venting")

        if is_vague_checkin(text):
            return self._direct("vague_checkin")

        # Short answers to the assistant's question stay conversational. The reply
        # model still sees history; routing does not need to re-search the KB.
        if is_fragment_reply(text, history):
            return self._direct("conversational_followup")

        context = recent_user_context(history, text)
        clinical_content = has_clinical_content(context)
        clinical_advice = _has_clinical_advice_signal(normalized)
        journal_signal = _has_journal_memory_signal(normalized)

        if not clinical_content and not clinical_advice and not journal_signal:
            return self._direct("no_clinical_content")

        plan = build_retrieval_plan(text, history)

        # Corpus Selection (Layer 2)
        if journal_signal and clinical_advice:
            return RouteDecision(
                path=Path.SEARCH_DATABASE,
                reason="clinical_and_journal_history",
                router=self.name,
                search_query=plan.search_query,
                categories=plan.categories,
                corpus="both",
            )

        if journal_signal:
            return RouteDecision(
                path=Path.SEARCH_DATABASE,
                reason="journal_memory_recall",
                router=self.name,
                search_query=plan.search_query or text,
                categories=(),
                corpus="journal",
            )

        return RouteDecision(
            path=Path.SEARCH_DATABASE,
            reason="symptom_or_grounding",
            router=self.name,
            search_query=plan.search_query,
            categories=plan.categories,
            corpus="clinical",
        )

    def _direct(self, reason: str) -> RouteDecision:
        return RouteDecision(path=Path.DIRECT_ANSWER, reason=reason, router=self.name)
