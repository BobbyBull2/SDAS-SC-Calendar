#!/usr/bin/env python3
"""Read-only Discord diagnostic; an emoji reaction is NOT officer approval.

Uses only the Python standard library. No attachments are downloaded and no
Discord messages or reactions are changed. Reaction-user identities and officer
authorization are deliberately not inferred from the emoji's name.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import PurePosixPath

API_BASE = "https://discord.com/api/v10"
GUILD_ID = "1518410019249459236"
CHANNEL_ID = "1519105573067686000"
EMOJI_NAME = "sdasapproved"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".bmp", ".tif", ".tiff", ".heic", ".heif"}


class DiagnosticError(Exception):
    """An already-reported API failure or a safe local diagnostic error."""


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the Bot Authorization header to another location.
        return None


class DiscordAPI:
    def __init__(self, token):
        self.token = token
        self.opener = urllib.request.build_opener(NoRedirects())

    def report(self, **fields):
        # JSON keeps untrusted API text on one line; redact before logging.
        serialized = json.dumps(fields, ensure_ascii=True)
        escaped_token = json.dumps(self.token, ensure_ascii=True)[1:-1]
        print(serialized.replace(escaped_token, "[REDACTED]"), flush=True)

    def get(self, path):
        request = urllib.request.Request(
            API_BASE + path,
            headers={
                "Authorization": f"Bot {self.token}",
                "User-Agent": "SDAS-Screenshot-Diagnostic/1.0",
            },
            method="GET",
        )
        try:
            with self.opener.open(request, timeout=30) as response:
                self.report(endpoint=path, http_status=response.status)
                try:
                    return json.load(response)
                except (ValueError, UnicodeError):
                    raise DiagnosticError("API returned invalid JSON") from None
        except urllib.error.HTTPError as error:
            details = {}
            with error:
                try:
                    body = json.load(error)
                    if isinstance(body, dict):
                        # Do not dump response bodies, headers, or request objects.
                        details = {
                            key: body[key]
                            for key in ("code", "message", "retry_after", "global")
                            if key in body
                        }
                except (ValueError, UnicodeError):
                    details["message"] = "Non-JSON error response (body omitted)"
            self.report(endpoint=path, http_status=error.code, api_error=details)
            raise DiagnosticError("Discord HTTP request failed; see status above") from None
        except (urllib.error.URLError, OSError, ValueError) as error:
            # Exception strings may include request data; report only safe types.
            self.report(endpoint=path, http_status=None, transport_error=type(error).__name__)
            raise DiagnosticError("Request failed without a usable HTTP response") from None


def is_image(attachment):
    """Prefer declared media type; use filename only when it is absent.

    This is attachment metadata classification, not content-byte verification.
    Videos, embeds, stickers, and linked images are not counted.
    """
    media_type = attachment.get("content_type")
    if media_type:
        return media_type.lower().startswith("image/")
    return PurePosixPath(attachment.get("filename", "")).suffix.lower() in IMAGE_EXTENSIONS


def summarize(messages, emoji_id):
    image_count = 0
    reacted_image_count = 0
    reacted_message_count = 0
    for message in messages:
        images = sum(is_image(item) for item in message.get("attachments", []))
        image_count += images
        # A reaction applies to the message, hence to each image attached to it.
        # Match the actual custom emoji ID, never merely the display name.
        reacted = any(
            reaction.get("emoji", {}).get("id") == emoji_id
            and reaction.get("count", 0) > 0
            for reaction in message.get("reactions", [])
        )
        if reacted and images:
            reacted_message_count += 1
            reacted_image_count += images
    return {
        "messages_inspected": len(messages),
        "image_attachments": image_count,
        "image_messages_with_exact_emoji_reaction": reacted_message_count,
        "image_attachments_with_exact_emoji_reaction": reacted_image_count,
        "reacting_user_identities_verified": False,
        "officer_approved_image_count": None,
        "approval_status": "NOT VERIFIED: emoji reactions alone do not prove officer approval",
    }


def main():
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        print("ERROR: DISCORD_BOT_TOKEN is not set", file=sys.stderr)
        return 1
    api = DiscordAPI(token)
    try:
        emojis = api.get(f"/guilds/{GUILD_ID}/emojis")
        if not isinstance(emojis, list):
            raise DiagnosticError("Expected a list of guild emojis")
        matches = [emoji for emoji in emojis if emoji.get("name") == EMOJI_NAME]
        if len(matches) != 1:
            raise DiagnosticError("Expected exactly one custom emoji named sdasapproved")
        emoji_id = matches[0].get("id")
        if not isinstance(emoji_id, str) or not emoji_id.isascii() or not emoji_id.isdecimal():
            raise DiagnosticError("Custom emoji has no valid numeric ID")
        api.report(guild_id=GUILD_ID, emoji_name=EMOJI_NAME, emoji_id=emoji_id)
        channel = api.get(f"/channels/{CHANNEL_ID}")
        if not isinstance(channel, dict) or channel.get("guild_id") != GUILD_ID:
            raise DiagnosticError("Channel does not belong to the expected guild")
        messages = api.get(f"/channels/{CHANNEL_ID}/messages?limit=25")
        if not isinstance(messages, list) or len(messages) > 25:
            raise DiagnosticError("Expected at most 25 channel messages")
        api.report(channel_id=CHANNEL_ID, emoji_id=emoji_id, **summarize(messages, emoji_id))
    except DiagnosticError as error:
        api.report(error=str(error), result="FAILED; no complete count available")
        return 1
    except Exception as error:
        # Avoid tracebacks that could contain credentials or private API content.
        api.report(error="Unexpected diagnostic failure", error_type=type(error).__name__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
