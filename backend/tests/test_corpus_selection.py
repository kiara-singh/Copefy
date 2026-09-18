"""Tests for Layer 2 Corpus Selection (clinical, journal, both, none)."""

from __future__ import annotations

import pytest
from agent.routers import Path, get_router


@pytest.mark.asyncio
async def test_corpus_selection_contrast_groups():
    """Verify Layer 2 corpus selection across contrast groups."""
    router = get_router("rule")

    cases = [
        # Anxiety contrast
        ("What are some ways to manage anxiety?", "clinical", Path.SEARCH_DATABASE),
        ("What did I say about my anxiety last week?", "journal", Path.SEARCH_DATABASE),
        ("My anxiety is getting bad again. What should I do?", "both", Path.SEARCH_DATABASE),
        ("I'm feeling anxious today.", "none", Path.DIRECT_ANSWER),

        # Sleep contrast
        ("How can I improve my sleep?", "clinical", Path.SEARCH_DATABASE),
        ("When have I had trouble sleeping before?", "journal", Path.SEARCH_DATABASE),
        ("I'm having trouble sleeping again. What might help?", "both", Path.SEARCH_DATABASE),
        ("I barely slept last night.", "none", Path.DIRECT_ANSWER),

        # Presentation contrast
        ("What are effective strategies for overcoming public speaking fear?", "clinical", Path.SEARCH_DATABASE),
        ("What did I write in my notes about the presentation I gave?", "journal", Path.SEARCH_DATABASE),
        ("I'm getting nervous about presentations again. What should I do?", "both", Path.SEARCH_DATABASE),
        ("I have a presentation tomorrow.", "journal", Path.SEARCH_DATABASE),
        ("I'm so nervous about this interview.", "journal", Path.SEARCH_DATABASE),

        # Burnout contrast
        ("What are the main differences between stress and clinical burnout?", "clinical", Path.SEARCH_DATABASE),
        ("When was the last time I felt completely burned out?", "journal", Path.SEARCH_DATABASE),
        ("I'm getting overwhelmed with assignments like before. What might help?", "both", Path.SEARCH_DATABASE),
        ("Today was just exhausting.", "none", Path.DIRECT_ANSWER),

        # Panic contrast
        ("How does deep diaphragmatic breathing help during a panic attack?", "clinical", Path.SEARCH_DATABASE),
        ("What did I write about my panic attack after class?", "journal", Path.SEARCH_DATABASE),
        ("That racing heartbeat feeling is starting up again. How do I calm it down?", "both", Path.SEARCH_DATABASE),
        ("My heart was beating fast earlier.", "none", Path.DIRECT_ANSWER),

        # Coping contrast
        ("What is grounding and how does it help reduce distress?", "clinical", Path.SEARCH_DATABASE),
        ("Did exercise help my mood before?", "journal", Path.SEARCH_DATABASE),
        ("The grounding exercises I tried before aren't working as well today. What else should I try?", "both", Path.SEARCH_DATABASE),
        ("I went for a short walk today.", "none", Path.DIRECT_ANSWER),

        # Relationship contrast
        ("What are constructive communication strategies for handling conflict with a roommate?", "clinical", Path.SEARCH_DATABASE),
        ("What did I say about my roommate?", "journal", Path.SEARCH_DATABASE),
        ("I'm getting into arguments with my roommate again. How should I handle this?", "both", Path.SEARCH_DATABASE),
        ("My roommate can be annoying sometimes.", "journal", Path.SEARCH_DATABASE),

        # Focus contrast
        ("What are practical organizational techniques for dealing with ADHD focus issues?", "clinical", Path.SEARCH_DATABASE),
        ("Did I mention struggling to focus on my chemistry homework in previous entries?", "journal", Path.SEARCH_DATABASE),
        ("My focus has started slipping again like last week. What strategies can I use to get back on track?", "both", Path.SEARCH_DATABASE),
        ("I have a lot of homework to do.", "none", Path.DIRECT_ANSWER),

        # General / Control contrast
        ("Can you explain how cognitive behavioral therapy identifies cognitive distortions?", "clinical", Path.SEARCH_DATABASE),
        ("When have I felt homesick before?", "journal", Path.SEARCH_DATABASE),
        ("I'm feeling that familiar homesickness creeping in again. What are good ways to cope?", "both", Path.SEARCH_DATABASE),
        ("Thanks, that helped a lot.", "none", Path.DIRECT_ANSWER),
    ]

    for query, expected_corpus, expected_path in cases:
        decision = await router.decide(query)
        pred_path = decision.path
        if decision.path is Path.SEARCH_DATABASE:
            pred_corpus = decision.corpus or "clinical"
        else:
            pred_corpus = "none"

        assert pred_path == expected_path, f"Path mismatch for '{query}': expected {expected_path}, got {pred_path}"
        assert pred_corpus == expected_corpus, f"Corpus mismatch for '{query}': expected {expected_corpus}, got {pred_corpus}"


@pytest.mark.asyncio
async def test_unresolved_personal_fact_not_mere_affect():
    router = get_router("rule")
    cases = [
        (
            "I need to ask the person mentoring me now for feedback without apologizing "
            "for needing help. Can you help me draft the opening, using their name?",
            "journal",
            Path.SEARCH_DATABASE,
        ),
        (
            "Could you help me prepare one clear question for the person I report to "
            "after the reorganization, using their name so I can rehearse it?",
            "journal",
            Path.SEARCH_DATABASE,
        ),
        ("I'm stressed about my mentor.", "journal", Path.SEARCH_DATABASE),
        (
            "Can you help me draft a message because I feel small asking for feedback?",
            "none",
            Path.DIRECT_ANSWER,
        ),
        ("I need feedback at work and I am already rehearsing an apology for asking.", "none", Path.DIRECT_ANSWER),
        ("I'm dreading this trip next week.", "journal", Path.SEARCH_DATABASE),
        ("My sister has been on my case.", "journal", Path.SEARCH_DATABASE),
        ("I'm feeling anxious today.", "none", Path.DIRECT_ANSWER),
    ]
    for query, expected_corpus, expected_path in cases:
        decision = await router.decide(query)
        pred_path = decision.path
        pred_corpus = decision.corpus or "clinical" if decision.path is Path.SEARCH_DATABASE else "none"
        assert pred_path == expected_path, f"Path mismatch for '{query}': expected {expected_path}, got {pred_path}"
        assert pred_corpus == expected_corpus, f"Corpus mismatch for '{query}': expected {expected_corpus}, got {pred_corpus}"

    already_named = await router.decide(
        "Can you help me draft the opening, using their name?",
        history=[{"role": "user", "content": "Helen is the person I go to now."}],
    )
    assert already_named.path is Path.DIRECT_ANSWER
