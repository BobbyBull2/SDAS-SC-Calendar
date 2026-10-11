import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path

spec = importlib.util.spec_from_file_location("orgnews", Path(__file__).resolve().parents[1] / "scripts" / "publish_org_news.py")
news = importlib.util.module_from_spec(spec)
spec.loader.exec_module(news)

CHANNEL = "1519103863758520471"
GUILD = "1518410019249459236"
START = datetime(2026, 10, 11, tzinfo=timezone.utc)

def msg(mid, text, date="2026-10-11T20:00:00Z"):
    return {"id": mid, "type": 0, "content": text, "timestamp": date, "author": {"bot": False}}

class NewsTests(unittest.TestCase):
    def test_older_news_does_not_publish(self):
        entries = [msg("1558000000000000001", "Fresh message"),
                   msg("1558000000000000002", "Old message", "2026-10-10T20:00:00Z")]
        selected = news.select_posts(entries, CHANNEL, START)
        self.assertEqual([x["title"] for x in selected], ["Fresh message"])

    def test_wrong_channel_rejected(self):
        def getter(path, token):
            return {"guild_id": GUILD, "name": "general", "type": 0}
        with self.assertRaises(ValueError):
            news.collect("test", CHANNEL, START, getter=getter)

    def test_unapproved_channel_id_rejected(self):
        with self.assertRaisesRegex(ValueError, "approved SDAS"):
            news.collect("test", "1519103965290168560", START, getter=lambda path, token: [])

    def test_plain_text_normalized(self):
        items = news.select_posts([msg("1558000000000000001", "# Org announcement\nHello everyone")], CHANNEL, START)
        self.assertEqual(items[0]["title"], "Org announcement")
        self.assertEqual(items[0]["body"], "Hello everyone")

    def test_rolling_three_month_window(self):
        from datetime import timedelta
        now = datetime(2026, 10, 11, 22, tzinfo=timezone.utc)
        cutoff = now - timedelta(days=90)
        recent = (now - timedelta(days=89)).isoformat()
        expired = (now - timedelta(days=91)).isoformat()
        entries = [msg("1558000000000000001", "Recent archive", recent),
                   msg("1558000000000000002", "Expired archive", expired)]
        self.assertEqual([x["title"] for x in news.select_posts(entries, CHANNEL, cutoff)], ["Recent archive"])

    def test_feed_archive_can_include_more_than_twelve(self):
        rows = [msg(str(1558000000000000000 + i), f"Post {i}") for i in range(20)]
        self.assertEqual(len(news.select_posts(rows, CHANNEL, START)), 10)

    def test_fifo_oldest_out_first(self):
        rows = [msg(str(1558000000000000000 + i), f"Post {i}") for i in range(12)]
        chosen = news.select_posts(rows, CHANNEL, START)
        self.assertEqual(len(chosen), 10)
        self.assertEqual(chosen[0]["title"], "Post 2")
        self.assertEqual(chosen[-1]["title"], "Post 11")

    def test_discord_attachment_image_and_art_only_post(self):
        art = "https://cdn.discordapp.com/attachments/1519103863758520471/1558000000000000020/photo.png"
        row = msg("1558000000000000020", "")
        row["attachments"] = [{"content_type":"image/png", "url":art, "filename":"photo.png"}]
        chosen = news.select_posts([row], CHANNEL, START)
        self.assertEqual(chosen[0]["title"], "SDAS artwork")
        self.assertEqual(chosen[0]["_imageSource"], art)
        self.assertFalse(news.safe_image_url("https://other-site.example/attachments/a/b.png"))

    def test_artwork_feed_url_is_hosted_and_source_is_omitted(self):
        import tempfile
        import json
        art = "https://cdn.discordapp.com/attachments/1519103863758520471/1558000000000000020/photo.png"
        row = msg("1558000000000000020", "Art news")
        row["attachments"] = [{"content_type":"image/png", "url":art}]
        chosen = news.select_posts([row], CHANNEL, START)
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path
            folder=Path(tmp)
            self.assertEqual(news.publish_art(chosen,folder,downloader=lambda url:b"fake-webp-test"),1)
            self.assertIn("imageUrl",chosen[0])
            self.assertNotIn("_imageSource",chosen[0])
            self.assertNotIn("cdn.discordapp.com",json.dumps(chosen))
            self.assertEqual(news.publish_art(chosen,folder,downloader=lambda url:b""),0)

    def test_timestamp_requires_timezone(self):
        with self.assertRaises(ValueError):
            news.date_utc("2026-10-11T20:00:00")

if __name__ == "__main__":
    unittest.main()
