"""Allowlisted domains, sitemaps, BFS roots, and category seed URLs for online ingest."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from rag import ANXIETY_SUBTYPES, CATEGORIES

# Domains we are allowed to crawl or download PDFs from.
ALLOWED_DOMAINS: frozenset[str] = frozenset(
    {
        "www.nimh.nih.gov",
        "nimh.nih.gov",
        "www.cdc.gov",
        "cdc.gov",
        "www.samhsa.gov",
        "samhsa.gov",
        "www.mentalhealth.gov",
        "mentalhealth.gov",
        "medlineplus.gov",
        "www.medlineplus.gov",
        "www.who.int",
        "who.int",
        "www.nhs.uk",
        "nhs.uk",
        "www.nami.org",
        "nami.org",
        "adaa.org",
        "www.adaa.org",
        "chadd.org",
        "www.chadd.org",
        "iocdf.org",
        "www.iocdf.org",
        "www.ptsd.va.gov",
        "ptsd.va.gov",
        "www.ncbi.nlm.nih.gov",
        "ncbi.nlm.nih.gov",
        "pmc.ncbi.nlm.nih.gov",
        "www.health.nih.gov",
        "health.nih.gov",
        "www.anxietycanada.com",
        "anxietycanada.com",
        "www.mind.org.uk",
        "mind.org.uk",
        "www.rcpsych.ac.uk",
        "rcpsych.ac.uk",
    }
)

# Bot-blocked or low-value for discovery — keep existing DB rows, skip new URLs.
BLOCKED_DOMAINS: frozenset[str] = frozenset(
    {
        "www.mayoclinic.org",
        "mayoclinic.org",
    }
)

# Per-domain path prefixes (empty tuple = entire domain allowed).
DOMAIN_PATH_PREFIXES: dict[str, tuple[str, ...]] = {
    "www.nimh.nih.gov": ("/health/",),
    "nimh.nih.gov": ("/health/",),
    "www.cdc.gov": ("/mentalhealth/", "/adhd/", "/depression/", "/mental-health/", "/ncbddd/adhd/", "/ncbddd/"),
    "cdc.gov": ("/mentalhealth/", "/adhd/", "/depression/", "/mental-health/", "/ncbddd/adhd/", "/ncbddd/"),
    "medlineplus.gov": ("/",),
    "www.medlineplus.gov": ("/",),
    "www.mentalhealth.gov": ("/",),
    "mentalhealth.gov": ("/",),
    "www.who.int": ("/news-room/", "/health-topics/", "/teams/mental-health", "/publications/"),
    "who.int": ("/news-room/", "/health-topics/", "/teams/mental-health", "/publications/"),
    "www.nhs.uk": ("/mental-health/", "/conditions/", "/medicines/"),
    "nhs.uk": ("/mental-health/", "/conditions/", "/medicines/"),
    "www.nami.org": ("/about-mental-illness/", "/your-journey/", "/support-education/"),
    "nami.org": ("/about-mental-illness/", "/your-journey/", "/support-education/"),
    "adaa.org": ("/",),
    "www.adaa.org": ("/",),
    "chadd.org": ("/about-adhd/", "/adhd-weekly/", "/understanding-adhd/"),
    "www.chadd.org": ("/about-adhd/", "/adhd-weekly/", "/understanding-adhd/"),
    "iocdf.org": ("/about-ocd/", "/about-ocd/ocd/", "/expert-opinions/", "/blog/"),
    "www.iocdf.org": ("/about-ocd/", "/about-ocd/ocd/", "/expert-opinions/", "/blog/"),
    "www.ptsd.va.gov": ("/",),
    "ptsd.va.gov": ("/",),
    "www.ncbi.nlm.nih.gov": ("/pmc/articles/",),
    "ncbi.nlm.nih.gov": ("/pmc/articles/",),
    "pmc.ncbi.nlm.nih.gov": ("/articles/",),
    "www.health.nih.gov": ("/",),
    "health.nih.gov": ("/",),
    "www.anxietycanada.com": ("/",),
    "anxietycanada.com": ("/",),
    "www.mind.org.uk": ("/information-support/",),
    "mind.org.uk": ("/information-support/",),
    "www.rcpsych.ac.uk": ("/mental-health/",),
    "rcpsych.ac.uk": ("/mental-health/",),
}

URL_EXCLUDE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"/search",
        r"/login",
        r"/signup",
        r"/cart",
        r"/privacy",
        r"/terms",
        r"/contact",
        r"/careers",
        r"/jobs",
        r"/donate",
        r"/events/",
        r"/calendar",
        r"/newsletter",
        r"/feed",
        r"/rss",
        r"/tag/",
        r"/author/",
        r"/wp-json",
        r"\.(jpg|jpeg|png|gif|svg|zip|mp4|mp3)$",
    )
)

SITEMAP_URLS: tuple[str, ...] = (
    "https://medlineplus.gov/sitemap.xml",
    "https://www.nami.org/sitemap.xml",
    "https://www.nhs.uk/sitemaps/sitemap-content.xml",
    "https://www.nhs.uk/sitemaps/sitemap.xml",
    "https://chadd.org/sitemap.xml",
    "https://iocdf.org/sitemap.xml",
    "https://www.ptsd.va.gov/sitemap.xml",
    "https://www.anxietycanada.com/sitemap_index.xml",
    "https://www.anxietycanada.com/sitemap.xml",
    "https://www.mind.org.uk/sitemap.xml",
    "https://www.rcpsych.ac.uk/sitemap.xml",
    "https://adaa.org/sitemap.xml",
)

# Extra BFS entry points beyond category seeds.
BFS_ROOT_URLS: tuple[str, ...] = (
    "https://www.nimh.nih.gov/health/topics",
    "https://www.nimh.nih.gov/health/publications",
    "https://medlineplus.gov/mentalhealth.html",
    "https://medlineplus.gov/anxiety.html",
    "https://medlineplus.gov/depression.html",
    "https://medlineplus.gov/encyclopedia.html",
    "https://www.mentalhealth.gov/what-to-look-for",
    "https://www.mentalhealth.gov/mental-health-conditions",
    "https://adaa.org/understanding-anxiety",
    "https://adaa.org/understanding-anxiety/depression",
    "https://www.nami.org/about-mental-illness/mental-health-conditions",
    "https://www.nhs.uk/mental-health/",
    "https://www.nhs.uk/mental-health/conditions/",
    "https://www.nhs.uk/conditions/",
    "https://www.ptsd.va.gov/understand/what",
    "https://www.ptsd.va.gov/understand/common",
    "https://iocdf.org/about-ocd/",
    "https://chadd.org/about-adhd/overview/",
    "https://www.who.int/health-topics/mental-health",
    "https://www.anxietycanada.com/anxiety-disorders/",
    "https://www.anxietycanada.com/articles/",
    "https://www.mind.org.uk/information-support/types-of-mental-health-problems/",
    "https://www.rcpsych.ac.uk/mental-health/mental-illnesses-and-mental-health-problems",
    "https://adaa.org/understanding-anxiety/panic-disorder",
    "https://adaa.org/understanding-anxiety/specific-phobias",
    "https://adaa.org/understanding-anxiety/social-anxiety-disorder",
)

# NCBI E-utilities search phrases per category for open-access PMC top-up.
# Multiple phrases per category are OR'd server-side by running one query each.
PMC_SEARCH_TERMS: dict[str, tuple[str, ...]] = {
    "adhd": ("attention deficit hyperactivity disorder",),
    "depression": ("major depressive disorder", "depression treatment"),
    "gad": ("generalized anxiety disorder",),
    "panic_disorder": ("panic disorder", "panic attack treatment"),
    "phobias": ("specific phobia", "agoraphobia"),
    "social_anxiety": ("social anxiety disorder", "social phobia"),
    "ocd": ("obsessive compulsive disorder",),
    "ptsd": ("posttraumatic stress disorder",),
}

# PMC keys for anxiety discovery (subtype-specific queries).
PMC_ANXIETY_SUBTYPE_TERMS: dict[str, tuple[str, ...]] = {
    st: PMC_SEARCH_TERMS[st] for st in ANXIETY_SUBTYPES
}

TOP_LEVEL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "adhd": ("adhd", "attention-deficit", "attention deficit", "hyperactivity"),
    "depression": ("depression", "depressive", "major-depression", "mdd", "depressed"),
    "anxiety": ("anxiety", "anxiety-disorder", "anxiety disorder", "worried", "worry"),
    "ocd": ("obsessive-compulsive", "obsessive compulsive", "ocd"),
    "ptsd": ("ptsd", "post-traumatic", "posttraumatic", "post traumatic", "traumatic stress"),
}

ANXIETY_SUBTYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "gad": (
        "generalized-anxiety",
        "generalised-anxiety",
        "generalized anxiety",
        "generalised anxiety",
        "gad",
    ),
    "panic_disorder": ("panic-disorder", "panic disorder", "panic-attack", "panic attack"),
    "phobias": ("phobia", "specific-phobia", "agoraphobia"),
    "social_anxiety": (
        "social-anxiety",
        "social anxiety",
        "social-phobia",
        "social phobia",
    ),
}

# Backward-compatible alias for any legacy imports.
CATEGORY_KEYWORDS = {**TOP_LEVEL_KEYWORDS, **ANXIETY_SUBTYPE_KEYWORDS}


@dataclass(frozen=True)
class SeedSource:
    url: str
    category: str
    source_type: str = "web"  # web | pdf
    anxiety_subtype: str | None = None


SEED_SOURCES: tuple[SeedSource, ...] = (
    # ADHD
    SeedSource("https://www.nimh.nih.gov/health/topics/attention-deficit-hyperactivity-disorder-adhd", "adhd"),
    SeedSource("https://www.nimh.nih.gov/health/publications/attention-deficit-hyperactivity-disorder-what-you-need-to-know", "adhd"),
    SeedSource("https://medlineplus.gov/attentiondeficithyperactivitydisorder.html", "adhd"),
    SeedSource("https://www.cdc.gov/adhd/about/index.html", "adhd"),
    SeedSource("https://chadd.org/about-adhd/overview/", "adhd"),
    # Depression
    SeedSource("https://www.nimh.nih.gov/health/topics/depression", "depression"),
    SeedSource("https://www.nimh.nih.gov/health/publications/depression", "depression"),
    SeedSource("https://medlineplus.gov/depression.html", "depression"),
    SeedSource("https://www.nami.org/about-mental-illness/mental-health-conditions/depression", "depression"),
    # Anxiety (subtype hints for balanced discovery)
    SeedSource("https://www.nimh.nih.gov/health/topics/anxiety-disorders", "anxiety", anxiety_subtype="gad"),
    SeedSource(
        "https://www.nimh.nih.gov/health/publications/generalized-anxiety-disorder-gad",
        "anxiety",
        anxiety_subtype="gad",
    ),
    SeedSource("https://medlineplus.gov/anxiety.html", "anxiety", anxiety_subtype="gad"),
    SeedSource(
        "https://adaa.org/understanding-anxiety/generalized-anxiety-disorder-gad",
        "anxiety",
        anxiety_subtype="gad",
    ),
    SeedSource(
        "https://www.nimh.nih.gov/health/publications/panic-disorder-when-fear-overwhelms",
        "anxiety",
        anxiety_subtype="panic_disorder",
    ),
    SeedSource("https://medlineplus.gov/panicdisorder.html", "anxiety", anxiety_subtype="panic_disorder"),
    SeedSource("https://adaa.org/understanding-anxiety/panic-disorder", "anxiety", anxiety_subtype="panic_disorder"),
    SeedSource(
        "https://www.anxietycanada.com/disorders/panic-disorder/",
        "anxiety",
        anxiety_subtype="panic_disorder",
    ),
    SeedSource(
        "https://www.mind.org.uk/information-support/types-of-mental-health-problems/anxiety-and-panic-attacks/",
        "anxiety",
        anxiety_subtype="panic_disorder",
    ),
    SeedSource(
        "https://www.rcpsych.ac.uk/mental-health/mental-illnesses-and-mental-health-problems/anxiety-panic-and-phobias",
        "anxiety",
        anxiety_subtype="panic_disorder",
    ),
    SeedSource("https://medlineplus.gov/phobias.html", "anxiety", anxiety_subtype="phobias"),
    SeedSource("https://adaa.org/understanding-anxiety/specific-phobias", "anxiety", anxiety_subtype="phobias"),
    SeedSource("https://www.anxietycanada.com/disorders/specific-phobias/", "anxiety", anxiety_subtype="phobias"),
    SeedSource(
        "https://www.mind.org.uk/information-support/types-of-mental-health-problems/phobias/",
        "anxiety",
        anxiety_subtype="phobias",
    ),
    SeedSource(
        "https://www.nimh.nih.gov/health/publications/social-anxiety-disorder-more-than-just-shyness",
        "anxiety",
        anxiety_subtype="social_anxiety",
    ),
    SeedSource("https://medlineplus.gov/socialanxietydisorder.html", "anxiety", anxiety_subtype="social_anxiety"),
    SeedSource(
        "https://adaa.org/understanding-anxiety/social-anxiety-disorder",
        "anxiety",
        anxiety_subtype="social_anxiety",
    ),
    SeedSource(
        "https://www.anxietycanada.com/disorders/social-anxiety-disorder/",
        "anxiety",
        anxiety_subtype="social_anxiety",
    ),
    SeedSource(
        "https://www.mind.org.uk/information-support/types-of-mental-health-problems/social-anxiety/",
        "anxiety",
        anxiety_subtype="social_anxiety",
    ),
    # OCD
    SeedSource("https://www.nimh.nih.gov/health/topics/obsessive-compulsive-disorder-ocd", "ocd"),
    SeedSource("https://www.nimh.nih.gov/health/publications/obsessive-compulsive-disorder-when-unwanted-thoughts-take-over", "ocd"),
    SeedSource("https://medlineplus.gov/obsessivecompulsivedisorder.html", "ocd"),
    SeedSource("https://iocdf.org/about-ocd/", "ocd"),
    SeedSource("https://www.mind.org.uk/information-support/types-of-mental-health-problems/obsessive-compulsive-disorder-ocd/", "ocd"),
    # PTSD
    SeedSource("https://www.nimh.nih.gov/health/topics/post-traumatic-stress-disorder-ptsd", "ptsd"),
    SeedSource("https://www.nimh.nih.gov/health/publications/post-traumatic-stress-disorder-ptsd", "ptsd"),
    SeedSource("https://medlineplus.gov/posttraumaticstressdisorder.html", "ptsd"),
    SeedSource("https://www.ptsd.va.gov/understand/what/ptsd_basics.asp", "ptsd"),
    SeedSource("https://www.mind.org.uk/information-support/types-of-mental-health-problems/post-traumatic-stress-disorder-ptsd-and-complex-ptsd/", "ptsd"),
)


def _host(url: str) -> str:
    return urlparse(url).netloc.lower()


def domain_allowed(url: str) -> bool:
    host = _host(url)
    if host in BLOCKED_DOMAINS:
        return False
    return host in ALLOWED_DOMAINS


def path_allowed(url: str) -> bool:
    host = _host(url)
    path = urlparse(url).path.lower()
    prefixes = DOMAIN_PATH_PREFIXES.get(host)
    if prefixes is None:
        return True
    if prefixes == ("/",):
        return True
    return any(path.startswith(prefix.lower()) for prefix in prefixes)


def url_excluded(url: str) -> bool:
    return any(pattern.search(url) for pattern in URL_EXCLUDE_PATTERNS)


def seeds_for_categories(categories: list[str] | None = None) -> list[SeedSource]:
    selected = set(categories) if categories else set(CATEGORIES)
    unknown = selected - set(CATEGORIES)
    if unknown:
        raise ValueError(f"Unknown categories: {sorted(unknown)}")
    return [s for s in SEED_SOURCES if s.category in selected]


def seed_hint_category(seed: SeedSource) -> str:
    """Discovery/classify hint: legacy subtype slug or top-level category."""
    return seed.anxiety_subtype or seed.category
