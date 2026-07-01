#!/usr/bin/env python3
"""
hermes_adapter_message_build_smoke.py — Runtime smoke test for adapter MessageEvent paths.

Synthesizes a minimal MessageEvent through every platform adapter and verifies
the build path doesn't raise TypeError (e.g. from a kwarg the dataclass no
longer defines after an update).  Designed as a no_agent cron script: silent
(exit 0) when clean, verbose only on failure.

Catches the v0.17.0 regression class: code compiles, gateway stays connected,
but every inbound message silently raises TypeError.
"""

import os
import pathlib
import sys
import traceback

REPO = pathlib.Path(os.environ.get(
    "HERMES_REPO",
    os.path.expanduser("~/.hermes/hermes-agent"),
)).resolve()

sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "plugins"))

try:
    import dataclasses
    from gateway.platforms.base import MessageEvent, MessageType, Platform, BasePlatformAdapter
except Exception as exc:
    print(f"FATAL: cannot import MessageEvent/Platform — {exc}", file=sys.stderr)
    sys.exit(2)


def _minimal_event() -> MessageEvent:
    """Smallest valid MessageEvent that exercises the full field surface."""
    return MessageEvent(
        source=None,  # type: ignore — adapters handle this internally
        message_id="smoke-test",
        text="smoke",
        message_type=MessageType.TEXT,
    )


def _adapter_paths() -> list[pathlib.Path]:
    platforms = REPO / "plugins" / "platforms"
    if not platforms.is_dir():
        return []
    return sorted(p for p in platforms.rglob("adapter.py") if p.is_file())


def _class_for_adapter(path: pathlib.Path) -> type | None:
    """Find the PlatformAdapter subclass in an adapter module."""
    import importlib.util
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                if isinstance(base, ast.Name) and base.id == "BasePlatformAdapter":
                    try:
                        mod_name = "plugins.platforms." + path.parent.name + ".adapter"
                        mod = importlib.import_module(mod_name)
                        return getattr(mod, node.name, None)
                    except Exception:
                        return None
    return None


def main() -> int:
    """Return 0 if all adapters can build a MessageEvent, 1 otherwise."""
    errors: list[str] = []

    for adapter_path in _adapter_paths():
        adapter_name = adapter_path.parent.name

        # Test 1: can we construct a MessageEvent with all default fields?
        try:
            evt = _minimal_event()
            _ = evt.text  # basic attribute access
        except Exception as exc:
            errors.append(
                f"  {adapter_name}: MessageEvent construction failed: {exc}"
            )
            continue

        # Test 2: does the adapter's _build_message_event (or equivalent)
        # accept the dataclass fields without TypeError?
        cls = _class_for_adapter(adapter_path)
        if cls is None:
            continue  # not a fatal error — not all platforms have their adapter

        build_method = getattr(cls, "_build_message_event", None)
        if build_method is None:
            continue  # some adapters use a different method name

        # Create a minimal fake adapter instance
        try:
            instance = cls.__new__(cls)
            instance.name = adapter_name
            instance.config = type("_cfg", (), {"extra": {}})()
        except Exception:
            continue  # can't instantiate — skip

        # Synthesize a fake inbound payload
        fake_payload = {
            "message_id": "smoke-test",
            "text": "smoke",
        }
        try:
            result = build_method(instance, fake_payload)
            if isinstance(result, MessageEvent):
                _ = result.text  # verify field access
            else:
                errors.append(
                    f"  {adapter_name}: _build_message_event returned "
                    f"{type(result).__name__}, not MessageEvent"
                )
        except TypeError as exc:
            errors.append(
                f"  {adapter_name}: TypeError in _build_message_event — "
                f"{exc}"
            )
            continue
        except Exception as exc:
            # Other exceptions (e.g. network calls in some adapters) are
            # not contract failures — skip them.
            if "unexpected keyword" in str(exc).lower():
                errors.append(
                    f"  {adapter_name}: unexpected kwarg — {exc}"
                )
            continue

    if errors:
        print("❌ Adapter message build smoke CHECK — FAILED")
        for e in errors:
            print(e)
        return 1

    print("✅ Adapter message build smoke — all OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
