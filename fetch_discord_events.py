#!/usr/bin/env python3
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

GUILD_ID = os.environ.get("DISCORD_GUILD_ID", "1518410019249459236")
TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
OUT = Path(__file__).resolve().parent / "discord-events.json"

if not TOKEN:
    raise SystemExit("DISCORD_BOT_TOKEN is not set")

url = f"https://discord.com/api/v10/guilds/{GUILD_ID}/scheduled-events?with_user_count=false"
req = urllib.request.Request(
    url,
    headers={
        "Authorization": f"Bot {TOKEN}",
        "User-Agent": "SDAS-Calendar-Sync/1.0",
    },
)
with urllib.request.urlopen(req, timeout=30) as response:
    raw = json.load(response)

events = []
for e in raw:
    start = e.get("scheduled_start_time")
    end = e.get("scheduled_end_time")
    if not start:
        continue
    events.append({
        "id": str(e["id"]),
        "title": e.get("name", "SDAS Event"),
        "description": e.get("description") or "",
        "start": start,
        "end": end,
        "status": e.get("status"),
        "entity_type": e.get("entity_type"),
        "location": (e.get("entity_metadata") or {}).get("location") or "",
        "recurrence_rule": e.get("recurrence_rule"),
        "source": f"https://discord.com/events/{GUILD_ID}/{e['id']}",
    })

payload = {
    "guild_id": GUILD_ID,
    "fetched_at": datetime.now(timezone.utc).isoformat(),
    "events": events,
}
OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
print(f"Fetched {len(events)} Discord scheduled event(s).")
