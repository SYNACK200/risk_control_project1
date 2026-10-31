import unittest
from benchmark import summarize

DESCRIPTION = [(name,) for name in ('id','select_type','table','partitions','type','possible_keys','key')]


class BenchmarkTests(unittest.TestCase):
    def test_possible_key_without_selected_key_fails(self):
        plan = (1,'SIMPLE','txn',None,'ALL','ix_txn_task_date',None)
        self.assertFalse(summarize([1]*100,100,[plan],DESCRIPTION,'ix_txn_task_date')['accepted'])

    def test_p99_threshold_and_actual_selected_key(self):
        plan = (1,'SIMPLE','txn','p202610','ref','ix_txn_task_date','ix_txn_task_date')
        self.assertTrue(summarize([2]*100,100,[plan],DESCRIPTION,'ix_txn_task_date')['accepted'])
        result = summarize([2]*98+[301,302],100,[plan],DESCRIPTION,'ix_txn_task_date')
        self.assertEqual(result['p99_ms'],301)
        self.assertFalse(result['accepted'])

    def test_empty_or_insufficient_samples_rejected(self):
        for samples, rows, plans in [([1]*99,1,[(1,)]),([1]*100,0,[(1,)]),([1]*100,1,[])]:
            with self.assertRaises(ValueError): summarize(samples,rows,plans,DESCRIPTION,'ix')


if __name__ == '__main__': unittest.main()
