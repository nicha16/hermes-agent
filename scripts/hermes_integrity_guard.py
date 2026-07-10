#!/usr/bin/env python3
"""
hermes_integrity_guard.py — Verify critical local patches survived the Hermes update.

███ REGISTERING NEW PATCHES — READ THIS ███

Whenever you (Keira) apply a local-only patch to the Hermes source tree,
add its file path and a unique content marker below BEFORE committing.
Two sections:

  FILE_MUST_EXIST        — files that must be physically present
  CONTENT_MUST_CONTAIN    — files that must contain a specific pattern

Each entry is (relative_path, regex_or_None, human_description).
Choose a regex that is:
  • Specific to your patch (not something upstream also has)
  • Stable across minor edits (not line numbers)
  • A literal string if possible (e.g., a unique function name or comment)

Use the ``# ── add new checks here ──`` markers as insertion points.
Failure mode: any unregistered patch will be silently lost in the next
update.  The post-merge hook runs this automatically after every
``hermes update`` / ``git pull``.

Exit 0 = passes.  Exit 1 = failures (reported to stdout during update).
"""

import os
import re
import sys
import pathlib

REPO = pathlib.Path(os.environ.get(
    "HERMES_REPO",
    os.path.expanduser("~/.hermes/hermes-agent"),
)).resolve()

# ── Checks ──────────────────────────────────────────────────────────────
# FILE_MUST_EXIST:  (relative_path, description)
# CONTENT_MUST_CONTAIN:  (relative_path, regex_pattern, description)
# TEST_MUST_PASS:  (relative_test_path, description)
#   These tests are run with pytest. A failure here means the code they
#   test was lost even though the test file survived — the guard would
#   have passed on file-existence alone, giving false confidence.

FILE_MUST_EXIST = [
    # ── add new file-existence checks here ───────────────────────────────
    ("plugins/model-providers/kimi-oauth/__init__.py",
     "Kimi OAuth provider profile"),
    ("plugins/model-providers/kimi-oauth/plugin.yaml",
     "Kimi OAuth plugin definition"),
    ("scripts/check_telegram_quote_gate.sh",
     "Telegram quote pre-update gate script"),
    ("scripts/whatsapp-bridge/patches/@whiskeysockets+baileys+7.0.0-rc13.patch",
     "WhatsApp Baileys rc13 atomic-auth patch"),
    ("scripts/whatsapp-bridge/atomic-auth-write.test.mjs",
     "WhatsApp Baileys atomic-auth regression test"),
]

TEST_MUST_PASS = [
    # ── add new test-run checks here ─────────────────────────────────────
    ("tests/hermes_cli/test_update_pre_restart_gate.py",
     "Pre-restart gate regression test"),
    ("tests/gateway/test_whatsapp_contract_drift.py",
     "WhatsApp contract drift test"),
    ("tests/tools/test_memory_builtin_writer_gate.py",
     "Memory writer gate regression test"),
    ("tests/hermes_cli/test_model_switch_session_scoped.py",
     "Session-scoped /model default regression test"),
]

