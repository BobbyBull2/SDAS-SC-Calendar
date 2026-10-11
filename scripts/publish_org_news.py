#!/usr/bin/env python3
"""Publish only explicitly authorized SDAS #org-news text to a small public JSON feed.

This collector is intentionally inert unless the guarded GitHub workflow is enabled
with the approved channel ID and publication switch.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import warnings
from PIL import Image, ImageOps
from datetime import datetime, timezone, timedelta

GUILD_ID = "1518410019249459236"
APPROVED_CHANNEL_ID = "1519103863758520471"
API = "https://discord.com/api/v10"
MAX_ITEMS = 10
MAX_PAGES = 100
CHANNEL_ID_RE = re.compile(r"^[0-9]{17,20}$")
USER_MENTION = re.compile(r"<@!?[0-9]{17,20}>")
ROLE_MENTION = re.compile(r"<@&[0-9]{17,20}>")
CHANNEL_MENTION = re.compile(r"<#[0-9]{17,20}>")
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024
IMAGE_HOSTS = {"cdn.discordapp.com", "media.discordapp.net"}
PUBLIC_IMAGE_ROOT = "https://bobbybull2.github.io/SDAS-SC-Calendar/org-news/images/"
Image.MAX_IMAGE_PIXELS = 25_000_000
warnings.simplefilter("error", Image.DecompressionBombWarning)

class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def safe_image_url(value):
    """Accept only Discord-owned attachment or image-proxy HTTPS URLs."""
    if not isinstance(value, str):
        return False
    try:
        p = urllib.parse.urlsplit(value)
        host = p.hostname or ""
        if p.scheme != "https" or p.username or p.password or p.port not in (None, 443):
            return False
        if host in IMAGE_HOSTS:
            return p.path.startswith("/attachments/")
        if re.fullmatch(r"images-ext-[1-9]\d*\.discordapp\.net", host):
            return p.path.startswith("/external/")
        return False
    except ValueError:
        return False

def image_candidate(message):
    """Only the first image per post; source URL never enters the public JSON feed."""
    for a in message.get("attachments") or []:
        if not isinstance(a, dict):
            continue
        kind = a.get("content_type") or ""
        name = str(a.get("filename") or "").lower()
        media = kind.lower().startswith("image/") if isinstance(kind, str) and kind else any(name.endswith(ext) for ext in IMAGE_EXTS)
        if not media:
            continue
        for key in ("url", "proxy_url"):
            if safe_image_url(a.get(key)):
                return a[key]
    for embed in message.get("embeds") or []:
        if not isinstance(embed, dict):
            continue
        for key in ("image", "thumbnail"):
            part = embed.get(key) or {}
            if isinstance(part, dict):
                for url_key in ("proxy_url", "url"):
                    if safe_image_url(part.get(url_key)):
                        return part[url_key]
    return None

def download_art(url):
    if not safe_image_url(url):
        raise ValueError("Unsafe art source")
    req = urllib.request.Request(url, headers={"User-Agent": "SDAS-News-Artwork/1.0"})
    with urllib.request.build_opener(NoRedirects()).open(req, timeout=25) as response:
        raw = response.read(MAX_IMAGE_BYTES + 1)
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("Artwork exceeds size limit")
    with Image.open(io.BytesIO(raw)) as im:
        im.load()
        picture = ImageOps.exif_transpose(im).convert("RGB")
        picture.thumbnail((1200, 800))
        buf = io.BytesIO()
        picture.save(buf, format="WEBP", quality=82, method=5)
        return buf.getvalue()

def publish_art(posts, folder, downloader=download_art):
    """Host normalized, metadata-free images; prune images outside the rolling FIFO."""
    folder.mkdir(parents=True, exist_ok=True)
    keep = set()
    saved = 0
    for post in posts:
        source = post.pop("_imageSource", None)
        if not source:
            continue
        mid = post["id"].removeprefix("discord-")
        file = folder / (mid + ".webp")
        if not file.is_file():
            try:
                data = downloader(source)
                # Never risk blanking the feed if an old Discord CDN URL has expired.
                if not data:
                    continue
                file.write_bytes(data)
                saved += 1
            except (ValueError, OSError, urllib.error.URLError, Image.UnidentifiedImageError,
                    Image.DecompressionBombError, Image.DecompressionBombWarning):
                continue
        post["imageUrl"] = PUBLIC_IMAGE_ROOT + file.name
        post["imageAlt"] = "Artwork shared with this SDAS announcement"
        keep.add(file.name)
    for old in folder.glob("*.webp"):
        if old.name not in keep:
            old.unlink()
    return saved


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
        if not isinstance(msg, dict) or msg.get("type") != 0:
            continue
        mid = str(msg.get("id", ""))
        if not CHANNEL_ID_RE.fullmatch(mid) or mid in seen:
            continue
        seen.add(mid)
        if msg.get("author", {}).get("bot", False) or msg.get("webhook_id"):
            continue
        raw = clean_text(msg.get("content", ""))
        artwork = image_candidate(msg)
        if not raw and not artwork:
            continue
        when = date_utc(msg.get("timestamp"))
        if when < started_at:
            continue
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        title = lines[0].lstrip("# ").strip()[:120] if lines else "SDAS artwork"
        body = (("\n".join(lines[1:]) if len(lines) > 1 else lines[0]) if lines else "Artwork shared in #org-news.")[:700]
        item = {
            "id": "discord-" + mid,
            "title": title,
            "body": body,
            "publishedAt": when.isoformat().replace("+00:00", "Z"),
            "discordUrl": f"https://discord.com/channels/{GUILD_ID}/{channel_id}/{mid}",
        }
        if artwork:
            item["_imageSource"] = artwork
        selected.append(item)
    # Select newest 10, then render in chronological/FIFO order.
    selected.sort(key=lambda item: (item["publishedAt"], int(item["id"].split("-")[1])), reverse=True)
    return list(reversed(selected[:MAX_ITEMS]))

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
    if not CHANNEL_ID_RE.fullmatch(channel_id) or channel_id != APPROVED_CHANNEL_ID:
        raise ValueError("Channel ID does not match the approved SDAS #org-news channel")
    channel = getter(f"/channels/{channel_id}", token)
    if channel.get("guild_id") != GUILD_ID:
        raise ValueError("Channel is not in the approved SDAS Discord server")
    if channel.get("type") not in (0, 5):
        raise ValueError("Approved Discord channel is not a supported text/announcement channel")
    # The exact approved channel ID is pinned above. A cosmetic Discord rename is okay.
    messages, cursor, seen = [], None, set()
    reached_cutoff = False
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
            reached_cutoff = True
            break
        if len(select_posts(messages, channel_id, started_at)) >= MAX_ITEMS:
            break
    if not reached_cutoff and len(messages) >= MAX_PAGES * 100 and len(select_posts(messages, channel_id, started_at)) < MAX_ITEMS:
        raise ValueError("Three-month history exceeds scan limit; refusing incomplete archive")
    posts = select_posts(messages, channel_id, started_at)
    return {"schemaVersion": 1, "mode": "live", "channelId": channel_id, "items": posts}

def main():
    if os.environ.get("SDAS_ORG_NEWS_PUBLIC_ENABLED") != "true":
        raise SystemExit("News publication is disabled; approval is required")
    token = os.environ.get("DISCORD_BOT_TOKEN", "")
    channel_id = os.environ.get("SDAS_ORG_NEWS_CHANNEL_ID", "")
    if not token or not channel_id:
        raise SystemExit("Required bot token or approved channel ID missing")
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=90)
        output = collect(token, channel_id, cutoff)
        downloaded = publish_art(output["items"], Path(__file__).resolve().parent.parent / "org-news" / "images")
        print(f"News artwork: {downloaded} new image(s) downloaded")
    except (ValueError, RuntimeError, urllib.error.URLError, OSError) as error:
        print(f"News feed preserved; sync failed: {type(error).__name__}: {str(error) if isinstance(error, ValueError) else 'Discord transport/API failure'}", file=sys.stderr)
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
    print(f"Org news feed prepared with {len(output['items'])} publicly approved-channel posts (FIFO, oldest to newest)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
