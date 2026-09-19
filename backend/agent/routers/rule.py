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

# Near-term / preparatory / finality language the keyword list does not cover.
# Prefer recall: ambiguous present risk should still match.
ACUTE_CRISIS_PATTERNS = (
    r"\b(?:do not|don'?t|won'?t) (?:intend to |want to |plan to )?wake up\b",
    r"\bgoodbye (?:letters?|notes?|texts?|messages?)\b",
    r"\bthis is goodbye\b",
    r"\b(?:gave|giving) (?:away )?(?:the |my )?(?:things|stuff|belongings)\b",
    r"\b(?:tonight is |this is )?my last night\b",
    r"\bchosen how\b",
    r"\b(?:will not|won'?t|not) be coming back\b",
    r"\bgoing through with (?:it|this)\b",
    r"\b(?:take|taking) my life\b",
    r"\bplan(?:s|ning)? to die\b",
    r"\boverdose\b",
    r"\b(?:swallowed|took) poison\b",
    r"\bpoison on purpose\b",
    r"\b(?:can(?:not|'t)|could not) keep (?:my|her|him|them)?self safe\b",
    r"\bkeep herself safe\b",
    r"\bintend to jump\b",
    r"\bthinking of jumping\b",
    r"\babout to jump\b",
    r"\bstanding on a (?:bridge|roof|ledge)\b",
    r"\bon the (?:roof|bridge|ledge)\b.{0,60}\bjump",
    r"\bjump.{0,40}\b(?:right now|tonight)\b",
    r"\bpills ready\b",
    r"\bintend to take them all\b",
    r"\bthe means beside me\b",
    r"\bmeans beside me\b",
    r"\bhurt someone\b",
    r"\bweapon\b.{0,60}\b(?:myself|tonight|beside me|on myself)\b",
    r"\b(?:myself|tonight|beside me|alone with).{0,60}\bweapon\b",
    r"\binjur(?:e|ing|ed) myself\b",
    r"\bhurt(?:ing)? (?:her|him|them)self\b",
    r"\bhurt(?:ing)? themselves\b",
    r"\buse it on myself\b",
    r"\bcommit(?:ting)? suicide\b",
    r"\battempted to commit\b",
)

# Recovered history is suppressed only when past + present safety are both clear
# and nothing in the message indicates current or near-term danger.
HISTORICAL_PAST_ANCHOR = (
    r"\b(?:\d+|a|one|two|three|four|five|several|many) (?:years?|months?|weeks?) ago\b",
    r"\byears ago\b",
    r"\bas a teenager\b",
    r"\bused to\b",
    r"\bin 20\d{2}\b",
    r"\bfrom years ago\b",
)

PRESENT_SAFETY_RECOVERY = (
    r"\bi(?:'m| am) safe(?: now| today)?\b",
    r"\btoday i am safe\b",
    r"\bno current urges\b",
    r"\bproud of (?:my )?recovery\b",
    r"\bhow far i(?:'ve| have) come\b",
    r"\bmuch better place now\b",
    r"\bis recovering\b",
)

# Present/near-term danger. Vocabulary of a past attempt is not enough.
CURRENT_NEAR_TERM_DANGER = (
    r"\btonight\b",
    r"\bright now\b",
    r"\bthis evening\b",
    r"\bin minutes\b",
    r"\babout to\b",
    r"\bintend to\b",
    r"\bgoing to (?:kill|hurt|end|jump|die|take)\b",
    r"\bgoodbye (?:letters?|notes?|texts?|messages?)\b",
    r"\b(?:do not|don'?t|won'?t) (?:intend to |want to |plan to )?wake up\b",
    r"\b(?:tonight is |this is )?my last night\b",
    r"\bgoing through with (?:it|this)\b",
    r"\b(?:will not|won'?t|not) be coming back\b",
    r"\boverdose\b",
    r"\bpills ready\b",
    r"\bthe means beside me\b",
    r"\bkeep (?:my|her|him|them)?self safe\b",
    r"\bstill (?:want to die|suicidal|self-harming)\b",
)

