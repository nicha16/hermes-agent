import pytest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.base import MessageEvent, MessageType
from gateway.run import GatewayRunner
from gateway.session import SessionSource
from hermes_cli import goals


class _FakeSessionEntry:
    session_id = "sid-gateway-goal-config"


class _FakeSessionStore:
    def __init__(self):
        self.entry = _FakeSessionEntry()

    def get_or_create_session(self, source):
        return self.entry

    def _generate_session_key(self, source):
        return "agent:main:discord:channel:goal-config"


@pytest.mark.asyncio
async def test_gateway_goal_uses_goals_max_turns_from_full_config(tmp_path, monkeypatch):
    """Gateway /goal should honor top-level goals.max_turns from config.yaml."""
    home = tmp_path / ".hermes"
    home.mkdir()
    (home / "config.yaml").write_text("goals:\n  max_turns: 7\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))
    goals._DB_CACHE.clear()

    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(
        platforms={Platform.DISCORD: PlatformConfig(enabled=True, token="token")}
    )
    runner.session_store = _FakeSessionStore()
    runner.adapters = {}
    runner._queued_events = {}

    event = MessageEvent(
        text="/goal ship the benchmark",
        message_type=MessageType.TEXT,
        source=SessionSource(
            platform=Platform.DISCORD,
            chat_id="chat-goal-config",
            chat_type="channel",
            user_id="user-goal-config",
        ),
        message_id="msg-goal-config",
    )

    response = await GatewayRunner._handle_goal_command(runner, event)

    try:
        assert "⊙ Goal set (7-turn budget): ship the benchmark" in response
        state = goals.GoalManager("sid-gateway-goal-config").state
        assert state is not None
        assert state.max_turns == 7
    finally:
        goals._DB_CACHE.clear()


@pytest.mark.asyncio
async def test_gateway_goal_kickoff_preserves_reply_context(tmp_path, monkeypatch):
    """/goal sent as a Telegram reply/quote must preserve reply context in the queued kickoff."""
    home = tmp_path / ".hermes"
    home.mkdir()
    (home / "config.yaml").write_text("goals:\n  max_turns: 5\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))
    goals._DB_CACHE.clear()

    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(
        platforms={Platform.DISCORD: PlatformConfig(enabled=True, token="token")}
    )
    runner.session_store = _FakeSessionStore()
    runner.adapters = {}
    runner._queued_events = {}

    import types
    fake_adapter = types.SimpleNamespace()
    fake_adapter._pending_messages = {}
    runner.adapters = {Platform.DISCORD: fake_adapter}

    event = MessageEvent(
        text="/goal identify the fix",
        message_type=MessageType.TEXT,
        source=SessionSource(
            platform=Platform.DISCORD,
            chat_id="chat-goal-quote",
            chat_type="channel",
            user_id="user-quote",
        ),
        message_id="msg-goal-reply",
        reply_to_message_id="msg-prior",
        reply_to_text="investigate the root cause",
        raw_message="{'quote': 'investigate the root cause'}",
    )

    try:
        response = await GatewayRunner._handle_goal_command(runner, event)

        # The kickoff must be enqueued via _enqueue_fifo.
        # Since no pending slot exists for this session_key, it goes
        # directly into adapter._pending_messages.
        assert "agent:main:discord:channel:goal-config" in fake_adapter._pending_messages, \
            "kickoff should be enqueued in adapter._pending_messages"
        kickoff = fake_adapter._pending_messages["agent:main:discord:channel:goal-config"]

        # The dataclasses.replace must preserve the reply context.
        assert kickoff.reply_to_text == "investigate the root cause", \
            f"Expected reply_to_text='investigate the root cause', got {kickoff.reply_to_text!r}"
        assert kickoff.reply_to_message_id == "msg-prior", \
            f"Expected reply_to_message_id='msg-prior', got {kickoff.reply_to_message_id!r}"
        assert kickoff.raw_message == "{'quote': 'investigate the root cause'}", \
            f"Expected raw_message preserved, got {kickoff.raw_message!r}"

        # The goal text must replace the original text.
        assert kickoff.text == "identify the fix", \
            f"Expected text='identify the fix', got {kickoff.text!r}"
    finally:
        goals._DB_CACHE.clear()
