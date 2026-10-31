import unittest
from decimal import Decimal
from synthetic import mask_account, mask_name, transactions


class SyntheticTests(unittest.TestCase):
    def test_masks(self):
        self.assertEqual(mask_account('1234567890123456'), '1234********3456')
        self.assertEqual(mask_account('12345678'), '********')
        self.assertIsNone(mask_account(None))
        self.assertEqual(mask_name('Demo'), 'D***')

    def test_balance_chain(self):
        rows = list(transactions(2, 3000))
        self.assertEqual(len({r['id'] for r in rows}), 6000)
        for task in (1, 2):
            balance = Decimal('10000.00')
            for row in (r for r in rows if r['task_id'] == task):
                amount = Decimal(row['amount'])
                self.assertGreater(amount, 0)
                balance += amount if row['direction'] == 'in' else -amount
                self.assertEqual(balance, Decimal(row['balance']))
                self.assertTrue(row['txn_date'].endswith('+08:00'))


if __name__ == '__main__':
    unittest.main()
