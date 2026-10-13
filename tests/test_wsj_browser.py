import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from screenerx.engine import InputError
from screenerx.wsj_browser import probe


class BrowserProbeTests(unittest.TestCase):
    def test_http_success_without_statement_is_not_accepted(self):
        for html, expected in (
            ('<html><body>Access is temporarily restricted</body></html>', 'CHALLENGED'),
            ('<html><body>Welcome</body></html>', 'STATEMENT_UNAVAILABLE'),
        ):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as folder:
                module = MagicMock()
                playwright = module.sync_playwright.return_value.__enter__.return_value
                browser = playwright.chromium.launch.return_value
                context = browser.new_context.return_value
                page = context.new_page.return_value
                page.goto.return_value.status = 200
                page.content.return_value = html
                page.locator.return_value.inner_text.return_value = html
                page.locator.return_value.count.return_value = 0
                page.url = 'https://www.wsj.com/'
                page.title.return_value = 'WSJ'
                with patch.dict('sys.modules', {'playwright.sync_api': module}), patch(
                    'screenerx.wsj_browser.time.monotonic', side_effect=[0, 2]
                ):
                    result = probe('TLKM', 'balance-sheet', Path(folder) / 'probe', wait_seconds=1)
                self.assertEqual(result['status'], expected)
                self.assertEqual(result['navigation_status'], 200)
                self.assertFalse((Path(folder) / 'probe/TLKM-balance-sheet.json').exists())
                context.close.assert_called_once()
                browser.close.assert_called_once()

    def test_existing_capture_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict('sys.modules', {'playwright.sync_api': MagicMock()}):
                with self.assertRaises(InputError):
                    probe('TLKM', 'balance-sheet', folder)
