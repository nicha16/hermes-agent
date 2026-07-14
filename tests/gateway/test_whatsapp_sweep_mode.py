"""Regression contract for WhatsApp bridge sweep mode."""

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BRIDGE = REPO / "scripts/whatsapp-bridge/bridge.js"


def test_sweep_mode_disabled_by_default():
    """Default bridge behaviour is unchanged always-connected mode."""
    source = BRIDGE.read_text()
    assert "const SWEEP_INTERVAL_MS = parseInt" in source
    assert "|| '0'" in source  # default is disabled


def test_sweep_mode_gates_connection_lifecycle():
    """Only locally initiated sweep closes wait for the sweep interval."""
    source = BRIDGE.read_text()
    assert "let intentionalSweepDisconnect = false" in source
    assert "const wasIntentionalSweepDisconnect = intentionalSweepDisconnect" in source
    assert "} else if (wasIntentionalSweepDisconnect)" in source
    assert "↻ Sweep complete. Reconnecting in ${SWEEP_INTERVAL_MS}ms" in source
    # Remote 428 and other transport closes retain the original quick recovery.
    assert "setTimeout(startSocket, reason === 515 ? 1000 : 3000)" in source
    assert "sweepMessagesSeen = false" in source
    assert "sweepTimer = setTimeout" in source
    assert "clearSweepTimer()" in source
    assert source.count("intentionalSweepDisconnect = true") == 2
    assert "sock.end(new Boom('Sweep window complete'" in source


def test_sweep_mode_extends_window_on_inbound_messages():
    """New inbound messages reset the sweep disconnect timer."""
    source = BRIDGE.read_text()
    assert "messages.some(m => m.message && !m.key.fromMe)" in source
    assert "sweepMessagesSeen = true" in source
