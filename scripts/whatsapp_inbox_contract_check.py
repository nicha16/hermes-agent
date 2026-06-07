#!/usr/bin/env python3
"""Read-only WhatsApp inbox-mode runtime contract check.

This catches the silent-failure class where WhatsApp transport health is green
but inbox monitoring coverage is broken because config intent, bridge ingress,
and gateway triage code drift apart.

No secrets or chat identifiers are printed.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
HERMES_HOME = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
CONFIG = HERMES_HOME / "config.yaml"
ENV_FILE = HERMES_HOME / ".env"
BRIDGE_LOG = HERMES_HOME / "whatsapp" / "bridge.log"
HEALTH_URL = os.environ.get("WHATSAPP_BRIDGE_HEALTH_URL", "http://127.0.0.1:3000/health")


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return None


def _load_env_flag(name: str) -> bool | None:
    if name in os.environ:
        return _coerce_bool(os.environ.get(name))
    if not ENV_FILE.exists():
        return None
    try:
        for raw in ENV_FILE.read_text(errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == name:
                return _coerce_bool(value.strip().strip('"\''))
    except OSError:
        return None
    return None


def _load_yaml_config() -> dict[str, Any]:
    if not CONFIG.exists():
        return {}
    try:
        import yaml  # type: ignore

        return yaml.safe_load(CONFIG.read_text(errors="replace")) or {}
    except Exception:
        # Fallback intentionally avoids printing config content.
        return {}


def _config_inbox_intent(config: dict[str, Any]) -> bool | None:
    values: list[bool] = []
    whatsapp = config.get("whatsapp") if isinstance(config, dict) else None
    if isinstance(whatsapp, dict):
        value = _coerce_bool(whatsapp.get("inbox_mode"))
        if value is not None:
            values.append(value)
    platforms = config.get("platforms") if isinstance(config, dict) else None
    platform_wa = platforms.get("whatsapp") if isinstance(platforms, dict) else None
    if isinstance(platform_wa, dict):
        extra = platform_wa.get("extra")
        if isinstance(extra, dict):
            value = _coerce_bool(extra.get("inbox_mode"))
            if value is not None:
                values.append(value)
    env_value = _load_env_flag("WHATSAPP_INBOX_MODE")
    if env_value is not None:
        values.append(env_value)
    if not values:
        return None
    return any(values)


def _grep(path: Path, needle: str) -> bool:
    try:
        return needle in path.read_text(errors="replace")
    except OSError:
        return False


def _bridge_health() -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=3) as resp:
            data = resp.read(64_000).decode("utf-8", "replace")
        try:
            parsed = json.loads(data)
            status = parsed.get("status")
            return status == "connected", f"status={status or 'unknown'} queue={parsed.get('queueLength', 'unknown')}"
        except json.JSONDecodeError:
            return False, "invalid_json"
    except Exception as exc:
        return False, f"unreachable:{exc.__class__.__name__}"


def _pgrep(pattern: str) -> list[str]:
    try:
        out = subprocess.check_output(["pgrep", "-af", pattern], text=True, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        return []
    return [line for line in out.splitlines() if line.strip()]


def _is_status_or_broadcast(chat_id: str | None) -> bool:
    text = str(chat_id or "").strip().lower()
    return bool(text) and (text == "status@broadcast" or text.endswith("@broadcast") or "newsletter" in text)


def _bridge_log_json(line: str) -> dict[str, Any] | None:
    start = line.find("{")
    if start == -1:
        return None
    try:
        parsed = json.loads(line[start:])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _latest_bridge_log_counts() -> dict[str, int]:
    if not BRIDGE_LOG.exists():
        return {"log_missing": 1}
    try:
        lines = BRIDGE_LOG.read_text(errors="replace").splitlines()
    except OSError:
        return {"log_unreadable": 1}
    start_idx = 0
    for idx, line in enumerate(lines):
        if "WhatsApp bridge listening" in line:
            start_idx = idx
    window = lines[start_idx:]
    counts = {
        "self_chat_rejects": 0,
        "allowlist_mismatch": 0,
        "status_or_broadcast": 0,
        "connected_markers": 0,
    }
    for line in window:
        lowered = line.lower()
        parsed = _bridge_log_json(line)
        chat_id = parsed.get("chatId") if parsed else None
        is_expected_status_drop = _is_status_or_broadcast(chat_id) or (
            "status@broadcast" in lowered or "@broadcast" in lowered or "newsletter" in lowered
        )
        if is_expected_status_drop:
            counts["status_or_broadcast"] += 1
        if "self_chat_mode_rejects_non_self" in lowered:
            if not is_expected_status_drop:
                counts["self_chat_rejects"] += 1
        if "allowlist_mismatch" in lowered:
            if not is_expected_status_drop:
                counts["allowlist_mismatch"] += 1
        if "connected" in lowered:
            counts["connected_markers"] += 1
    return counts


def main() -> int:
    failures: list[str] = []
    warnings: list[str] = []
    config = _load_yaml_config()
    inbox_intent = _config_inbox_intent(config)

    allowlist_ok = _grep(REPO / "scripts/whatsapp-bridge/allowlist.js", "shouldBypassAllowlistForInboxMode")
    bridge_ok = _grep(REPO / "scripts/whatsapp-bridge/bridge.js", "WHATSAPP_INBOX_MODE") and _grep(
        REPO / "scripts/whatsapp-bridge/bridge.js", "shouldBypassAllowlistForInboxMode"
    )
    gateway_ok = _grep(REPO / "gateway/run.py", "_forward_whatsapp_inbox_event") and _grep(
        REPO / "gateway/run.py", "_triage_whatsapp_inbox_event"
    )
    adapter_ok = _grep(REPO / "gateway/platforms/whatsapp.py", "WHATSAPP_INBOX_MODE")

    health_ok, health_summary = _bridge_health()
    gateway_procs = _pgrep(r"hermes_cli.main gateway run|hermes gateway run|gateway run --replace")
    bridge_procs = _pgrep(r"scripts/whatsapp-bridge/bridge[.]js")
    counts = _latest_bridge_log_counts()

    if inbox_intent is True:
        if not allowlist_ok:
            failures.append("missing Node allowlist inbox bypass helper")
        if not bridge_ok:
            failures.append("missing bridge WHATSAPP_INBOX_MODE bypass wiring")
        if not gateway_ok:
            failures.append("missing Python gateway inbox triage/forwarding path")
        if not adapter_ok:
            failures.append("missing adapter-to-bridge WHATSAPP_INBOX_MODE env propagation")
        if not health_ok:
            failures.append(f"bridge health not connected ({health_summary})")
        if not gateway_procs:
            failures.append("gateway process not found")
        if not bridge_procs:
            failures.append("bridge process not found")
        if counts.get("self_chat_rejects", 0) > 0 or counts.get("allowlist_mismatch", 0) > 0:
            failures.append(
                "latest bridge-start window contains inbox-breaking reject evidence "
                f"(self_chat={counts.get('self_chat_rejects', 0)}, allowlist={counts.get('allowlist_mismatch', 0)})"
            )
    elif inbox_intent is False:
        warnings.append("WhatsApp inbox intent is explicitly false; inbox coverage checks skipped")
    else:
        warnings.append("WhatsApp inbox intent not found; inbox coverage checks skipped")

    print("WhatsApp inbox runtime contract check")
    print(f"intent_inbox_mode={inbox_intent}")
    print(f"bridge_health={health_summary}")
    print(f"gateway_processes={len(gateway_procs)} bridge_processes={len(bridge_procs)}")
    print(
        "code_contract="
        f"allowlist:{allowlist_ok} bridge:{bridge_ok} gateway:{gateway_ok} adapter_env:{adapter_ok}"
    )
    print(
        "latest_bridge_window="
        f"self_chat_rejects:{counts.get('self_chat_rejects', 0)} "
        f"allowlist_mismatch:{counts.get('allowlist_mismatch', 0)} "
        f"status_or_broadcast:{counts.get('status_or_broadcast', 0)}"
    )
    for warning in warnings:
        print(f"WARN: {warning}")
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 2
    print("OK: WhatsApp inbox runtime contract holds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
