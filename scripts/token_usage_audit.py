#!/usr/bin/env python3
"""Read-only Hermes token usage audit.

Summarizes token accounting and context-bloat metadata without printing
message/tool contents or secrets. Intended for local operational review.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


TOKEN_COLS = (
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
)


@dataclass
class SessionFileSummary:
    session_id: str
    path: Path | None
    file_bytes: int = 0
    system_prompt_chars: int = 0
    message_count: int = 0
    role_counts: dict[str, int] | None = None
    role_chars: dict[str, int] | None = None
    tool_chars_by_name: dict[str, int] | None = None
    tool_counts_by_name: dict[str, int] | None = None
    tool_max_by_name: dict[str, int] | None = None
    large_tool_outputs: list[tuple[int, str]] | None = None
    error: str | None = None


def hermes_home() -> Path:
    try:
        from hermes_constants import get_hermes_home

        return Path(get_hermes_home())
    except Exception:
        return Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))


def fmt_int(value: int | float | None) -> str:
    return f"{int(value or 0):,}"


def fmt_pct(part: int | float | None, total: int | float | None) -> str:
    total = total or 0
    if total <= 0:
        return "0.0%"
    return f"{(float(part or 0) / float(total)) * 100:.1f}%"


def dt(ts: float | None) -> str:
    if not ts:
        return "-"
    return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")


def total_expr() -> str:
    return " + ".join(f"coalesce({c},0)" for c in TOKEN_COLS)


def row_total(row: sqlite3.Row | dict[str, Any]) -> int:
    return int(sum(row[c] or 0 for c in TOKEN_COLS))


def connect_state_db(home: Path) -> sqlite3.Connection:
    db = home / "state.db"
    if not db.exists():
        raise SystemExit(f"state.db not found: {db}")
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    return con


def load_session_json(path: Path) -> dict[str, Any]:
    text = path.read_text(errors="ignore")
    try:
        return json.loads(text)
    except Exception:
        # Some historical artifacts may be JSONL. Keep only structured metadata.
        messages: list[dict[str, Any]] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if isinstance(obj, dict):
                messages.append(obj)
        return {"messages": messages}


def content_len(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value)
    try:
        return len(json.dumps(value, ensure_ascii=False))
    except Exception:
        return len(repr(value))


def find_session_file(home: Path, session_id: str) -> Path | None:
    sessions_dir = home / "sessions"
    exact = sessions_dir / f"session_{session_id}.json"
    if exact.exists():
        return exact
    matches = sorted(sessions_dir.glob(f"*{session_id}*.json"))
    return matches[0] if matches else None


def tool_call_name_map(messages: Iterable[dict[str, Any]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        for tc in msg.get("tool_calls") or []:
            if not isinstance(tc, dict):
                continue
            tid = tc.get("id")
            fn = (tc.get("function") or {}).get("name") or tc.get("name") or ""
            if tid and fn:
                mapping[str(tid)] = str(fn)
    return mapping


def summarize_session_file(home: Path, session_id: str, large_threshold: int) -> SessionFileSummary:
    path = find_session_file(home, session_id)
    if path is None:
        return SessionFileSummary(session_id=session_id, path=None, error="session file not found")
    try:
        data = load_session_json(path)
    except Exception as exc:
        return SessionFileSummary(session_id=session_id, path=path, error=f"parse error: {exc}")

    messages = data.get("messages") or data.get("conversation_history") or []
    if not isinstance(messages, list):
        messages = []
    messages = [m for m in messages if isinstance(m, dict)]
    system_prompt = data.get("system_prompt") or data.get("system_message") or ""
    id_to_tool = tool_call_name_map(messages)

    role_counts: collections.Counter[str] = collections.Counter()
    role_chars: collections.Counter[str] = collections.Counter()
    tool_chars: collections.Counter[str] = collections.Counter()
    tool_counts: collections.Counter[str] = collections.Counter()
    tool_max: dict[str, int] = collections.defaultdict(int)
    large: list[tuple[int, str]] = []

    for msg in messages:
        role = str(msg.get("role") or "?")
        size = content_len(msg.get("content"))
        role_counts[role] += 1
        role_chars[role] += size
        if role == "tool":
            name = str(msg.get("name") or id_to_tool.get(str(msg.get("tool_call_id"))) or "(unknown)")
            tool_chars[name] += size
            tool_counts[name] += 1
            tool_max[name] = max(tool_max[name], size)
            if size >= large_threshold:
                large.append((size, name))

    return SessionFileSummary(
        session_id=session_id,
        path=path,
        file_bytes=path.stat().st_size,
        system_prompt_chars=len(system_prompt) if isinstance(system_prompt, str) else content_len(system_prompt),
        message_count=len(messages),
        role_counts=dict(role_counts),
        role_chars=dict(role_chars),
        tool_chars_by_name=dict(tool_chars),
        tool_counts_by_name=dict(tool_counts),
        tool_max_by_name=dict(tool_max),
        large_tool_outputs=sorted(large, reverse=True)[:10],
    )


def print_totals(con: sqlite3.Connection, since: float, label: str) -> None:
    expr = total_expr()
    row = con.execute(
        f"""
        select
          count(*) sessions,
          sum(coalesce(message_count,0)) messages,
          sum(coalesce(tool_call_count,0)) tool_calls,
          sum(coalesce(api_call_count,0)) api_calls,
          sum(coalesce(input_tokens,0)) input_tokens,
          sum(coalesce(output_tokens,0)) output_tokens,
          sum(coalesce(cache_read_tokens,0)) cache_read_tokens,
          sum(coalesce(cache_write_tokens,0)) cache_write_tokens,
          sum(coalesce(reasoning_tokens,0)) reasoning_tokens,
          sum({expr}) total_tokens
        from sessions where started_at >= ?
        """,
        (since,),
    ).fetchone()
    total = int(row["total_tokens"] or 0)
    print(f"\n## Totals — {label}")
    print(f"sessions: {fmt_int(row['sessions'])}; messages: {fmt_int(row['messages'])}; tool_calls: {fmt_int(row['tool_calls'])}; api_calls: {fmt_int(row['api_calls'])}")
    for col, name in [
        ("input_tokens", "fresh_input"),
        ("output_tokens", "output"),
        ("cache_read_tokens", "cache_read"),
        ("cache_write_tokens", "cache_write"),
        ("reasoning_tokens", "reasoning"),
    ]:
        print(f"{name}: {fmt_int(row[col])} ({fmt_pct(row[col], total)})")
    print(f"total_reported: {fmt_int(total)}")


def print_by_source(con: sqlite3.Connection, since: float, label: str, limit: int) -> None:
    expr = total_expr()
    rows = con.execute(
        f"""
        select source, model, billing_provider,
          count(*) sessions,
          sum(coalesce(message_count,0)) messages,
          sum(coalesce(tool_call_count,0)) tool_calls,
          sum(coalesce(api_call_count,0)) api_calls,
          sum(coalesce(input_tokens,0)) input_tokens,
          sum(coalesce(output_tokens,0)) output_tokens,
          sum(coalesce(cache_read_tokens,0)) cache_read_tokens,
          sum(coalesce(cache_write_tokens,0)) cache_write_tokens,
          sum(coalesce(reasoning_tokens,0)) reasoning_tokens,
          sum({expr}) total_tokens
        from sessions where started_at >= ?
        group by source, model, billing_provider
        order by total_tokens desc
        limit ?
        """,
        (since, limit),
    ).fetchall()
    print(f"\n## By source/model/provider — {label}")
    for r in rows:
        total = int(r["total_tokens"] or 0)
        print(
            f"- source={r['source'] or '-'} model={r['model'] or '-'} provider={r['billing_provider'] or '-'}; "
            f"sessions={fmt_int(r['sessions'])}; api_calls={fmt_int(r['api_calls'])}; "
            f"total={fmt_int(total)}; fresh={fmt_int(r['input_tokens'])} ({fmt_pct(r['input_tokens'], total)}); "
            f"cache={fmt_int(r['cache_read_tokens'])} ({fmt_pct(r['cache_read_tokens'], total)})"
        )


def print_top_sessions(con: sqlite3.Connection, home: Path, since: float, label: str, limit: int, large_threshold: int) -> None:
    expr = total_expr()
    rows = con.execute(
        f"""
        select id, source, model, billing_provider, title, started_at, ended_at,
          message_count, tool_call_count, api_call_count,
          input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, reasoning_tokens,
          {expr} as total_tokens,
          length(coalesce(system_prompt,'')) as db_system_prompt_chars
        from sessions where started_at >= ?
        order by total_tokens desc
        limit ?
        """,
        (since, limit),
    ).fetchall()
    print(f"\n## Top sessions by reported total — {label}")
    for r in rows:
        s = summarize_session_file(home, r["id"], large_threshold)
        title = (r["title"] or "")[:80]
        print(
            f"- {r['id']} source={r['source']} title={title!r}; started={dt(r['started_at'])}; "
            f"api_calls={fmt_int(r['api_call_count'])}; total={fmt_int(r['total_tokens'])}; "
            f"fresh={fmt_int(r['input_tokens'])}; cache={fmt_int(r['cache_read_tokens'])}; "
            f"system_chars={fmt_int(s.system_prompt_chars or r['db_system_prompt_chars'])}; "
            f"file_bytes={fmt_int(s.file_bytes)}"
        )
        if s.tool_chars_by_name:
            top_tools = sorted(s.tool_chars_by_name.items(), key=lambda kv: kv[1], reverse=True)[:5]
            tool_bits = []
            for name, chars in top_tools:
                calls = (s.tool_counts_by_name or {}).get(name, 0)
                mx = (s.tool_max_by_name or {}).get(name, 0)
                tool_bits.append(f"{name}: chars={fmt_int(chars)}, calls={calls}, max={fmt_int(mx)}")
            print("  top_tool_output: " + "; ".join(tool_bits))
        elif s.error:
            print(f"  session_file_note: {s.error}")


def print_top_cron(con: sqlite3.Connection, home: Path, since: float, label: str, limit: int, large_threshold: int) -> None:
    rows = con.execute(
        f"""
        select id, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
          reasoning_tokens, api_call_count
        from sessions
        where started_at >= ? and source = 'cron'
        """,
        (since,),
    ).fetchall()
    agg: dict[str, dict[str, Any]] = {}
    for r in rows:
        match = re.match(r"cron_([a-f0-9]+)_", r["id"] or "")
        job_id = match.group(1) if match else "(unknown)"
        a = agg.setdefault(
            job_id,
            {
                "runs": 0,
                "api_calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "reasoning_tokens": 0,
                "total_tokens": 0,
                "session_file_bytes": 0,
                "user_chars": 0,
                "tool_chars": 0,
                "max_tool_output": 0,
                "example_session": r["id"],
            },
        )
        a["runs"] += 1
        a["api_calls"] += int(r["api_call_count"] or 0)
        for col in TOKEN_COLS:
            a[col] += int(r[col] or 0)
        a["total_tokens"] += row_total(r)
        s = summarize_session_file(home, r["id"], large_threshold)
        a["session_file_bytes"] += s.file_bytes
        if s.role_chars:
            a["user_chars"] += int(s.role_chars.get("user", 0))
            a["tool_chars"] += int(s.role_chars.get("tool", 0))
        if s.tool_max_by_name:
            a["max_tool_output"] = max(a["max_tool_output"], max(s.tool_max_by_name.values()))

    print(f"\n## Top cron jobs by aggregate reported total — {label}")
    for job_id, a in sorted(agg.items(), key=lambda kv: kv[1]["total_tokens"], reverse=True)[:limit]:
        total = a["total_tokens"]
        avg_total = int(total / a["runs"]) if a["runs"] else 0
        avg_api = a["api_calls"] / a["runs"] if a["runs"] else 0
        print(
            f"- job_id={job_id}; runs={a['runs']}; api_calls={a['api_calls']} (avg={avg_api:.1f}/run); "
            f"total={fmt_int(total)} (avg={fmt_int(avg_total)}/run); "
            f"fresh={fmt_int(a['input_tokens'])}; cache={fmt_int(a['cache_read_tokens'])}; "
            f"user_chars={fmt_int(a['user_chars'])}; tool_chars={fmt_int(a['tool_chars'])}; "
            f"max_tool_output={fmt_int(a['max_tool_output'])}; example={a['example_session']}"
        )


def print_tool_schema_baseline(platforms: list[str]) -> None:
    print("\n## Effective platform toolsets and schema size")
    try:
        from hermes_cli.config import load_config
        from hermes_cli.tools_config import _get_platform_tools
        from model_tools import get_tool_definitions
    except Exception as exc:
        print(f"tool_schema_note: unavailable: {exc}")
        return

    try:
        cfg = load_config()
    except Exception as exc:
        print(f"tool_schema_note: config load failed: {exc}")
        return

    for platform in platforms:
        try:
            enabled = sorted(_get_platform_tools(cfg, platform))
            tools = get_tool_definitions(enabled_toolsets=enabled, quiet_mode=True)
            schema_chars = len(json.dumps(tools, ensure_ascii=False, separators=(",", ":")))
            names = [t.get("function", {}).get("name", "?") for t in tools]
            print(
                f"- platform={platform}; enabled_toolsets={enabled}; "
                f"tools={len(tools)}; schema_chars={fmt_int(schema_chars)}; "
                f"largest_tools={top_schema_tools(tools)}"
            )
            print(f"  tool_names={names}")
        except Exception as exc:
            print(f"- platform={platform}; error={exc}")


def top_schema_tools(tools: list[dict[str, Any]], limit: int = 8) -> str:
    pairs = []
    for t in tools:
        name = t.get("function", {}).get("name", "?")
        chars = len(json.dumps(t, ensure_ascii=False, separators=(",", ":")))
        pairs.append((chars, name))
    return ", ".join(f"{name}:{fmt_int(chars)}" for chars, name in sorted(pairs, reverse=True)[:limit])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Hermes token usage audit")
    parser.add_argument("--days", type=float, action="append", default=None, help="Window in days; repeatable. Default: 1 and 7")
    parser.add_argument("--top", type=int, default=10, help="Top N rows per section")
    parser.add_argument("--large-threshold", type=int, default=10000, help="Large tool output threshold in chars")
    parser.add_argument("--platform", action="append", default=None, help="Platform to include in schema audit; repeatable")
    args = parser.parse_args(argv)

    home = hermes_home()
    days_values = args.days or [1, 7]
    platforms = args.platform or ["telegram", "cron", "cli"]
    now = time.time()

    print("# Hermes Token Usage Audit")
    print(f"generated_at: {datetime.fromtimestamp(now).isoformat(timespec='seconds')}")
    print(f"hermes_home: {home}")
    print("privacy: metadata only; message/tool contents are not printed")

    con = connect_state_db(home)
    try:
        for days in days_values:
            label = f"last {days:g}d"
            since = now - (days * 86400)
            print_totals(con, since, label)
            print_by_source(con, since, label, args.top)
            print_top_sessions(con, home, since, label, args.top, args.large_threshold)
            print_top_cron(con, home, since, label, args.top, args.large_threshold)
        print_tool_schema_baseline(platforms)
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
