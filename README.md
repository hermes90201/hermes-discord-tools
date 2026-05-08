# Hermes Discord Tools Plugin

A [Hermes Agent](https://github.com/NousResearch/hermes-agent) plugin that extends Discord capabilities with advanced message reading — fetch messages by exact ID, human-readable timestamp ranges, and surrounding context for disambiguation.

## What It Adds

The built-in Discord integration handles sending messages and basic channel interaction. This plugin adds **reading messages back** from Discord:

| Capability | Built-in Discord | This Plugin |
|------------|:---:|:---:|
| Send messages | ✓ | — |
| Fetch by message ID | ✗ | ✓ |
| Fetch by time range | ✗ | ✓ |
| Human-readable timestamps (`"today"`, `"3pm"`) | ✗ | ✓ |
| Surrounding context for disambiguation | ✗ | ✓ |

## Installation

### Prerequisites

- Hermes Agent ≥ v0.11.0
- Discord bot token configured in `~/.hermes/.env`

### Option 1: Git Clone (Recommended)

```bash
cd ~/.hermes/plugins
git clone https://github.com/hermes90201/hermes-discord-tools.git
mv hermes-discord-tools/discord-tools .
rm -rf hermes-discord-tools
```

### Option 2: Manual Download

```bash
mkdir -p ~/.hermes/plugins/discord-tools
wget -O ~/.hermes/plugins/discord-tools/plugin.yaml \
  https://raw.githubusercontent.com/hermes90201/hermes-discord-tools/main/discord-tools/plugin.yaml
wget -O ~/.hermes/plugins/discord-tools/__init__.py \
  https://raw.githubusercontent.com/hermes90201/hermes-discord-tools/main/discord-tools/__init__.py
```

### Option 3: Via Plugin Registry (Future)

```
# Coming when the official plugin registry launches
hermes plugins install discord-tools
```

## Configuration

Add to `~/.hermes/config.yaml`:

```yaml
plugins:
  enabled:
    - discord-tools
```

Then enable the `discord` toolset for your platform:

```bash
hermes tools enable discord --platform discord
hermes gateway restart
```

> **⚠️ Important:** The `discord` toolset is in Hermes's `DEFAULT_OFF_TOOLSETS` list. Even though you're on the Discord platform, you must explicitly enable it. Without this step, `discord_read_message` won't appear in your agent's tools.

**verify the plugin loaded:**
```bash
hermes plugins list | grep discord-tools
```

## Usage

### Fetch a message by ID

```
Read message 1502111057177481377 from channel 1494428308413219057
```

The agent calls `discord_read_message(message_id="1502...", channel_id="1494...")`.

### Fetch with context for disambiguation

```
Read message 1502111057177481377 with 3 messages of context
```

Returns the target message plus 3 messages before and after — perfect for understanding conversation flow.

### Fetch messages since a human-readable time

```
Show me messages since 3pm in #operations
```

The plugin understands:
- `"today"`, `"yesterday"`
- `"2026-05-08"`, `"2026-05-08T14:30:00"`
- `"3pm"`, `"11:30am"`
- ISO-8601 timestamps
- Raw Discord snowflake IDs

### Fetch recent messages

```
Show the last 10 messages from channel 1497113266294620310
```

## Tool Schema

```json
{
  "name": "discord_read_message",
  "parameters": {
    "channel_id": "Discord channel ID (required for all operations)",
    "message_id": "Exact message ID to fetch. Use context=N to pull surrounding messages.",
    "since": "Human-readable timestamp: 'today', 'yesterday', '2026-04-24', '12pm', '3:30am', ISO-8601",
    "before": "Get messages before this snowflake ID",
    "after": "Get messages after this snowflake ID",
    "around": "Get messages around this snowflake ID",
    "limit": "Max messages (default 50, max 100)",
    "context": "Messages to fetch before AND after the target for disambiguation"
  }
}
```

## Troubleshooting

### Plugin tool not appearing after install

**Most common cause:** The `discord` toolset is opt-in only. Run:

```bash
hermes tools enable discord --platform discord
hermes gateway restart
```

Then start a **new session** (`/new` or `/reset`) — toolset changes only take effect on new sessions, not mid-conversation.

### Plugin installed but not listed

```bash
# Check plugin files exist
ls -la ~/.hermes/plugins/discord-tools/

# Verify Python syntax
python3 -m py_compile ~/.hermes/plugins/discord-tools/__init__.py

# Check config
grep -A5 'plugins:' ~/.hermes/config.yaml
```

### Verify plugin loading in isolation

Test that the plugin loads correctly outside the gateway:

```bash
cd ~/.hermes/hermes-agent && python3 -c "
import sys, os
os.environ['HERMES_HOME'] = os.path.expanduser('~/.hermes')
sys.path.insert(0, '.')
from hermes_cli.plugins import discover_plugins, get_plugin_manager
discover_plugins(force=True)
pm = get_plugin_manager()
for k, p in pm._plugins.items():
    if 'discord' in k:
        print(f'{k}: enabled={p.enabled}, tools={p.tools_registered}, error={p.error}')
"
```

### DISCORD_BOT_TOKEN not found

The plugin uses the same `DISCORD_BOT_TOKEN` environment variable as the main Hermes Discord gateway. Verify it's set:

```bash
grep DISCORD_BOT_TOKEN ~/.hermes/.env
```

## How It Works

The plugin registers a single tool — `discord_read_message` — into the `discord` toolset. When the agent needs to read messages, it calls this tool instead of the built-in `discord` tool (which focuses on sending).

The tool makes direct Discord REST API calls using the same bot token as the gateway. It parses responses into clean JSON with `author`, `content`, `timestamp`, `attachments`, `embeds`, `mentions`, and `referenced_message` fields.

Human-readable timestamps are converted to Discord snowflakes using the standard Discord epoch calculation.

## Community & Ecosystem

This plugin follows the [official Hermes plugin structure](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/guides/build-a-hermes-plugin.md).

### Other Community Plugins

- [42-evey/hermes-plugins](https://github.com/42-evey/hermes-plugins) — 23 plugins for autonomy, observability, cost control, and self-improvement
- [NousResearch Discord](https://discord.gg/nousresearch) — #hermes-agent channel for sharing plugins and getting help

### Publishing Your Own Plugin

1. Structure it as `plugin.yaml` + `__init__.py`
2. Push to a public GitHub repo
3. Share in the Nous Research Discord
4. When the official registry launches, you'll be able to publish via `hermes plugins publish`

## License

MIT — see [LICENSE](LICENSE)
