"""
Discord Tools Plugin — read messages by ID, fetch with timestamp ranges.

Uses the existing DISCORD_BOT_TOKEN from the Hermes environment.
Adds 'discord_read_message' tool to the 'discord' toolset.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any


DISCORD_API = "https://discord.com/api/v10"
DISCORD_EPOCH = 1420070400000  # ms since Unix epoch


def _parse_int(value: Any, *, default: int, minimum: int, maximum: int, field: str) -> tuple[int | None, str | None]:
    """Parse and clamp integer input safely."""
    if value in (None, ""):
        return default, None
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return None, f"{field} must be an integer"

    if parsed < minimum:
        parsed = minimum
    if parsed > maximum:
        parsed = maximum
    return parsed, None


def _discord_request(endpoint: str, token: str) -> tuple[int, Any]:
    """Make a Discord API request and return parsed JSON where possible."""
    url = f"{DISCORD_API}{endpoint}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "HermesDiscordPlugin/1.1",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = {"raw": raw}
            return resp.status, parsed

    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""

        payload: Any
        if body:
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = {"error": body}
        else:
            payload = {"error": str(e)}

        return e.code, payload

    except Exception as e:
        return 500, {"error": str(e)}


def _snowflake_from_iso(timestamp_str: str) -> str | None:
    """Convert ISO-8601 or human-readable timestamp to a Discord snowflake string."""
    ts = timestamp_str.strip()
    if not ts:
        return None
    if ts.isdigit():
        return ts  # Already a snowflake

    now = datetime.now(timezone.utc)

    if ts.lower() == "today":
        dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif ts.lower() == "yesterday":
        dt = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    else:
        normalized = ts.replace("Z", "+00:00")
        formats = [
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
            "%m/%d/%Y %I:%M %p",
            "%m/%d/%Y %I:%M:%S %p",
        ]

        dt = None
        for fmt in formats:
            try:
                dt = datetime.strptime(normalized, fmt)
                break
            except ValueError:
                continue

        if dt is None:
            m = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)$", ts, re.I)
            if not m:
                return None
            hour = int(m.group(1))
            minute = int(m.group(2) or 0)
            if hour > 12 or minute > 59:
                return None
            meridiem = m.group(3).lower()
            if meridiem == "pm" and hour != 12:
                hour += 12
            elif meridiem == "am" and hour == 12:
                hour = 0
            dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

    ms = int(dt.timestamp() * 1000)
    snowflake = (ms - DISCORD_EPOCH) << 22
    return str(snowflake)


def _format_message(msg: dict[str, Any], *, depth: int = 0, max_depth: int = 1) -> dict[str, Any]:
    """Extract key fields from a Discord message object."""
    author = msg.get("author", {})

    referenced = None
    if depth < max_depth and msg.get("referenced_message"):
        referenced = _format_message(msg["referenced_message"], depth=depth + 1, max_depth=max_depth)

    return {
        "id": msg.get("id"),
        "channel_id": msg.get("channel_id"),
        "author": f"{author.get('username', 'unknown')}#{author.get('discriminator', '0')}",
        "author_id": author.get("id"),
        "username": author.get("username"),
        "display_name": author.get("global_name") or author.get("username"),
        "content": msg.get("content", ""),
        "timestamp": msg.get("timestamp"),
        "edited_timestamp": msg.get("edited_timestamp"),
        "attachments": [
            {"filename": a.get("filename"), "url": a.get("url")}
            for a in msg.get("attachments", [])
        ],
        "embeds": [
            {"title": e.get("title"), "description": e.get("description")}
            for e in msg.get("embeds", [])
        ],
        "mentions": [
            {"id": u.get("id"), "username": u.get("username")}
            for u in msg.get("mentions", [])
        ],
        "referenced_message": referenced,
    }


def handle_read_message(params, **kwargs):
    """Fetch Discord messages by ID or timestamp range from a channel."""
    token = os.getenv("DISCORD_BOT_TOKEN", "")
    if not token:
        return json.dumps({"error": "DISCORD_BOT_TOKEN not set"})

    channel_id = str(params.get("channel_id", "")).strip()
    message_id = str(params.get("message_id", "")).strip()
    before = str(params.get("before", "")).strip()
    after = str(params.get("after", "")).strip()
    since = str(params.get("since", "")).strip()
    around = str(params.get("around", "")).strip()

    limit, limit_err = _parse_int(params.get("limit", "50"), default=50, minimum=1, maximum=100, field="limit")
    if limit_err:
        return json.dumps({"error": limit_err}, indent=2)

    context, context_err = _parse_int(params.get("context", "0"), default=0, minimum=0, maximum=100, field="context")
    if context_err:
        return json.dumps({"error": context_err}, indent=2)

    if not channel_id:
        return json.dumps({"error": "channel_id is required"}, indent=2)

    # Single message by ID — with optional surrounding context
    if message_id:
        status, data = _discord_request(f"/channels/{channel_id}/messages/{message_id}", token)
        if status != 200:
            return json.dumps({"error": f"HTTP {status}", "details": data}, indent=2)

        result = {"message": _format_message(data)}

        if context > 0:
            qs = urllib.parse.urlencode({"limit": context})

            s_before, d_before = _discord_request(
                f"/channels/{channel_id}/messages?before={message_id}&{qs}", token
            )
            s_after, d_after = _discord_request(
                f"/channels/{channel_id}/messages?after={message_id}&{qs}", token
            )

            before_msgs = []
            after_msgs = []
            if s_before == 200 and isinstance(d_before, list):
                # Discord returns newest first; reverse for chronological order
                before_msgs = [_format_message(m) for m in reversed(d_before)]
            if s_after == 200 and isinstance(d_after, list):
                # For "after", API still returns newest first; reverse for chronological order
                after_msgs = [_format_message(m) for m in reversed(d_after)]

            result["context_before"] = before_msgs
            result["context_after"] = after_msgs

        return json.dumps(result, indent=2)

    query: dict[str, str] = {"limit": str(limit)}

    if since:
        sf = _snowflake_from_iso(since)
        if sf:
            query["after"] = sf
        else:
            return json.dumps(
                {
                    "error": f"Could not parse timestamp: {since}",
                    "accepted_examples": [
                        "today",
                        "yesterday",
                        "2026-04-24",
                        "2026-04-24T12:00:00Z",
                        "12pm",
                        "3:30am",
                    ],
                },
                indent=2,
            )
    elif after:
        query["after"] = after

    if before:
        query["before"] = before
    if around:
        query["around"] = around

    endpoint = f"/channels/{channel_id}/messages?{urllib.parse.urlencode(query)}"
    status, data = _discord_request(endpoint, token)

    if status == 200:
        if isinstance(data, list):
            messages = [_format_message(m) for m in data]
            return json.dumps({"messages": messages, "count": len(messages)}, indent=2)
        return json.dumps({"error": "Unexpected API response format"}, indent=2)

    return json.dumps({"error": f"HTTP {status}", "details": data}, indent=2)


def register(ctx):
    """Register the discord_read_message tool."""
    schema = {
        "name": "discord_read_message",
        "description": (
            "Read Discord messages from a channel. Fetch by exact message_id "
            "(with optional 'context' to pull surrounding messages), "
            "or get recent messages with before/after/since/around filters. "
            "The 'since' parameter accepts human-readable timestamps like "
            "'today', 'yesterday', '2026-04-24', '12pm', '3:30am', or ISO-8601. "
            "Use context=1-5 when you need to see messages before and after a target for disambiguation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "channel_id": {
                    "type": "string",
                    "description": "Discord channel ID (required for all operations)",
                },
                "message_id": {
                    "type": "string",
                    "description": "Exact message ID to fetch. Use context=N to pull N messages before and after for disambiguation.",
                },
                "before": {
                    "type": "string",
                    "description": "Get messages before this snowflake ID",
                },
                "after": {
                    "type": "string",
                    "description": "Get messages after this snowflake ID",
                },
                "since": {
                    "type": "string",
                    "description": (
                        "Human-readable timestamp converted to 'after' snowflake. "
                        "Accepts: 'today', 'yesterday', '2026-04-24', '12pm', '3:30am', ISO-8601."
                    ),
                },
                "around": {
                    "type": "string",
                    "description": "Get messages around this snowflake ID",
                },
                "limit": {
                    "type": "string",
                    "description": "Max messages to return (default 50, max 100)",
                },
                "context": {
                    "type": "string",
                    "description": "Number of messages to fetch before AND after the target (max 100). Use when you need surrounding conversation for disambiguation. Only applies when message_id is provided.",
                },
            },
            "required": ["channel_id"],
        },
    }

    ctx.register_tool(
        name="discord_read_message",
        toolset="discord",
        schema=schema,
        handler=handle_read_message,
        description="Read Discord messages by ID, channel, or timestamp range",
    )
