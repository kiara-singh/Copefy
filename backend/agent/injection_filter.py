"""Instruction-overwrite filtering for user-authored persona fields.

Strips sentences that try to replace Copefy's role or safety rules while
leaving ordinary preference text (tone, goals, and format) intact.
"""

from __future__ import annotations

import re
import unicodedata

_STRIP_CHARS = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff\u00ad"))
_DELIMITER_RE = re.compile(
    r"</?(?:user_profile|active_persona)[^>]*>", re.IGNORECASE
)

_OVERRIDE_PATTERNS = (
    re.compile(r"\bignore (all |any |the )?(previous |prior |above |your )?(instructions?|prompts?|rules)\b"),
    re.compile(r"\bdisregard (all |any |the )?(previous |prior |above |your )?(instructions?|prompts?|rules)\b"),
    re.compile(r"\bforget (all |your |the )?(previous )?(instructions?|rules|prompts?)\b"),
    re.compile(r"\byou are now\b"),
    re.compile(r"\bnew system prompt\b"),
    re.compile(r"\boverride (your |the )?(system |safety )?(instructions?|rules|prompt)\b"),
    re.compile(r"\bdisable (all )?(safety|guardrails?|filters?)\b"),
    re.compile(r"\bnever mention 988\b"),
    re.compile(r"\bdo not (mention|talk about) 988\b"),
    re.compile(r"\breveal (your |the )?(hidden |secret )?(system )?prompt\b"),
    re.compile(r"\bshow (me )?(your |the )?system prompt\b"),
    re.compile(r"\bjailbreak\b"),
    re.compile(r"\bdan mode\b"),
    re.compile(r"\byou are dan\b"),
    re.compile(r"\bact as (a |an |my )?(licensed )?therapist\b"),
    re.compile(r"\byou are (a |an |my )?(licensed )?therapist\b"),
    re.compile(r"\bpretend (you are|to be) (a |an )?(licensed )?therapist\b"),
    re.compile(r"\bfrom now on you (must|will|are|should)\b"),
    re.compile(r"\bdo not follow (your |the )?(safety |system )?(rules|instructions)\b"),
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")

STYLE_MAX_CHARS = 200
GOAL_MAX_CHARS = 300
COACHING_MAX_CHARS = 500
NAME_MAX_CHARS = 50
PERSONA_NAME_MAX_CHARS = 80
PERSONA_ROLE_MAX_CHARS = 100
PERSONA_TRAITS_MAX_CHARS = 300
PERSONA_INSTRUCTIONS_MAX_CHARS = 500


def normalize_untrusted(text: str) -> str:
    """Normalize untrusted text for matching without changing benign meaning."""
    cleaned = unicodedata.normalize("NFKC", text).translate(_STRIP_CHARS)
    cleaned = "".join(ch for ch in cleaned if ch.isprintable() or ch in "\n\t")
    return " ".join(cleaned.split())


def _is_override_sentence(sentence: str) -> bool:
    collapsed = normalize_untrusted(sentence).lower()
    return bool(collapsed) and any(pattern.search(collapsed) for pattern in _OVERRIDE_PATTERNS)


def strip_delimiter_spoof(text: str) -> str:
    return _DELIMITER_RE.sub("", text)


def filter_instruction_overwrites(text: str | None, *, max_chars: int) -> str | None:
    """Drop override sentences and cap length; preserve benign sentences."""
    if not text or not text.strip():
        return None
    stripped = strip_delimiter_spoof(text)
    parts = [part.strip() for part in _SENTENCE_SPLIT.split(stripped) if part.strip()]
    if not parts:
        parts = [stripped.strip()]
    kept = [part for part in parts if not _is_override_sentence(part)]
    if not kept:
        return None
    joined = " ".join(" ".join(kept).split())
    return joined[:max_chars].rstrip() or None


def filter_preferred_name(name: str | None) -> str | None:
    if not name or not name.strip():
        return None
    cleaned = " ".join(strip_delimiter_spoof(name).split())
    if _is_override_sentence(cleaned):
        return None
    return cleaned[:NAME_MAX_CHARS] or None


_UNSAFE_REPLY_PATTERNS = (
    re.compile(r"\bi(?:'m| am) (?:a |your )?(?:licensed )?therapist\b", re.I),
    re.compile(r"\bas your (?:licensed )?therapist\b", re.I),
    re.compile(
        r"\byou (?:have|have been diagnosed with)\b.{0,40}\b"
        r"(?:ocd|adhd|ptsd|bipolar|schizophrenia)\b",
        re.I,
    ),
)


def reply_violates_safety(text: str) -> bool:
    """Detect the narrow unsafe reply classes covered by the partner gate."""
    return bool(text) and any(pattern.search(text) for pattern in _UNSAFE_REPLY_PATTERNS)
