# SDAS #org-news -> News Wire (approval-gated)

**Status: Automatic publication has been enabled on main. History expansion to the previous 90 days is under review in this branch.**

Confirmed Discord `#org-news` channel ID: `1519103863758520471`. The previously provided `1519103965290168560` is the existing Pipeline/game-news channel and is **not** authorized for this feed. The collector refuses any other channel ID.

## Planned behavior
- Reuses the existing Discord bot token secret in this Calendar repository.
- Runs every hour, reads only the single channel named `org-news` in the official SDAS guild.
- Selects up to 100 latest human-authored text announcements in a **rolling 90-day window**.
- Includes the preceding 90 days of channel history; older messages expire automatically. Excludes bot/webhook posts, attachments and rich embeds.
- Removes direct Discord @user/@role mentions from public text, renders text without HTML, and links to the original messages.
- Updates `org-news/feed.json` on the repository default branch and publishes it to the existing GitHub Pages site.
- The SDAS *preview website* can read that feed, refreshing every ten minutes, and falls back to labeled sample posts when no feed exists.
- Public users can view the feed URL even if the Discord channel itself requires membership. Treat every mirrored post as public.

## Activation requires approval by an org officer
1. Confirm that posts to `#org-news` are explicitly intended for public display on SDAS.space.
2. Use confirmed channel ID `1519103863758520471` (runtime verifies channel name `org-news` and SDAS guild).
3. Note which authors can post. This prototype excludes bot/webhook messages by design.
4. The user has approved including historic posts up to 90 days old.
5. Review the publishing and removal policy before enabling.

Then merge the draft PR and configure GitHub **repository variables** in `BobbyBull2/SDAS-SC-Calendar` > Settings > Secrets and variables > Actions > Variables:

- `SDAS_ORG_NEWS_CHANNEL_ID`: `1519103863758520471` (exact, enforced at runtime).
- `SDAS_ORG_NEWS_PUBLIC_ENABLED`: `true` only after the above approvals; unset or `false` to stop the workflow.

The existing `DISCORD_BOT_TOKEN` repository secret is reused. **Never paste it in chat or commit it.** The bot must have access to the channel, `View Channel` and `Read Message History` permissions and access to message content (the Discord privileged Message Content intent if required). Do not grant administrator rights.

## Stopping / removing content
- Disable the workflow immediately with `SDAS_ORG_NEWS_PUBLIC_ENABLED=false`.
- Note that disabling collection does not remove previously published JSON. For urgent takedowns, delete or replace `org-news/feed.json` on main and redeploy GitHub Pages; remove cached content if applicable.
- Configure an explicit retention and approval policy before public launch.

## Validation
- Run `python -m unittest discover -s tests -p test_org_news.py -v` without Discord secrets.
- Check the repo's workflow `Validate SDAS Org News Publisher` on PR.
- After approval, manually run `Publish SDAS Org News`, verify it read the correct channel and feed contains only approved posts, and check the SDAS *preview* website before any production website merge.

## Separation of environments
- The Calendar repository's new collector and scheduled workflow remain on an unmerged draft PR until approved.
- The Website repository's News Wire implementation remains in its independent draft PR #8 and Cloudflare review branch.
- Nothing in this proposal changes `https://sdas.space` or the existing calendar subscription or screenshots.
