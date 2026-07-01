#!/usr/bin/env bash
# Focused regression gate for Telegram quote/reply binding.
#
# Run this before merging or activating gateway changes that touch Telegram,
# reply/quote handling, or prompt injection. It intentionally stays narrow:
# exact quote preservation, quote-only prompt injection, old-message ledger
# recovery, and forum-topic root-anchor suppression.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

if [ -n "${PYTHON:-}" ]; then
  PY="$PYTHON"
elif [ -x "$REPO_ROOT/.venv/bin/python" ]; then
  PY="$REPO_ROOT/.venv/bin/python"
elif [ -x "$REPO_ROOT/venv/bin/python" ]; then
  PY="$REPO_ROOT/venv/bin/python"
else
  PY="python3"
fi

echo "▶ Telegram quote/reply regression gate"
echo "  python: $PY"

"$PY" -m py_compile \
  plugins/platforms/telegram/adapter.py \
  gateway/run.py

"$PY" -m pytest -q \
  tests/gateway/test_telegram_reply_quote.py \
  tests/gateway/test_reply_to_injection.py \
  -o 'addopts='
