"""WhatsApp drift contract tests — run before cutover activation.

Asserts all six code layers that constitute Nicha's WhatsApp inbox/send
deployment are present on disk.  Missing layers after a reconciliation
or upstream cutover silently break inbox triage or outbound sending
while bridge /health stays green.

These are code-presence checks, not runtime behaviour tests.  Keep them
fast (<1 s total) and colocated with the focused WhatsApp suite for
pre-cutover runs.
"""

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _assert_text_in_file(path: str, needle: str) -> None:
    filepath = REPO / path
    text = filepath.read_text(errors="replace")
    assert needle in text, f"Missing expected text in {path}: {needle!r}"


# ---------------------------------------------------------------------------
# Inbox triage layers (bridge ingress)
# ---------------------------------------------------------------------------


def test_allowlist_inbox_bypass_present():
    """Node allowlist.js has shouldBypassAllowlistForInboxMode helper."""
    _assert_text_in_file(
        "scripts/whatsapp-bridge/allowlist.js",
        "shouldBypassAllowlistForInboxMode",
    )


def test_bridge_inbox_wiring_present():
    """Node bridge.js wires WHATSAPP_INBOX_MODE and calls the bypass helper."""
    f = "scripts/whatsapp-bridge/bridge.js"
    text = (REPO / f).read_text(errors="replace")
    assert "WHATSAPP_INBOX_MODE" in text, f"Missing WHATSAPP_INBOX_MODE in {f}"
    assert "shouldBypassAllowlistForInboxMode" in text, (
        f"Missing shouldBypassAllowlistForInboxMode call in {f}"
    )


def test_gateway_inbox_triage_present():
    """Python gateway/run.py has inbox forwarding + triage functions."""
    f = "gateway/run.py"
    text = (REPO / f).read_text(errors="replace")
    assert "_forward_whatsapp_inbox_event" in text, (
        f"Missing _forward_whatsapp_inbox_event in {f}"
    )
    assert "_triage_whatsapp_inbox_event" in text, (
        f"Missing _triage_whatsapp_inbox_event in {f}"
    )


def test_adapter_env_propagation_present():
    """Python whatsapp.py passes WHATSAPP_INBOX_MODE to the bridge subprocess."""
    _assert_text_in_file(
        "plugins/platforms/whatsapp/adapter.py",
        "WHATSAPP_INBOX_MODE",
    )


# ---------------------------------------------------------------------------
# Channel directory layer (contact discovery)
# ---------------------------------------------------------------------------


def test_channel_directory_lid_mapping_present():
    """channel_directory.py has _build_whatsapp_from_lid_mappings."""
    _assert_text_in_file(
        "gateway/channel_directory.py",
        "_build_whatsapp_from_lid_mappings",
    )


# ---------------------------------------------------------------------------
# Send-path layer (outbound JID resolution)
# ---------------------------------------------------------------------------


def test_send_message_jid_resolution_present():
    """send_message_tool.py accepts raw WhatsApp JIDs for outbound send."""
    _assert_text_in_file(
        "tools/send_message_tool.py",
        '"whatsapp" and "@" in target_ref',
    )
