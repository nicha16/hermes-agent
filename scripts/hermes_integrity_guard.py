#!/usr/bin/env python3
"""
hermes_integrity_guard.py — Verify critical local patches survived the Hermes update.

Designed to be run:
  1. After any `hermes update` or git pull / cutover operation
  2. Periodically via cron (silent unless a check fails)

Exit 0 = all checks pass (or silenced by configured suppression).
Exit 1 = one or more checks failed (and it will print details to stdout).
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

FILE_MUST_EXIST = [
    ("plugins/model-providers/kimi-oauth/__init__.py",
     "Kimi OAuth provider profile"),
    ("plugins/model-providers/kimi-oauth/plugin.yaml",
     "Kimi OAuth plugin definition"),
    ("scripts/check_telegram_quote_gate.sh",
     "Telegram quote pre-update gate script"),
    ("scripts/whatsapp-bridge/patches/@whiskeysockets+baileys+7.0.0-rc.9.patch",
     "WhatsApp Baileys library patch"),
    ("tests/tools/test_memory_builtin_writer_gate.py",
     "Memory writer gate regression test"),
    ("tests/hermes_cli/test_update_pre_restart_gate.py",
     "Pre-restart gate regression test"),
    ("tests/gateway/test_whatsapp_contract_drift.py",
     "WhatsApp contract drift test"),
]

CONTENT_MUST_CONTAIN = [
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


def main() -> int:
    errors: list[str] = []

    for rel_path, description in FILE_MUST_EXIST:
        errors.extend(_check_file_exists(rel_path, description))

    for rel_path, pattern, description in CONTENT_MUST_CONTAIN:
        errors.extend(_check_content(rel_path, pattern, description))

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
