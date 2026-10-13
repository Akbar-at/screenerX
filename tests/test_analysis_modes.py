import unittest
from tests.test_reporting_tables import company
from screenerx.analysis_modes import parse_modes,select_analysis
from screenerx.reporting import narrative,figure

class AnalysisModeTests(unittest.TestCase):
 def test_modes_are_canonical_and_invalid_choices_fail(self):
  self.assertEqual(parse_modes('broker+tech'),('technical','broker'))
  with self.assertRaises(ValueError):parse_modes('unknown')
 def test_missing_fundamentals_do_not_gate_technical(self):
  c=select_analysis(company(),('technical',));info=narrative(c)
  self.assertEqual(c['_analysis_components']['technical']['status'],'AVAILABLE')
  self.assertNotIn('DDM',info['text']);self.assertNotIn('Valuasi belum direview',info['text'])
 def test_fundamental_has_no_entry_or_technical_recommendation(self):
  c=select_analysis(company(),('fundamental',));info=narrative(c)
  self.assertEqual(c['_analysis_components']['fundamental']['status'],'PARTIAL_ESTIMATES')
  self.assertIn('RIM',info['text']);self.assertNotIn('Entry',info['text']);self.assertNotIn('SMA20',info['text'])
 def test_combination_preserves_available_analysis_with_broker_on_hold(self):
  c=select_analysis(company(),parse_modes('technical+broker'));info=narrative(c)
  self.assertEqual(c['_analysis_components']['technical']['status'],'AVAILABLE')
  self.assertIn('ON_HOLD',info['text']);self.assertIn('SMA20',info['text']);self.assertNotIn('DDM',info['text'])
 def test_selected_numbers_appear_in_image_and_text(self):
  import matplotlib.pyplot as plt
  for mode in ('technical','fundamental','broker','technical+fundamental','all'):
   c=select_analysis(company(),parse_modes(mode));info=narrative(c);fig=figure(c,[])
   try:
    values={cell.get_text().get_text() for a in fig.axes for t in a.tables for cell in t.get_celld().values()}
    for title,rows in info['tables']:
     for key,value in rows:self.assertIn(key,values);self.assertIn(value,values);self.assertIn(value,info['text'])
   finally:plt.close(fig)
