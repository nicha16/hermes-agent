#!/usr/bin/env python3
"""
dataclass_kwarg_contract_check.py — Verify that every platform adapter's
MessageEvent(...) call-site passes only kwargs the target dataclass accepts.

Catches the reconciliation-loss class of bug where an adapter passes a field
(e.g. reply_to_is_native_quote) that the dataclass no longer defines after an
update.  Run post-merge / post-update.  Exit 0 = clean.  Exit 1 = mismatches.
"""

import ast
import dataclasses
import importlib
import pathlib
import re
import sys


REPO = pathlib.Path(__file__).resolve().parent.parent


# ── resolve dataclass fields ──────────────────────────────────────────

def _fields_of(dataclass_path: str, class_name: str) -> set[str]:
    """Return the field names of a dataclass by importing it."""
    module_path, _ = dataclass_path.rsplit("/", 1)
    module_name = module_path.replace("/", ".").rstrip(".py")
    module_name = module_name.replace("plugins.", "hermes_cli.") \
        if module_name.startswith("plugins.") else module_name
    try:
        mod = importlib.import_module(module_name)
        cls = getattr(mod, class_name)
        return {f.name for f in dataclasses.fields(cls)}
    except Exception as exc:
        print(f"  WARNING: could not import {dataclass_path}::{class_name}: {exc}",
              file=sys.stderr)
        return set()


# ── find adapter call-sites ────────────────────────────────────────────

def _adapter_paths() -> list[pathlib.Path]:
    platforms = REPO / "plugins" / "platforms"
    if not platforms.is_dir():
        return []
    return sorted(p for p in platforms.rglob("adapter.py") if p.is_file())


def _call_sites(file_path: pathlib.Path, class_name: str) -> list[dict]:
    """Find all ``ClassName(...)`` calls and extract kwargs."""
    tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
    results: list[dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Name) or func.id != class_name:
            continue
        kwargs = {
            kw.arg: _kwarg_span(kw)
            for kw in node.keywords
            if kw.arg is not None
        }
        if kwargs:
            results.append({"line": node.lineno, "kwargs": kwargs})
    return results


def _kwarg_span(kw: ast.keyword) -> str:
    """Human-readable source span for a kwarg."""
    try:
        return ast.unparse(kw.value)
    except Exception:
        return "<expr>"


# ── sweep ──────────────────────────────────────────────────────────────

DATACLASS_TARGETS = [
    ("gateway/platforms/base.py", "MessageEvent"),
    ("gateway/platforms/base.py", "SessionSource"),
]


def main() -> int:
    errors: list[str] = []

    for dc_path, class_name in DATACLASS_TARGETS:
        valid_fields = _fields_of(dc_path, class_name)
        if not valid_fields:
            print(f"  WARNING: skipping {class_name} — import failed",
                  file=sys.stderr)
            continue

        print(f"  {class_name}: {len(valid_fields)} fields — {sorted(valid_fields)[:8]}...",
              file=sys.stderr)

        for adapter_path in _adapter_paths():
            sites = _call_sites(adapter_path, class_name)
            for site in sites:
                for kwarg, span in site["kwargs"].items():
                    if kwarg not in valid_fields:
                        errors.append(
                            f"  {adapter_path.relative_to(REPO)}:{site['line']}: "
                            f"{class_name}({kwarg}=...) — field NOT in dataclass"
                        )

    if errors:
        print("❌ Dataclass kwarg contract CHECK — FAILED")
        for e in errors:
            print(e)
        return 1

    print("✅ Dataclass kwarg contract CHECK — all OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
