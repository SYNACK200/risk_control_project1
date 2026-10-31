import datetime
import unittest
from partition_plan import month, next_month, plan


class PartitionTests(unittest.TestCase):
    def test_year_and_leap_month_boundaries(self):
        self.assertEqual(next_month(month('2026-12')),datetime.date(2027,1,1))
        self.assertEqual(next_month(month('2028-02')),datetime.date(2028,3,1))

    def test_forward_and_inverse_preserve_existing_layout(self):
        existing=[('p_before',month('2026-10')),('p202610',month('2026-11')),('p_future','MAXVALUE')]
        up,down=plan(existing,month('2027-01'))
        self.assertIn("PARTITION `p202611` VALUES LESS THAN ('2026-12-01')",up)
        self.assertIn("PARTITION `p202701` VALUES LESS THAN ('2027-02-01')",up)
        self.assertNotIn('DROP',up+down)
        self.assertNotIn('p202610',down)
        self.assertNotIn('p_before',up+down)

    def test_gaps_unknown_layout_and_unbounded_plans_stop(self):
        with self.assertRaises(ValueError): plan([('p_before',month('2026-10')),('p202611',month('2026-12')),('p_future','MAXVALUE')],month('2027-01'))
        with self.assertRaises(ValueError): plan([('other',month('2026-10')),('p_future','MAXVALUE')],month('2027-01'))
        with self.assertRaises(ValueError): plan([('p_before',month('2026-10')),('p_future','MAXVALUE')],month('2050-01'))


if __name__ == '__main__': unittest.main()
