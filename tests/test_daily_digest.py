import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image,PdfParser
from screenerx.daily_digest import prepare_daily_digest


class DailyDigestTests(unittest.TestCase):
    def test_two_bubbles_have_short_caption_and_all_chart_pages(self):
        report={'as_of':'2026-10-13','requested_slots':10,'universe_count':957,
                'top10':[{'ticker':'BMRI','execution_readiness':{'reward_risk_passed':False}}],
                'idx_screening':{'counts':{'available':866}}}
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);png=root/'overview.png';stock=root/'stock.png'
            Image.new('RGB',(100,80),'white').save(png);Image.new('RGB',(100,160),'white').save(stock)
            with patch('screenerx.daily_digest.render_top',return_value={'png':png,'analyses':[{'chart':str(stock)}]}) as renderer:
                parts=prepare_daily_digest(SimpleNamespace(report=report),root,'2026-10-14')
                self.assertEqual([p['kind'] for p in parts],['photo','document'])
                self.assertLessEqual(len(parts[0]['caption']),1024)
                self.assertIn('Setup R/R lolos: 0/1',parts[0]['caption'])
                self.assertIn('866/957',parts[0]['caption'])
                self.assertIn('2026-10-13',parts[0]['caption'])
                pdf=Path(parts[1]['path'])
                with PdfParser.PdfParser(filename=str(pdf),mode='rb') as document:self.assertEqual(len(document.pages),2)
                self.assertFalse(renderer.call_args.kwargs['include_pdf'])
                self.assertFalse(pdf.with_suffix('.tmp').exists())

    def test_empty_shortlist_is_not_padded_with_stock_messages(self):
        report={'as_of':'2026-10-13','requested_slots':10,'universe_count':1,'top10':[]}
        with tempfile.TemporaryDirectory() as directory:
            png=Path(directory)/'overview.png';Image.new('RGB',(100,80),'white').save(png)
            with patch('screenerx.daily_digest.render_top',return_value={'png':png,'analyses':[]}):
                parts=prepare_daily_digest(SimpleNamespace(report=report),directory,'2026-10-14')
                self.assertEqual(len(parts),2);self.assertIn('Belum ada kandidat',parts[0]['caption'])