CONTENT_MUST_CONTAIN = [
    # ── add new content checks here ──────────────────────────────────────
    # Format: ("relative/path.py", r"unique_regex_pattern", "description"),
    # MCP reconnect retry — continuous retry, not park
    ("tools/mcp_tool.py",
     r"self\._mark_connected\(\)",
     "MCP reconnect retry (_mark_connected)"),
    ("tools/mcp_tool.py",
     r"_register_discovered_tools_if_needed",
     "MCP tool re-registration after reconnect"),
    # Telegram quote context — MessageLedger
    ("plugins/platforms/telegram/adapter.py",
     r"class TelegramMessageLedger",
     "Telegram message ledger for quote recovery"),
    ("plugins/platforms/telegram/adapter.py",
     r"self\._message_ledger",
     "Telegram adapter ledger init"),
    # Codex SDK output=None monkey-patch
    ("agent/codex_responses_adapter.py",
     r"__hermes_codex_guard__",
     "Codex SDK output=None monkey-patch"),
    # Built-in memory writer gate
    ("tools/memory_tool.py",
     r"builtin_writer_enabled",
     "Memory writer source gate"),
    ("hermes_cli/config.py",
     r"builtin_writer_enabled",
     "Memory writer config default"),
    # Reasoning effort max
    ("hermes_constants.py",
     r'"max"',
     "VALID_REASONING_EFFORTS includes max"),
    # Gateway goal reply context (in slash_commands.py)
    ("gateway/slash_commands.py",
     r"dataclasses\.replace.*event",
     "Gateway goal reply context"),
    # Telegram streaming opt-in
    ("plugins/platforms/telegram/adapter.py",
     r"streaming",
     "Telegram streaming opt-in"),
    # Session-scoped /model default (Nicha policy 2026-07-01) — upstream ships True
    ("hermes_cli/model_switch.py",
     r'persist_switch_by_default", False',
     "session-scoped /model default (built-in False)"),
    # WhatsApp Baileys auth-state durability
    ("scripts/whatsapp-bridge/package.json",
     r'"postinstall": "patch-package"',
     "Baileys atomic-auth patch is re-applied after npm install"),
    ("scripts/whatsapp-bridge/patches/@whiskeysockets+baileys+7.0.0-rc13.patch",
     r"await rename\(tmpPath, filePath\);",
     "Baileys auth writes atomically replace the credentials file"),
    # ── add new content checks above this line ──────────────────────────────
    # ── cross-file dataclass contract ───────────────────────────────────────
    # reply_to_is_native_quote must exist in base.py MessageEvent dataclass
    # because plugins/platforms/telegram/adapter.py passes it as a kwarg.
    # Removal causes TypeError on every inbound Telegram message.
    ("gateway/platforms/base.py",
     r"reply_to_is_native_quote",
     "reply_to_is_native_quote field in MessageEvent"),
    # dataclass kwarg contract checker must be present
    ("scripts/dataclass_kwarg_contract_check.py",
     r"MessageEvent",
     "dataclass kwarg contract checker"),
]


def _check_file_exists(rel_path: str, description: str) -> list[str]:
    full = REPO / rel_path
    if not full.exists():
        return [f"  FILE MISSING: {rel_path}  ({description})"]
    if not full.is_file():
        return [f"  NOT A FILE: {rel_path}  ({description})"]
    return []


def _check_content(rel_path: str, pattern: str, description: str) -> list[str]:
    full = REPO / rel_path
    if not full.exists():
        return [f"  FILE MISSING (can't check content): {rel_path}  ({description})"]
    try:
        text = full.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return [f"  CANNOT READ: {rel_path} — {exc}  ({description})"]

    if not re.search(pattern, text):
        return [f"  PATTERN NOT FOUND: /{pattern}/ in {rel_path}  ({description})"]
    return []


def _silence_file() -> pathlib.Path:
    return REPO / "var" / "integrity_suppressed"


def _check_tests_pass(rel_path: str, description: str) -> list[str]:
    """Run a pytest file, return error lines if any test fails."""
    import subprocess
    test_path = REPO / rel_path
    if not test_path.exists():
        return [f"  TEST FILE MISSING: {rel_path}  ({description})"]
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(test_path), "-q", "--no-header"],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            timeout=60,
        )
    except Exception as exc:
        return [f"  TEST RUN FAILED: {rel_path} — {exc}  ({description})"]
    if result.returncode != 0:
        # Return the pytest output (last few lines) for diagnosis
        lines = result.stdout.strip().split("\n")
        summary = lines[-5:] if len(lines) > 5 else lines
        return [
            f"  TEST FAILED: {rel_path}  ({description})",
            *[f"    {line}" for line in summary],
        ]
    return []


def main() -> int:
    errors: list[str] = []

    for rel_path, description in FILE_MUST_EXIST:
        errors.extend(_check_file_exists(rel_path, description))

    for rel_path, pattern, description in CONTENT_MUST_CONTAIN:
        errors.extend(_check_content(rel_path, pattern, description))

    for rel_path, description in TEST_MUST_PASS:
        errors.extend(_check_tests_pass(rel_path, description))

    if errors:
        silence = _silence_file()
        if silence.exists():
            log = REPO / "var" / "integrity_guard.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text("\n".join(errors) + "\n", encoding="utf-8")
            return 0

        print("🛡️  Hermes integrity guard — FAILED")
        print(f"  Repo: {REPO}")
        print(f"  Touch {_silence_file()} to suppress future alerts.")
        for e in errors:
            print(e)
        return 1

    print("🛡️  Hermes integrity guard — all OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
