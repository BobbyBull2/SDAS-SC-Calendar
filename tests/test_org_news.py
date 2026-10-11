import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path

spec = importlib.util.spec_from_file_location("orgnews", Path(__file__).resolve().parents[1] / "scripts" / "publish_org_news.py")
news = importlib.util.module_from_spec(spec)
spec.loader.exec_module(news)

CHANNEL = "1519105573067686000"
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

    def test_plain_text_normalized(self):
        items = news.select_posts([msg("1558000000000000001", "# Org announcement\nHello everyone")], CHANNEL, START)
        self.assertEqual(items[0]["title"], "Org announcement")
        self.assertEqual(items[0]["body"], "Hello everyone")

    def test_timestamp_requires_timezone(self):
        with self.assertRaises(ValueError):
            news.date_utc("2026-10-11T20:00:00")

if __name__ == "__main__":
    unittest.main()
