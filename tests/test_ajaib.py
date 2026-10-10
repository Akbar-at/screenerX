import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from screenerx.ajaib import main,result_of
from screenerx.engine import InputError


class AjaibTests(unittest.TestCase):
    def test_provider_error_is_not_accepted_as_data(self):
        with self.assertRaises(InputError):result_of({'err_code':'DENIED','result':{}})

    def test_snapshots_are_saved_without_fabricated_broker_fields(self):
        universe={'err_code':'EC0000000','result':{'codes':['BBCA']}}
        info={'err_code':'EC0000000','result':{'code':'BBCA','price':6050,'timestamp':1791585009518}}
        detail={'err_code':'EC0000000','result':{'stock_detail':{'volume':87098600}}}
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'snapshots'
            responses=[(p,json.dumps(p).encode()) for p in (universe,info,detail)]
            with patch('screenerx.ajaib.fetch_json',side_effect=responses):
                self.assertEqual(main(['--tickers','BBCA','--output',str(output)]),0)
            report=json.loads((output/'api-run.json').read_text())
            self.assertEqual(report['snapshot_count'],1)
            self.assertFalse(report['broker_flow_available'])
            self.assertFalse(report['valuation_models_available'])
            self.assertFalse((output/'brokers.csv').exists())
            self.assertEqual(len(report['sources']),3)


if __name__=='__main__':unittest.main()
