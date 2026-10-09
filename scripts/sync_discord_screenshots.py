#!/usr/bin/env python3
"""Produce a review-only image bundle; never publish, commit, or deploy it."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import warnings
from datetime import datetime, timezone

from PIL import Image, ImageOps
from test_discord_screenshots import DiscordAPI, DiagnosticError, NoRedirects, is_image

GUILD = '1518410019249459236'
CHANNEL = '1519105573067686000'
EMOJI = '1557915851922083880'
MAX_BYTES = 25 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 40_000_000
warnings.simplefilter('error', Image.DecompressionBombWarning)


def snowflake(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,20}', value):
        raise DiagnosticError('Invalid Discord numeric ID')
    return value


class SyncAPI(DiscordAPI):
    def get(self, path):
        # Read-only GETs: bounded retries for Discord rate limits and 5xx only.
        for attempt in range(4):
            req = urllib.request.Request('https://discord.com/api/v10' + path,
                headers={'Authorization': f'Bot {self.token}', 'User-Agent': 'SDAS-Gallery-Sync/1.0'})
            try:
                with self.opener.open(req, timeout=30) as response:
                    self.report(endpoint=path, http_status=response.status)
                    return json.load(response)
            except urllib.error.HTTPError as error:
                status = error.code
                with error:
                    try:
                        body = json.load(error)
                    except (ValueError, UnicodeError):
                        body = {}
                if not isinstance(body, dict):
                    body = {}
                self.report(endpoint=path, http_status=status,
                    api_error={k: body[k] for k in ('code', 'message', 'retry_after') if k in body})
                if attempt == 3 or (status != 429 and status < 500):
                    raise DiagnosticError('Discord API request failed') from None
                delay = float(body.get('retry_after', 2 ** attempt))
                if not 0 <= delay <= 60:
                    raise DiagnosticError('Rate limit exceeds bounded retry window')
                time.sleep(delay + 0.1)
            except (urllib.error.URLError, OSError, ValueError) as error:
                self.report(endpoint=path, http_status=None, error_type=type(error).__name__)
                raise DiagnosticError('Discord transport or JSON failure') from None


def messages(api, max_pages):
    before = None
    seen = set()
    for _ in range(max_pages):
        path = f'/channels/{CHANNEL}/messages?limit=100'
        if before:
            path += '&before=' + before
        batch = api.get(path)
        if not isinstance(batch, list) or len(batch) > 100:
            raise DiagnosticError('Invalid messages response')
        if not batch:
            return
        ids = [snowflake(m['id']) for m in batch]
        if any(i in seen for i in ids) or (before and any(int(i) >= int(before) for i in ids)):
            raise DiagnosticError('Message pagination did not advance')
        seen.update(ids)
        yield from batch
        before = min(ids, key=int)
        # Continue to an empty page, including after short pages.
    raise DiagnosticError('History page limit reached; refusing an incomplete bundle')


def approving_users(api, message_id, allowed):
    matched = set()
    emoji = urllib.parse.quote('sdasapproved:' + EMOJI, safe='')
    # Both ordinary and burst/super reactions have separate user lists.
    for reaction_type in (0, 1):
        after = None
        for _ in range(1000):
            path = f'/channels/{CHANNEL}/messages/{message_id}/reactions/{emoji}?limit=100&type={reaction_type}'
            if after:
                path += '&after=' + after
            users = api.get(path)
            if not isinstance(users, list) or len(users) > 100:
                raise DiagnosticError('Invalid reacting-user response')
            if not users:
                break
            ids = [snowflake(u['id']) for u in users]
            if after and any(int(i) <= int(after) for i in ids):
                raise DiagnosticError('Reaction-user pagination did not advance')
            matched.update(u['id'] for u in users if u['id'] in allowed and not u.get('bot', False))
            after = max(ids, key=int)
            if len(users) < 100:
                break
        else:
            raise DiagnosticError('Reacting-user page limit reached')
    return sorted(matched)


def download_image(url):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname not in {'cdn.discordapp.com', 'media.discordapp.net'}
            or parsed.username or parsed.password or parsed.port not in (None, 443)
            or not parsed.path.startswith('/attachments/')):
        raise DiagnosticError('Attachment URL is not an allowed Discord CDN location')
    # Separate opener/request: never send bot credentials to the CDN; no redirects.
    opener = urllib.request.build_opener(NoRedirects())
    try:
        with opener.open(urllib.request.Request(url, headers={'User-Agent': 'SDAS-Gallery-Sync/1.0'}), timeout=30) as response:
            print(json.dumps({'operation': 'download_image', 'http_status': response.status}))
            data = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as error:
        print(json.dumps({'operation': 'download_image', 'http_status': error.code}))
        error.close()
        raise DiagnosticError('Image download failed; URL omitted') from None
    except (urllib.error.URLError, OSError):
        raise DiagnosticError('Image transport failure; URL omitted') from None
    if len(data) > MAX_BYTES:
        raise DiagnosticError('Image exceeds 25 MiB limit')
    return normalize_image(data)


def normalize_image(data):
    # Decode and re-encode raster pixels: remove metadata and reject HTML/SVG/etc.
    with Image.open(io.BytesIO(data)) as source:
        source.load()
        picture = ImageOps.exif_transpose(source).convert('RGB')
        picture.thumbnail((2560, 2560))
        width, height = picture.size
        output = io.BytesIO()
        picture.save(output, format='WEBP', quality=88, method=6)
    return output.getvalue(), width, height


def message_time(message):
    # Discord snowflakes encode creation time, not reaction/approval time.
    value = message.get('timestamp')
    if value is None:
        milliseconds = (int(snowflake(message['id'])) >> 22) + 1420070400000
        return datetime.fromtimestamp(milliseconds / 1000, timezone.utc).isoformat()
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise DiagnosticError('Discord message timestamp has no timezone')
    return parsed.astimezone(timezone.utc).isoformat()


def select_images(candidates):
    def order(item):
        # Only use an approval timestamp if both the identity and time are known.
        # REST snapshots currently provide no approval timestamps: approvedAt=None.
        value = item.get('approvedAt') if item['verifiedApproverIds'] else None
        value = value or item['messageTimestamp']
        date = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if date.tzinfo is None:
            raise DiagnosticError('Gallery ordering timestamp has no timezone')
        return date.timestamp(), int(item['messageId']), int(item['attachmentId'])
    identities = [c['messageId'] + '-' + c['attachmentId'] for c in candidates]
    if len(set(identities)) != len(identities):
        raise DiagnosticError('Duplicate gallery attachment')
    return sorted(candidates, key=order, reverse=True)[:25]


def sync(api, destination, allowed, max_pages=1000, include_provisional=False, reaction_is_approval=False):
    if not allowed and not include_provisional and not reaction_is_approval:
        raise DiagnosticError('Verified mode requires SDAS_APPROVER_IDS; use explicit provisional mode for local review')
    if destination.exists():
        raise DiagnosticError('Output already exists; choose a new bundle directory')
    emojis = api.get(f'/guilds/{GUILD}/emojis')
    if not isinstance(emojis, list) or not any(e.get('id') == EMOJI and e.get('name') == 'sdasapproved' for e in emojis):
        raise DiagnosticError('Configured emoji ID/name not found in guild')
    channel = api.get(f'/channels/{CHANNEL}')
    if channel.get('guild_id') != GUILD:
        raise DiagnosticError('Screenshot channel is outside the expected guild')
    candidates, inspected, reaction_messages = [], 0, 0
    for message in messages(api, max_pages):
        inspected += 1
        if not any(r.get('emoji', {}).get('id') == EMOJI and r.get('count', 0) > 0 for r in message.get('reactions', [])):
            continue
        attachments = [a for a in message.get('attachments', []) if is_image(a)]
        if not attachments:
            continue
        reaction_messages += 1
        mid = snowflake(message['id'])
        verified = [] if reaction_is_approval else approving_users(api, mid, allowed)
        if not verified and not include_provisional and not reaction_is_approval:
            continue
        for attachment in attachments:
            candidates.append({'messageId': mid, 'attachmentId': snowflake(attachment['id']),
                'messageTimestamp': message_time(message), 'approvedAt': None,
                'verifiedApproverIds': verified, 'attachment': attachment})
    selected = select_images(candidates)
    destination.parent.mkdir(parents=True, exist_ok=True)
    items = []
    with tempfile.TemporaryDirectory(prefix='.screenshot-stage-', dir=destination.parent) as staging:
        stage = Path(staging)
        (stage / 'images').mkdir()
        for candidate in selected:
            attachment = candidate['attachment']
            mid, aid = candidate['messageId'], candidate['attachmentId']
            verified = candidate['verifiedApproverIds']
            if attachment.get('size', 0) > MAX_BYTES:
                raise DiagnosticError('Attachment exceeds size limit')
            pixels, width, height = download_image(attachment['url'])
            digest = hashlib.sha256(pixels).hexdigest()
            filename = f'{mid}-{aid}-{digest}.webp'
            (stage / 'images' / filename).write_bytes(pixels)
            items.append({'id': f'{mid}-{aid}', 'file': 'images/' + filename,
                'sha256': digest, 'width': width, 'height': height,
                'approval': 'reaction-approved' if reaction_is_approval else ('officer-verified' if verified else 'provisional'),
                'verifiedApproverIds': verified, 'messageTimestamp': candidate['messageTimestamp'],
                'approvedAt': candidate['approvedAt'], 'sortBasis': 'discord-message-time',
                'title': 'From the SDAS crew', 'alt': 'Community screenshot shared in the SDAS Discord.'})
        manifest = {'schemaVersion': 1, 'generatedAt': datetime.now(timezone.utc).isoformat(),
            'guildId': GUILD, 'channelId': CHANNEL, 'emojiId': EMOJI,
            'publicationApproved': reaction_is_approval, 'completeHistory': True, 'galleryLimit': 25,
            'mode': 'reaction-approved-production' if reaction_is_approval else ('provisional-review' if include_provisional else 'verified-only'),
            'qualifyingImages': len(candidates),
            'messagesInspected': inspected, 'reactionMatchedMessages': reaction_messages,
            'images': items}
        (stage / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        stage.rename(destination)
    api.report(messages_inspected=inspected, images_saved=len(items), qualifying_images=len(candidates),
        officer_verified=sum(i['approval'] == 'officer-verified' for i in items), publication_approved=reaction_is_approval)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--include-provisional', action='store_true', help='Local review only; include unverified reaction matches')
    parser.add_argument('--reaction-is-approval', action='store_true', help='SDAS-authorized exact custom emoji reaction is final publication approval')
    parser.add_argument('--max-pages', type=int, default=1000)
    args = parser.parse_args()
    token = os.environ.get('DISCORD_BOT_TOKEN', '').strip()
    if not token:
        print('ERROR: DISCORD_BOT_TOKEN is not set')
        return 1
    api = SyncAPI(token)
    try:
        allowed = {snowflake(v.strip()) for v in os.environ.get('SDAS_APPROVER_IDS', '').split(',') if v.strip()}
        if args.max_pages < 1:
            raise DiagnosticError('max-pages must be positive')
        if args.reaction_is_approval and args.include_provisional:
            raise DiagnosticError('Production and provisional modes cannot be combined')
        sync(api, args.output, allowed, args.max_pages, args.include_provisional, args.reaction_is_approval)
    except Exception as error:
        api.report(result='FAILED; no complete bundle produced', error_type=type(error).__name__,
            error=str(error) if isinstance(error, DiagnosticError) else 'Details omitted to protect credentials and attachment URLs')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
