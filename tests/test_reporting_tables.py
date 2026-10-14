import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from screenerx.reporting import figure, metric_tables, narrative, render_stock
from screenerx.telegram_bot import chunks, telegram_html


def company():
    return {'ticker':'TEST','as_of':'2026-10-12','close':350,'coverage_complete':False,
            'technical':{'sma20':398.7,'sma60':325,'macd':9.7,'macd_signal':17.31,'rsi':45.3,
                'stoch_k':20.5,'stoch_d':21.4,'volume_multiple':.82,'atr':32.81,'return20':-.222},
            'valuation':{'financial_provider':'yfinance','statement_date':'2025-12-31','ddm':None,
                'rim':416,'eva':369,'fair_value':392,'bear_value':276,'bull_value':498,
                'current_mos':.107,'dispersion':.12,'financial_currency':'USD','fx_rate':17807.5,'fx_date':'2026-10-09'},
            'required_models':['ddm','rim','eva'],'models':{'ddm':{'status':'UNAVAILABLE'}},
            'plan':{'entry_price':384,'tp1_price':388,'tp2_price':422,'stop_loss_price':364,
                'support':244,'resistance':500,'gross_rr':.2,'net_rr':.074,
                'risk_reasons':['Estimated net reward/risk below 2'],
                'cost_assumptions':{'buy_fee':.0015,'sell_fee':.0025,'entry_slippage':.001}},
            'median_turnover_idr':1703583000,
            'quality':{'liquidity_floor':{'evidence':{'minimum':5000000000}}},
            'failed_quality_checks':[{'reason':'Liquidity below threshold or missing'}]}


class NumericalReportingTests(unittest.TestCase):
    def test_every_formatted_metric_is_in_both_text_and_image_tables(self):
        import matplotlib.pyplot as plt
        c=company(); report=narrative(c); fig=figure(c,[])
        try:
            image_values={cell.get_text().get_text() for axis in fig.axes
                          for table in axis.tables for cell in table.get_celld().values()}
            for title,rows in metric_tables(c):
                for label,value in rows:
                    self.assertIn(label,image_values)
                    self.assertIn(value,image_values)
                    self.assertIn(label,report['text'])
                    self.assertIn(value,report['text'])
            tables=dict(metric_tables(c))
            self.assertEqual(dict(tables['Likuiditas & asumsi biaya'])['Fee beli'],'0.15%')
            self.assertEqual(dict(tables['Likuiditas & asumsi biaya'])['Fee jual'],'0.25%')
            self.assertEqual(dict(tables['Fundamental & valuasi'])['DDM'],'Tidak tersedia')
            c['models']['eva']={'status':'NOT_APPLICABLE'}
            self.assertEqual(dict(dict(metric_tables(c))['Fundamental & valuasi'])['EVA'],'Tidak berlaku')
        finally: plt.close(fig)

    def test_telegram_tables_remain_balanced_and_escape_source_text(self):
        report=narrative(company())
        for part in chunks(report['text']):
            rendered=telegram_html(part)
            self.assertEqual(rendered.count('<pre>'),rendered.count('</pre>'))
            self.assertNotIn('```',rendered)
        self.assertEqual(telegram_html('A & B <bad>\n```\nX | <1\n```'),
                         'A &amp; B &lt;bad&gt;\n<pre>X | &lt;1</pre>')

    def test_sent_chart_export_preserves_all_numerical_tables(self):
        # save_chart must not remove the figure's texts/tables as the former crop did.
        import matplotlib.pyplot as plt
        c=company(); fig=figure(c,[])
        with tempfile.TemporaryDirectory() as directory:
            from screenerx.reporting import save_chart
            with patch.object(fig,'savefig') as save:
                before=list(fig.texts); save_chart(fig,c,[],Path(directory)/'chart.png')
                self.assertEqual(before,list(fig.texts))
                self.assertEqual(len([axis for axis in fig.axes if len(axis.tables)]),4)
                self.assertNotIn('bbox_inches',save.call_args.kwargs)
        plt.close(fig)

    def test_chart_only_top_export_skips_unused_combined_pdf(self):
        from types import SimpleNamespace
        from screenerx.reporting import render_top
        report={'as_of':'2026-10-13','selected_count':0,'universe_count':1,'top10':[],
                'requested_slots':10,'coverage_complete_count':0,'unfilled_slots':10}
        with tempfile.TemporaryDirectory() as directory:
            assets=render_top(SimpleNamespace(report=report),directory,include_pdf=False)
            self.assertTrue(assets['png'].exists())
            self.assertFalse(assets['pdf'].exists())
