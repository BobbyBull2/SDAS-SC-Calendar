# Screenshot review sync (separate from calendar automation)

`sync-discord-screenshots.yml` is manual-only and artifact-only. It does not
commit, publish, deploy, or modify calendar workflows. Use the existing Actions
secret `DISCORD_BOT_TOKEN`; never download that secret or create a local token file.

## Review procedure

1. Review this feature branch before authorizing its push and an Actions run.
2. Once Bobby/Fox's Discord **numeric user IDs** are confirmed, configure the
   repository Actions variable `SDAS_APPROVER_IDS` as comma-separated IDs. Never
   infer IDs from usernames, emoji ownership, or permissions. An empty allowlist
   safely leaves every image provisional, even though reacting users are queried.
3. Run **Prepare Discord Screenshot Review Bundle** on the reviewed branch.
4. Download/extract `sdas-screenshot-review-<run-id>` with authenticated GitHub
   access. Artifacts expire after 90 days: they are transport, not permanent hosting.
5. Import the extracted bundle into the website using its local importer:
   `node scripts/import-screenshots.mjs /absolute/path/to/bundle`.
   The importer saves durable local image copies, not expiring Discord URLs.
6. Review locally. No publication path is enabled by this workflow. Identity
   verification and approval to publish are distinct: every generated bundle has
   `publicationApproved: false`, including those with verified reacting officers.

## Data behavior

- Discord API v10; exact guild/channel/emoji IDs validated each run.
- Full history in 100-message pages, stopping at an empty page. Safety page caps
  fail the run rather than silently yielding an incomplete gallery.
- Every image attachment on a reaction-matched message is included. Reactions
  apply to the whole message. Embeds/linked images are not attachment screenshots.
- Normal and burst reactions are paginated separately; bots cannot approve.
- CDN downloads have no Bot header and cannot redirect. Images are size/pixel
  bounded, decoded and normalized to WebP (first frame for animated inputs), with
  metadata stripped. Invalid/unsupported images fail the complete snapshot.
- Content-hashed filenames, dimensions, original message/attachment identifiers,
  and only matched approver IDs are retained. No source URLs, message text, full
  user lists, or credentials are stored. API status/errors are logged safely.
- A complete scan is not a transactional Discord snapshot: messages/reactions
  may change during a run. Future automated publication must resync before release.
- Removed reactions/messages disappear from the next complete manifest. Importing
  replaces the active local snapshot and preserves the previous bundle as backup.

Future work after review: authorize publication and its storage destination, then
add scheduled sync/review automation. Do not schedule automatic public release of
provisional candidates. No new paid services or third-party gallery platform is
needed: this uses existing Actions, Discord REST, and maintained Pillow.

## Local checks

Install `scripts/screenshot-requirements.txt` in an isolated Python environment.
Run `python -m unittest discover -s tests -p 'test_screenshot_sync.py'`.
Tests use synthetic data only and never contact Discord.

## Rolling 25-image gallery

The collector now selects and downloads **at most 25** qualifying attachments.
It fully scans message history and verifies reacting user IDs before selection.
Additional attachments on the same message qualify independently; numeric message
and attachment IDs provide descending stable tie-breakers. Each new snapshot
replaces the active set, so a new qualifying image displaces the oldest. Discord
originals are never modified or deleted.

Verified-only mode is the default and requires `SDAS_APPROVER_IDS`. For the local
candidate preview, explicitly select the workflow's `include_provisional` input,
or pass `--include-provisional`. Provisional entries can then participate in the
25-image review set but cannot be published by this workflow or production UI.

Discord's REST reaction-user endpoint exposes **no reaction timestamps**. Current
snapshots therefore write `approvedAt: null`, retain the actual message timestamp
(or its snowflake-derived equivalent), and set `sortBasis: discord-message-time`.
Never call polling time or first observation time the actual approval time. The
ordering function supports a known approval timestamp only for verified identities,
but a trusted reaction-event timestamp source would be needed to supply it. Such
a Gateway event recorder is not part of this read-only snapshot integration.

A bundle contains only the selected files and a manifest with `galleryLimit: 25`.
Old local snapshots remain as review backups, not active gallery entries. A failed
sync does not produce a partial replacement. The workflow is still manual-only,
unpushed and inactive locally; real automatic publication requires separate review.
