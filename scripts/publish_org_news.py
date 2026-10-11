#!/usr/bin/env python3
"""Publish only explicitly authorized SDAS #org-news text to a small public JSON feed.

This collector is intentionally inert unless the guarded GitHub workflow is enabled
with both the correct channel ID and a post-approval start timestamp.
"""
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

GUILD_ID = "1518410019249459236"
API = "https://discord.com/api/v10"
MAX_ITEMS = 12
MAX_PAGES = 5
CHANNEL_ID_RE = re.compile(r"^[0-9]{17,20}$")
USER_MENTION = re.compile(r"<@!?[0-9]{17,20}>")
ROLE_MENTION = re.compile(r"<@&[0-9]{17,20}>")
CHANNEL_MENTION = re.compile(r"<#[0-9]{17,20}>")

def date_utc(value):
    if not isinstance(value, str):
        raise ValueError("Missing timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp lacks timezone")
    return parsed.astimezone(timezone.utc)

def clean_text(value):
    if not isinstance(value, str):
        return ""
    value = USER_MENTION.sub("[member]", value)
    value = ROLE_MENTION.sub("[role]", value)
    value = CHANNEL_MENTION.sub("#channel", value)
    value = re.sub(r"@(everyone|here)\b", r"\1", value, flags=re.IGNORECASE)
    value = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()

def select_posts(messages, channel_id, started_at):
    selected = []
    seen = set()
    for msg in messages:
        if not isinstance(msg, dict) or msg.get("type") not in (0, 19):
            continue
        mid = str(msg.get("id", ""))
        if not CHANNEL_ID_RE.fullmatch(mid) or mid in seen:
            continue
        seen.add(mid)
        if msg.get("author", {}).get("bot", False) or msg.get("webhook_id"):
            continue
        raw = clean_text(msg.get("content", ""))
        if not raw:
            continue
        when = date_utc(msg.get("timestamp"))
        if when < started_at:
            continue
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        title = lines[0].lstrip("# ").strip()[:120] or "SDAS update"
        # Text-only; attachments, embeds, and members' identity are never exported.
        body = ("\n".join(lines[1:]) if len(lines) > 1 else lines[0])[:700]
        selected.append({
            "id": "discord-" + mid,
            "title": title,
            "body": body,
            "publishedAt": when.isoformat().replace("+00:00", "Z"),
            "discordUrl": f"https://discord.com/channels/{GUILD_ID}/{channel_id}/{mid}",
        })
    selected.sort(key=lambda item: (item["publishedAt"], int(item["id"].split("-")[1])), reverse=True)
    return selected[:MAX_ITEMS]

def fetch_json(path, token):
    for attempt in range(3):
        req = urllib.request.Request(
            API + path,
            headers={
                "Authorization": "Bot " + token,
                "User-Agent": "SDAS-Org-News-Publisher/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=25) as response:
                if response.status != 200:
                    raise RuntimeError("Discord returned an unexpected response")
                return json.load(response)
        except urllib.error.HTTPError as err:
            if err.code == 429 and attempt < 2:
                try:
                    retry = json.loads(err.read(1024)).get("retry_after", 2)
                except (ValueError, UnicodeError):
                    retry = 2
                time.sleep(min(max(float(retry), 1), 15))
                continue
            raise RuntimeError(f"Discord API returned HTTP {err.code}") from None
    raise RuntimeError("Discord request could not be completed")

def collect(token, channel_id, started_at, getter=fetch_json):
    if not CHANNEL_ID_RE.fullmatch(channel_id):
        raise ValueError("A valid #org-news channel ID is required")
    channel = getter(f"/channels/{channel_id}", token)
    if (channel.get("guild_id") != GUILD_ID or
        channel.get("name") != "org-news" or channel.get("type") not in (0, 5)):
        raise ValueError("Channel does not match the approved SDAS #org-news text channel")
    messages, cursor, seen = [], None, set()
    for _ in range(MAX_PAGES):
        path = f"/channels/{channel_id}/messages?limit=100"
        if cursor:
            path += f"&before={cursor}"
        batch = getter(path, token)
        if not isinstance(batch, list) or len(batch) > 100:
            raise ValueError("Invalid Discord messages response")
        if not batch:
            break
        ids = [str(item.get("id", "")) for item in batch]
        if any(not CHANNEL_ID_RE.fullmatch(x) or x in seen for x in ids):
            raise ValueError("Discord message pagination failed")
        seen.update(ids)
        messages.extend(batch)
        cursor = str(min(int(x) for x in ids))
        # Discord sends newest first. Stop when entire batch predates the opt-in.
        if all(date_utc(item.get("timestamp")) < started_at for item in batch):
            break
        if len(select_posts(messages, channel_id, started_at)) >= MAX_ITEMS:
            break
    posts = select_posts(messages, channel_id, started_at)
    return {"schemaVersion": 1, "mode": "live", "channelId": channel_id, "items": posts}

def main():
    if os.environ.get("SDAS_ORG_NEWS_PUBLIC_ENABLED") != "true":
        raise SystemExit("News publication is disabled; approval is required")
    token = os.environ.get("DISCORD_BOT_TOKEN", "")
    channel_id = os.environ.get("SDAS_ORG_NEWS_CHANNEL_ID", "")
    start_at = os.environ.get("SDAS_ORG_NEWS_START_AT", "")
    if not token or not channel_id or not start_at:
        raise SystemExit("Required bot token, approved channel ID or start timestamp missing")
    try:
        output = collect(token, channel_id, date_utc(start_at))
    except (ValueError, RuntimeError, urllib.error.URLError, OSError) as error:
        print(f"News feed preserved; sync failed: {type(error).__name__}", file=sys.stderr)
        return 1
    dest = Path(__file__).resolve().parent.parent / "org-news" / "feed.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, filename = tempfile.mkstemp(prefix=".news-", dir=dest.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(output, file, indent=2, ensure_ascii=False)
            file.write("\n")
        os.replace(filename, dest)
    finally:
        if os.path.exists(filename):
            os.remove(filename)
    print(f"Org news feed prepared with {len(output['items'])} publicly approved-channel posts")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
