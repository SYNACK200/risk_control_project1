import unittest
from audit_synthetic import audit
from synthetic import transactions


class AuditTests(unittest.TestCase):
    def test_valid_cardinality_and_missing_task(self):
        self.assertEqual(audit(transactions(2,10),2,10)['transactions'],20)
        with self.assertRaises(ValueError): audit(transactions(1,10),2,10)

    def test_duplicate_and_balance_damage_rejected(self):
        for field,value in [('id',1),('balance','0.00'),('counterparty_name','UNMASKED')]:
            records=list(transactions(1,10)); records[1][field]=value
            with self.assertRaises(ValueError): audit(records,1,10)


if __name__ == '__main__': unittest.main()