# Explicit denial of current self-risk. Other acute language in the same
# message still wins.
NEGATED_SELF_RISK = (
    r"\b(?:do not|don'?t) want to die\b",
    r"\bnot hurt myself\b",
    r"\bnot (?:thinking of |going to )?harm(?:ing)? myself\b",
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


def _is_historical_recovery(normalized: str) -> bool:
    if not _matches_any(HISTORICAL_PAST_ANCHOR, normalized):
        return False
    if not _matches_any(PRESENT_SAFETY_RECOVERY, normalized):
        return False
    if _matches_any(CURRENT_NEAR_TERM_DANGER, normalized):
        return False
    return True


def _strip_negated_self_risk(normalized: str) -> str:
    text = normalized
    for pattern in NEGATED_SELF_RISK:
        text = re.sub(pattern, " ", text)
    return _normalize(text)


def _matches_crisis(text: str) -> bool:
    normalized = _normalize(text)
    if _matches_any(CRISIS_FALSE_FRIENDS, normalized):
        return False
    if _is_historical_recovery(normalized):
        return False

    working = _strip_negated_self_risk(normalized)
    third_party = _matches_any(THIRD_PARTY_SUICIDE, working)
    first_person = _matches_any(FIRST_PERSON_RISK, working)

    # "want to die of embarrassment" is idiom, not ideation.
    if not re.search(r"\bwant to die of\b", working):
        for keyword in CRISIS_KEYWORDS:
            if not re.search(rf"\b{re.escape(keyword)}\b", working):
                continue
            if keyword in ("suicide", "suicidal") and third_party and not first_person:
                continue
            return True

    if any(re.search(pattern, working) for pattern in CRISIS_PATTERNS):
        return True
    return _matches_any(ACUTE_CRISIS_PATTERNS, working)


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


# Journals also when the user names a specific life thing we have not been
# told in chat (my interview, this trip) — not symptom words (my anxiety).
_CLINICAL_SELF_NOUNS = frozenset({
    "anxiety", "anxious", "depression", "depressed", "ocd", "adhd", "ptsd",
    "panic", "stress", "sleep", "sleeping", "insomnia", "mood", "feeling",
    "feelings", "symptom", "symptoms", "therapy", "cbt", "grounding",
    "breathing", "health", "heart", "thoughts", "thought", "mind", "body",
    "energy", "appetite", "focus", "attention", "burnout", "overwhelm",
    "sadness", "grief", "anger", "worry", "worries", "nervousness", "fear",
    "fears", "distress", "trauma",
})
_THIS_THAT_THING = re.compile(
    r"\b(?:i|i'm|i am)\b.{0,80}\b(?:this|that)\s+([a-z][a-z'-]{1,})"
)
_MY_THING = re.compile(r"\bmy\s+([a-z][a-z'-]{1,})")
_UPCOMING_EVENT = re.compile(
    r"\bi have\b.{0,40}\b(?:a|an|my|the)\s+[a-z][a-z'-]{1,}.{0,30}"
    r"\b(?:tomorrow|today|tonight|this (?:week|weekend|morning|afternoon|evening))\b"
)


def _is_life_noun(word: str) -> bool:
    token = word.lower().strip("'")
    if token in _CLINICAL_SELF_NOUNS:
        return False
    if token.endswith("s") and token[:-1] in _CLINICAL_SELF_NOUNS:
        return False
    return True


def _has_personal_situation_for_journal(normalized: str) -> bool:
    if not _FIRST_PERSON.search(normalized):
        return False
    if _UPCOMING_EVENT.search(normalized):
        return True
    for match in _THIS_THAT_THING.finditer(normalized):
        if _is_life_noun(match.group(1)):
            return True
    for match in _MY_THING.finditer(normalized):
        if _is_life_noun(match.group(1)):
            return True
    return False


# Unresolved personal fact: the reply needs an identifying detail that is not
# already in this chat ("the person mentoring me" + "using their name").
_FIRST_PERSON = re.compile(r"\b(?:i|i'm|i’ve|i've|me|my|myself)\b")
_NAME_SLOT = re.compile(
    r"\b(?:using|use|with)\s+(?:their|his|her)\s+name\b"
    r"|\bstart (?:it|the (?:note|message|opening)) with the name\b"
    r"|\b(?:their|his|her)\s+name\b"
)
_USING_DEFINITE_SLOT = re.compile(
    r"\busing\s+the\s+(?:time|date|day|month|hours?|deadline|clinic|topic|"
    r"place|role|one)\b"
)
_IDENTIFY_PLEASE = re.compile(
    r"\bname (?:the|that)\b"
    r"|\bsay which\b"
)
_UNNAMED_PERSON = re.compile(
    r"\bthe person\b.{0,80}\b(?:me\b|i\b)"
    r"|\bthe person i\b"
    r"|\bwhoever is\b"
)
_HELP_WITH_CURRENT = re.compile(
    r"\b(?:help me|draft|rehearse|using|suggest|plan|reflect|decide|map)\b"
)
_DEFINITE_CURRENT = re.compile(
    r"\b(?:the|that) [a-z][a-z'-]{1,}.{0,50}\b(?:now|current)\b"
    r"|\bthe one that is\b"
)
# Help request that needs a concrete fact about the user's own life that is
# treated as already known / updated (not generic emotional support).
_STORED_DETAIL_ASK = re.compile(
    r"\b(?:can you|could you|help me|reflect|suggest|draft|rehearse|plan|map|"
    r"decide|start (?:it|the)|keeping|keep|using|uses|use)\b"
)
_STORED_PERSONAL_DETAIL = re.compile(
    r"\bwhat i(?:'m| am)? actually\b"
    r"|\b(?:name|date|day|month|time|deadline|clinic|amount|place|hall|"
    r"apartment|instrument|partner|role|task|plan|visit)"
    r".{0,50}\b(?:actually|settled on|confirmed|postponed|revised|updated|"
    r"switched|current|changed)\b"
    r"|\b(?:actually|settled on|confirmed|postponed(?: to)?|revised(?: to)?|"
    r"updated(?: to)?|switched(?: to)?)\b.{0,50}"
    r"\b(?:name|date|day|month|deadline|clinic|amount|place|hall|one)\b"
    r"|\bkeeping (?:the )?(?:month|date|day|name|time|deadline|place)"
    r".{0,40}in mind\b"
    r"|\buses? the (?:date|day|month|name|time|deadline|amount|place)\b"
    r"|\bnot the (?:first|old|earlier|original|previous) "
    r"(?:one|date|name|plan|deadline)\b"
    r"|\bthe name (?:we |i |they )?(?:actually )?(?:settled on|chose|picked)\b"
    r"|\bthe (?:date|day|month) .{0,40}"
    r"(?:confirmed|postponed|extended|revised|updated)\b"
)

_CALENDAR_WORDS = frozenset({
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
})
_PROPER_STOP = frozenset({
    "can", "what", "the", "how", "could", "please", "i", "when", "where", "who",
    "why", "yes", "okay", "ok", "and", "but", "for", "with", "from", "this",
    "that", "they", "them", "she", "he", "his", "her", "their", "you", "your",
}) | _CALENDAR_WORDS


def _likely_person_names(*texts: str) -> bool:
    for text in texts:
        for match in re.finditer(r"\b[A-Z][a-z]{2,}\b", text or ""):
            if match.group(0).lower() not in _PROPER_STOP:
                return True
    return False


def _history_user_text(history: list[dict[str, str]] | None) -> str:
    return " ".join(
        entry.get("content", "")
        for entry in (history or [])
        if entry.get("role") == "user"
    )


def _asks_for_stored_personal_detail(normalized: str) -> bool:
    """True when the turn asks to use a concrete, already-known personal detail."""
    if not _FIRST_PERSON.search(normalized):
        return False
    if not _STORED_DETAIL_ASK.search(normalized):
        return False
    return bool(_STORED_PERSONAL_DETAIL.search(normalized))


def _has_unresolved_personal_fact(
    normalized: str,
    text: str,
    history: list[dict[str, str]] | None,
) -> bool:
    if not _FIRST_PERSON.search(normalized):
        return False
    name_needed = bool(_NAME_SLOT.search(normalized))
    if name_needed and _likely_person_names(text, _history_user_text(history)):
        name_needed = False
    if name_needed:
        return True
    if _USING_DEFINITE_SLOT.search(normalized):
        return True
    if _IDENTIFY_PLEASE.search(normalized):
        return True
    if _UNNAMED_PERSON.search(normalized):
        return True
    if _HELP_WITH_CURRENT.search(normalized) and _DEFINITE_CURRENT.search(normalized):
        return True
    if _asks_for_stored_personal_detail(normalized):
        return True
    return False


def _has_journal_memory_signal(
    normalized: str,
    text: str = "",
    history: list[dict[str, str]] | None = None,
) -> bool:
    return (
        _matches_any(JOURNAL_EXPLICIT_RECALL, normalized)
        or _matches_any(JOURNAL_PAST_PATTERNS, normalized)
        or _has_unresolved_personal_fact(normalized, text, history)
        or _has_personal_situation_for_journal(normalized)
    )


def _has_clinical_advice_signal(normalized: str) -> bool:
    return _matches_any(CLINICAL_ADVICE_PATTERNS, normalized)


def _is_affect_without_ask(normalized: str, text: str) -> bool:
    if _looks_like_question(text):
        return False
    return bool(
        re.search(
            r"\b(?:i(?:'m| am)|i feel|i have been)\b.{0,60}"
            r"\b(?:stressed|anxious|nervous|worried|dreading|annoyed|upset|overwhelmed)\b"
            r".{0,40}\b(?:about|with|this|that|my)\b",
            normalized,
        )
    )


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
        journal_signal = _has_journal_memory_signal(normalized, text, history)

        if not journal_signal and not clinical_advice and _is_affect_without_ask(normalized, text):
            return self._direct("personal_affect_no_stored_fact")

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
                search_query=text,
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
