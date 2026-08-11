"""System prompts and safety copy for the therapy companion."""

SYSTEM_PROMPT = """You are Copefy, a warm mental health companion. Talk like a real person in a
conversation — not a chatbot running a script.

Your job is to help them feel heard and explore what's going on. Move the conversation
forward; do not just echo what they said.

How to respond:
- React to what they actually shared, then ask one curious question or sit with something hard.
- Vary your tone and structure — don't fall into the same opening or pattern every turn.
- Keep it short: 1-3 sentences. One question max.

Grounding rules:
- Only work with what they have told you. Do not invent, assume, or fill in details they
  haven't shared — about their situation, feelings, causes, or history.
- Do not parrot their message back, summarize it, or rephrase it as your opening move.
- Do not lecture, normalize ("that's normal"), or give unsolicited advice or coping tips.
- When reference material is provided, it is generic background knowledge — not information
  about this person. Never treat it as their story.

Do NOT diagnose. Do NOT claim to be a licensed therapist or crisis service.

If the user mentions suicide or self-harm, express care and point them to 988 or emergency services."""

CRISIS_KEYWORDS = (
    "kill myself",
    "kill herself",
    "kill himself",
    "kill themselves",
    "suicide",
    "suicidal",
    "end my life",
    "want to die",
    "hurt myself",
    "self-harm",
    "self harm",
)

# Indirect phrasing carries the same risk as the keywords above but rarely uses them:
# passive ideation, plan and means, and the behavioural signals (goodbye notes,
# giving possessions away, feeling like a burden) that precede an attempt.
# Each pattern needs enough specificity that ordinary speech does not trip it —
# "tired of waking up" is risk language; "tired after that double shift" is not.
CRISIS_PATTERNS = (
    r"\bkill(?:ing)? (?:my|her|him|them)self\b",
    r"\bhurt(?:ing)? (?:my|her|him|them)self\b",
    r"\bcut(?:ting)? myself\b",
    r"\bdon'?t want to (?:be here|be alive|live|exist)\b",
    r"\bnot wanting to live\b",
    r"\bbetter off without me\b",
    r"\bworld would (?:be (?:lighter|better)|keep spinning) without me\b",
    r"\blighter for everyone if i wasn'?t around\b",
    r"\brelieved if i (?:was|were) gone\b",
    r"\bdon'?t wake up\b",
    r"\bdidn'?t wake up tomorrow\b",
    r"\b(?:no|the) (?:point|reason) (?:in |of |for me )?(?:going on|to be alive|to live|being alive)\b",
    r"\bwant it all to (?:stop|end) (?:permanently|forever|for good)\b",
    r"\bbe around much longer\b",
    r"\bsaving up my (?:pills|meds|medication)\b",
    r"\bcounting out my (?:pills|meds|medication)\b",
    r"\bhow many pills would be too many\b",
    r"\btake too much of something\b",
    r"\bpainless ways out\b",
    r"\bwrote (?:letters|a letter|notes) to my (?:family|friends|kids)\b.*\bjust in case\b",
    r"\bgiving (?:my )?(?:things|stuff|belongings) away\b.*\b(?:won'?t need|last time)\b",
    r"\bwhat i want to happen to my things\b",
    r"\bwant to disappear\b.*\bnever come back\b",
    r"\bdisappear forever\b",
    r"\bending (?:it all|my life)\b",
    r"\bthinking about ending it\b(?!\s+with\b)",
    r"\bmake it through (?:tonight|the night)\b",
    r"\bhow i(?:'d| would) do it\b",
    r"\bimagining my funeral\b",
    r"\bdon'?t see a future for myself\b",
    r"\bmade peace with not being here\b",
    r"\bpermanent solutions?\b",
    r"\bhopes? the surgery goes wrong\b",
    r"\bin case i don'?t see them again\b",
    r"\btired of waking up\b",
    r"\bfeel like a burden\b",
    r"\bnobody would miss me\b",
    r"\bstopped showing up\b",
    r"\blast birthday i have\b",
    r"\bno way out of this other than\b",
    r"\bhoping something happens\b.*\bdriv",
    r"\bdriv(?:ing|e).*\bhoping something happens\b",
    r"\bgoodbye texts?\b",
    r"\bstood on the bridge\b",
    r"\bbought something i shouldn'?t\b",
    r"\bi attempted\b",
    r"\bending my life\b",
    r"\bwho is suicidal\b",
)

CRISIS_RESPONSE = (
    "I'm really glad you told me that, and I'm concerned about your safety. "
    "You deserve support right now. If you're in the U.S., you can call or text 988 "
    "to reach the Suicide & Crisis Lifeline, or contact your local emergency services. "
    "I'm here with you, but I'm not a crisis service — please reach out to someone "
    "who can help keep you safe."
)
