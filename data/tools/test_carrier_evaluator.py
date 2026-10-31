import copy
import unittest
from evaluate_carrier import evaluate


class CarrierEvaluatorTests(unittest.TestCase):
    def setUp(self):
        self.expected={'scan.png':{'sha256':'a'*64,'carrier':'image'},'screen.png':{'sha256':'b'*64,'carrier':'screenshot'}}
        self.document={'producer_version':'SYNTHETIC EVALUATOR TEST ONLY','predictions':[{'file':name,**value} for name,value in self.expected.items()]}

    def test_metrics_and_wrong_classification(self):
        self.assertTrue(evaluate(self.expected,self.document)['accepted'])
        self.document['predictions'][0]['carrier']='electronic'
        self.assertFalse(evaluate(self.expected,self.document)['accepted'])

    def test_missing_duplicate_and_changed_fixture_rejected(self):
        for mode in ('missing','duplicate','hash'):
            document=copy.deepcopy(self.document)
            if mode=='missing': document['predictions'].pop()
            elif mode=='duplicate': document['predictions'][1]=document['predictions'][0]
            else: document['predictions'][0]['sha256']='c'*64
            with self.assertRaises(ValueError): evaluate(self.expected,document)


if __name__ == '__main__': unittest.main()
