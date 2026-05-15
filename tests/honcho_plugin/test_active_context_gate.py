"""Regression tests for Honcho automatic context authority gating."""

from plugins.memory.honcho import HonchoMemoryProvider


def test_base_context_gate_disabled_preserves_raw_context():
    provider = HonchoMemoryProvider()
    provider._active_context_gate = False

    raw = provider._format_first_turn_context(
        {
            "summary": "Old session summary about WhatsApp JSON triage.",
            "representation": "- User asked: Do it next.\n- WhatsApp triage output must be JSON only.",
            "card": "Approval before live restarts.\nUser prefers concise direct answers.",
        },
        query="Current Honcho memory debugging turn",
    )

    assert "## User Representation" in raw
    assert "WhatsApp triage output must be JSON only" in raw
    assert "Do it next" in raw


def test_base_context_gate_builds_authority_scoped_brief_and_quarantines_stale_rows():
    provider = HonchoMemoryProvider()
    provider._active_context_gate = True

    gated = provider._format_first_turn_context(
        {
            "summary": "Old session summary: user said Do it; next step was WhatsApp JSON triage.",
            "representation": """
- Approval before live writes/restarts.
- User expects rich PA lookaround and adjacent context.
- WhatsApp triage must return JSON only with priority/summary/action_needed.
- Random third-party remark: Bob's luggage was delayed.
- Debug diary: next step is restart old service.
""",
            "card": """
Privacy: do not expose secrets or exact chat IDs.
Wiki/session recall: when Nicha names an entity/project/open loop, proactively search wiki/session.
""",
        },
        query="Let's try this Honcho context authority gate",
    )

    assert "## PA Situation Brief" in gated
    assert "### Standing operating kernel" in gated
    assert "Approval before live writes/restarts" in gated
    assert "do not expose secrets" in gated
    assert "rich PA lookaround" in gated
    assert "### Quarantined recalled context" in gated

    assert "## User Representation" not in gated
    assert "WhatsApp triage must return JSON only" not in gated
    assert "Bob's luggage" not in gated
    assert "next step is restart old service" not in gated
    assert "user said Do it" not in gated


def test_base_context_gate_adds_canonical_recall_trigger_for_named_open_loops():
    provider = HonchoMemoryProvider()
    provider._active_context_gate = True

    gated = provider._format_first_turn_context(
        {"card": "User prefers concise direct answers."},
        query="What is the Danista open question?",
    )

    assert "### Canonical recall trigger" in gated
    assert "wiki/session" in gated
    assert "answered-vs-open" in gated


def test_dialectic_gate_suppresses_ungrounded_most_relevant_active_context():
    provider = HonchoMemoryProvider()
    provider._active_context_gate = True

    dialectic = """
Most relevant active context for this session:

- They want context grounded in the current thread, not just biography.
- The immediate thread context is about Ash Sethi and meeting/logistics:
  - heating/cooling setup in the Gers
  - whether the meeting is at the user's house or in town
  - whether there's a particular cuisine they're hungry for
"""

    gated = provider._format_dialectic_context(
        dialectic,
        query="The gateway has been restarted",
    )

    assert "Most relevant active context" not in gated
    assert "Ash Sethi" not in gated
    assert "heating/cooling" not in gated
    assert "Gers" not in gated
    assert "Quarantined recalled context" in gated


def test_base_context_gate_quarantines_long_narrative_even_with_standing_keywords():
    provider = HonchoMemoryProvider()
    provider._active_context_gate = True

    gated = provider._format_first_turn_context(
        {
            "card": "Approval before live writes/restarts.",
            "summary": (
                "Keira then checked the Honcho documentation and discussed approval, "
                "current-vs-stale authority, wiki/session recall, token limits, prior "
                "operator decisions, and a long historical debugging narrative that "
                "should remain searchable but must not become standing operating policy."
            ),
        },
        query="Audit performance regressions and propose highest leverage fix",
    )

    assert "Approval before live writes/restarts" in gated
    assert "Keira then checked" not in gated
    assert "long historical debugging narrative" not in gated
    assert "Quarantined recalled context" in gated


def test_base_context_gate_truncates_admitted_lines_and_caps_total_brief():
    provider = HonchoMemoryProvider()
    provider._active_context_gate = True

    very_long_policy = "Privacy: do not expose secrets or credentials. " + ("extra detail " * 80)

    gated = provider._format_first_turn_context(
        {
            "card": "\n".join([very_long_policy] * 12),
            "representation": "User expects rich PA lookaround and adjacent context.\n" * 8,
        },
        query="Debug current Hermes performance",
    )

    assert len(gated) <= provider._AUTHORITY_BRIEF_MAX_CHARS + len(" …")
    for line in gated.splitlines():
        if line.startswith("- ") and "Privacy:" in line:
            assert len(line) <= provider._AUTHORITY_LINE_MAX_CHARS + len("-  …")
