import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import sync_discord_screenshots as sync


class SyncTests(unittest.TestCase):
    def test_rolling_limit_and_deterministic_order(self):
        candidates = [{'messageId': str(i), 'attachmentId': str(i),
            'messageTimestamp': '2026-10-01T00:00:00+00:00', 'approvedAt': None,
            'verifiedApproverIds': []} for i in range(1, 31)]
        chosen = sync.select_images(candidates)
        self.assertEqual(len(chosen), 25)
        self.assertEqual([int(c['messageId']) for c in chosen], list(range(30, 5, -1)))
        # Known verified approval time takes precedence; unverified claims do not.
        candidates[0].update(approvedAt='2026-10-02T00:00:00+00:00', verifiedApproverIds=['444'])
        candidates[1]['approvedAt'] = '2027-10-01T00:00:00+00:00'
        chosen = sync.select_images(list(reversed(candidates)))
        self.assertEqual(chosen[0]['messageId'], '1')
        self.assertNotIn('2', [c['messageId'] for c in chosen])
        self.assertEqual(len(sync.select_images(candidates[:2])), 2)
        self.assertEqual(sync.select_images([]), [])
        newcomer = {**candidates[-1], 'messageId': '31', 'attachmentId': '31', 'messageTimestamp': '2026-10-03T00:00:00+00:00'}
        refreshed = sync.select_images(candidates + [newcomer])
        self.assertEqual(refreshed[0]['messageId'], '31')
        self.assertEqual(len(refreshed), 25)
        self.assertNotIn(chosen[-1]['messageId'], [c['messageId'] for c in refreshed])

    def test_sync_limits_files_before_download(self):
        class API:
            def get(self, path):
                if '/emojis' in path: return [{'id': sync.EMOJI, 'name': 'sdasapproved'}]
                if '/messages?' not in path: return {'guild_id': sync.GUILD}
                if 'before=' in path: return []
                return [{'id': '300', 'timestamp': '2026-10-01T00:00:00Z',
                    'attachments': [{'id': str(i), 'filename': 'shot.png', 'url': 'not-persisted'} for i in range(1, 31)],
                    'reactions': [{'emoji': {'id': sync.EMOJI}, 'count': 1}]}]
            def report(self, **fields): pass
        with tempfile.TemporaryDirectory() as root, patch.object(sync, 'approving_users', return_value=['444']), patch.object(sync, 'download_image', return_value=(b'pixels', 10, 10)) as download:
            out = Path(root) / 'bundle'
            sync.sync(API(), out, {'444'})
            result = json.loads((out / 'manifest.json').read_text())
            self.assertEqual(len(result['images']), 25)
            self.assertEqual(result['qualifyingImages'], 30)
            self.assertEqual(download.call_count, 25)
            self.assertEqual(len(list((out / 'images').iterdir())), 25)
            self.assertEqual(result['images'][0]['id'], '300-30')
            self.assertTrue(all(i['approvedAt'] is None for i in result['images']))
        with tempfile.TemporaryDirectory() as root, patch.object(sync, 'approving_users', return_value=[]), patch.object(sync, 'download_image') as download:
            out = Path(root) / 'bundle'
            sync.sync(API(), out, {'444'})
            self.assertEqual(json.loads((out / 'manifest.json').read_text())['images'], [])
            download.assert_not_called()

    def test_message_pagination(self):
        class API:
            def __init__(self): self.paths = []
            def get(self, path):
                self.paths.append(path)
                if len(self.paths) == 1: return [{'id': str(i)} for i in range(200, 100, -1)]
                if len(self.paths) == 2: return [{'id': '100'}]
                return []
        api = API()
        self.assertEqual(len(list(sync.messages(api, 3))), 101)
        self.assertIn('before=101', api.paths[1])
        self.assertIn('before=100', api.paths[2])
        with self.assertRaises(sync.DiagnosticError): list(sync.messages(API(), 1))

    def test_user_pagination_and_burst(self):
        class API:
            def get(self, path):
                if 'type=1' in path: return [{'id': '900'}]
                if 'after=100' in path: return [{'id': '101'}, {'id': '102', 'bot': True}]
                return [{'id': str(i)} for i in range(1, 101)]
        self.assertEqual(sync.approving_users(API(), '999', {'101', '102', '900'}), ['101', '900'])
        self.assertEqual(sync.approving_users(API(), '999', set()), [])

    def test_raster_conversion_and_url_rejection(self):
        from PIL import Image
        source = io.BytesIO()
        Image.new('RGB', (32, 20), 'blue').save(source, 'PNG')
        result, w, h = sync.normalize_image(source.getvalue())
        self.assertEqual((w, h), (32, 20))
        self.assertEqual(result[8:12], b'WEBP')
        with self.assertRaises(Exception): sync.normalize_image(b'<svg/>')
        for url in ['https://evil.example/attachments/a', 'http://cdn.discordapp.com/attachments/a', 'https://cdn.discordapp.com@evil.example/attachments/a']:
            with self.assertRaises(sync.DiagnosticError): sync.download_image(url)

    def test_multiple_attachments_identity_and_atomic_output(self):
        class API:
            def get(self, path):
                if '/emojis' in path: return [{'id': sync.EMOJI, 'name': 'sdasapproved'}]
                if '/messages?' not in path: return {'guild_id': sync.GUILD}
                if 'before=' in path: return []
                return [
                    {'id': '200', 'attachments': [{'id': '1', 'filename': 'a.png', 'url': 'not-persisted'}, {'id': '2', 'filename': 'b.jpg', 'url': 'not-persisted'}], 'reactions': [{'emoji': {'id': sync.EMOJI}, 'count': 1}]},
                    {'id': '199', 'attachments': [{'id': '3', 'filename': 'c.png'}], 'reactions': [{'emoji': {'id': '999', 'name': 'sdasapproved'}, 'count': 1}]}]
            def report(self, **fields): pass
        with tempfile.TemporaryDirectory() as root, patch.object(sync, 'approving_users', return_value=[]), patch.object(sync, 'download_image', return_value=(b'pixels', 10, 10)):
            out = Path(root) / 'bundle'
            sync.sync(API(), out, set(), include_provisional=True)
            manifest = json.loads((out / 'manifest.json').read_text())
            self.assertEqual(len(manifest['images']), 2)
            self.assertFalse(manifest['publicationApproved'])
            self.assertTrue(all(i['approval'] == 'provisional' for i in manifest['images']))
            self.assertNotIn('not-persisted', json.dumps(manifest))
            for item in manifest['images']:
                self.assertEqual(hashlib.sha256((out / item['file']).read_bytes()).hexdigest(), item['sha256'])
            with patch.object(sync, 'approving_users', return_value=['444']):
                sync.sync(API(), Path(root) / 'verified', {'444'})
                verified = json.loads((Path(root) / 'verified/manifest.json').read_text())
                self.assertTrue(all(i['approval'] == 'officer-verified' for i in verified['images']))
                self.assertFalse(verified['publicationApproved'])
            with patch.object(sync, 'download_image', side_effect=sync.DiagnosticError('download failed')):
                with self.assertRaises(sync.DiagnosticError): sync.sync(API(), Path(root) / 'failed', set(), include_provisional=True)
                self.assertFalse((Path(root) / 'failed').exists())


if __name__ == '__main__': unittest.main()
