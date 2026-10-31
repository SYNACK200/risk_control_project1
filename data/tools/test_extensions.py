import copy
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import tempfile
import unittest
from extensions.adapters import DemoRateCatalog, append_ocr, read_ocr


RATE={'bank_code':'SYNTHETIC','effective_from':'2026-01-01','effective_to':'2027-01-01','rate':'0.0000',
      'rate_unit':'DEMO_ANNUAL_FRACTION','day_count_basis':'DEMO_ONLY','source':'SYNTHETIC NOT BANK DATA','version':1}
OCR={'synthetic_only':True,'file_id':1,'parser_version':'DEMO-1','lines':[{'page_no':1,'bbox_normalized':[0.1,0.1,0.3,0.2],'confidence':0.9,'masked_text':'SYNTHETIC D*** 0000********0000'}]}


class ExtensionTests(unittest.TestCase):
    def test_rate_opt_in_and_explicit_version(self):
        with self.assertRaises(ValueError): DemoRateCatalog({'synthetic_only':True,'records':[RATE]})
        catalog=DemoRateCatalog({'synthetic_only':True,'records':[RATE]},allow_demo=True)
        self.assertEqual(catalog.lookup('SYNTHETIC','2026-10-01',1)['rate'],'0.0000')
        with self.assertRaises(LookupError): catalog.lookup('SYNTHETIC','2027-01-01',1)
        with self.assertRaises(LookupError): catalog.lookup('SYNTHETIC','2026-10-01',2)

    def test_overlapping_rate_periods_rejected(self):
        with self.assertRaises(ValueError): DemoRateCatalog({'synthetic_only':True,'records':[RATE,copy.deepcopy(RATE)]},allow_demo=True)

    def test_ocr_append_and_checksum(self):
        with tempfile.TemporaryDirectory() as directory:
            first=append_ocr(directory,OCR); second=append_ocr(directory,OCR)
            self.assertNotEqual(first,second)
            self.assertEqual(read_ocr(first),OCR)
            first.write_text(first.read_text().replace('DEMO-1','DEMO-2'))
            with self.assertRaises(ValueError): read_ocr(first)

    def test_ocr_rejects_raw_identifiers_and_bad_geometry(self):
        for key,value in [('confidence',1.1),('bbox_normalized',[0.9,0,0.2,1]),('masked_text','0'*18)]:
            document=copy.deepcopy(OCR); document['lines'][0][key]=value
            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(ValueError): append_ocr(directory,document)
                self.assertEqual(list(Path(directory).iterdir()),[])


if __name__ == '__main__': unittest.main()
