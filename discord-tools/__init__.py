"""
Discord Tools Plugin — read messages by ID, fetch with timestamp ranges.

Uses the existing DISCORD_BOT_TOKEN from the Hermes environment.
Adds 'discord_read_message' tool to the 'discord' toolset.
"""

import json
import os
import re
import urllib.request
import urllib.error
from datetime import datetime, timezone


DISCORD_API = "https://discord.com/api/v10"
DISCORD_EPOCH = 1420070400000  # ms since Unix epoch


def _discord_request(endpoint, token):
    """Make a Discord API request and return parsed JSON."""
    url = f"{DISCORD_API}{endpoint}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "HermesDiscordPlugin/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, {"error": str(e)}
    except Exception as e:
        return 500, {"error": str(e)}


def _snowflake_from_iso(timestamp_str):
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
        dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
        dt = dt.replace(day=dt.day - 1)
    else:
        formats = [
            "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
            "%m/%d/%Y %I:%M %p", "%m/%d/%Y %I:%M:%S %p",
        ]
        dt = None
        for fmt in formats:
            try:
                dt = datetime.strptime(ts, fmt)
                break
            except ValueError:
                continue
        if dt is None:
            m = re.match(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", ts, re.I)
            if m:
                hour = int(m.group(1))
                minute = int(m.group(2) or 0)
                meridiem = m.group(3).lower()
                if meridiem == "pm" and hour != 12:
                    hour += 12
                elif meridiem == "am" and hour == 12:
                    hour = 0
                dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            else:
                return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

    ms = int(dt.timestamp() * 1000)
    snowflake = (ms - DISCORD_EPOCH) << 22
    return str(snowflake)


def _format_message(msg):
    """Extract key fields from a Discord message object."""
    author = msg.get("author", {})
    return {
        "id": msg.get("id"),
        "channel_id": msg.get("channel_id"),
        "author": f"{author.get('username', 'unknown')}#{author.get('discriminator', '0')}",
        "author_id": author.get("id"),
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
        "referenced_message": _format_message(msg["referenced_message"])
        if msg.get("referenced_message") else None,
    }


def handle_read_message(params, **kwargs):
    """Fetch Discord messages by ID or timestamp range from a channel."""
    token = os.getenv("DISCORD_BOT_TOKEN", "")
    if not token:
        return json.dumps({"error": "DISCORD_BOT_TOKEN not set"})

    channel_id = params.get("channel_id", "")
    message_id = params.get("message_id", "")
    before = params.get("before", "")
    after = params.get("after", "")
    since = params.get("since", "")
    around = params.get("around", "")
    limit = min(int(params.get("limit", "50")), 100)
    context = int(params.get("context", "0"))

    # Single message by ID — with optional surrounding context
    if message_id:
        status, data = _discord_request(
            f"/channels/{channel_id}/messages/{message_id}", token
        )
        if status != 200:
            return json.dumps({"error": f"HTTP {status}: {data}"}, indent=2)

        result = {"message": _format_message(data)}

        if context > 0:
            # Fetch messages before and after
            before_msgs = []
            after_msgs = []
            qs = f"limit={min(context, 100)}"
            s1, d1 = _discord_request(
                f"/channels/{channel_id}/messages?before={message_id}&{qs}", token)
            s2, d2 = _discord_request(
                f"/channels/{channel_id}/messages?after={message_id}&{qs}", token)
            if s1 == 200 and isinstance(d1, list):
                before_msgs = [_format_message(m) for m in d1]
            if s2 == 200 and isinstance(d2, list):
                after_msgs = [_format_message(m) for m in reversed(d2)]  # chronological order
            result["context_before"] = before_msgs
            result["context_after"] = after_msgs

        return json.dumps(result, indent=2)

    # Message range
    if not channel_id:
        return json.dumps({"error": "channel_id is required"})

    query = [f"limit={min(limit, 100)}"]

    if since:
        sf = _snowflake_from_iso(since)
        if sf:
            query.append(f"after={sf}")
        else:
            return json.dumps({"error": f"Could not parse timestamp: {since}"})
    elif after:
        query.append(f"after={after}")

    if before:
        query.append(f"before={before}")
    if around:
        query.append(f"around={around}")

    endpoint = f"/channels/{channel_id}/messages?{'&'.join(query)}"
    status, data = _discord_request(endpoint, token)

    if status == 200:
        if isinstance(data, list):
            messages = [_format_message(m) for m in data]
            return json.dumps({"messages": messages, "count": len(messages)}, indent=2)
        return json.dumps({"error": "Unexpected API response format"}, indent=2)

    return json.dumps({"error": f"HTTP {status}: {data}"}, indent=2)


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
