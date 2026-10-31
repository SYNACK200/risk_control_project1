import unittest
from verify_live import column_matches


class MetadataTests(unittest.TestCase):
    def test_decimal_nullability_and_defaults(self):
        column=('amount','decimal(18,2)','NO','',None,None,None)
        self.assertTrue(column_matches('DECIMAL(18,2) NOT NULL',column))
        self.assertFalse(column_matches('DECIMAL(18,2) NULL',column))
        self.assertFalse(column_matches('DECIMAL(30,8) NOT NULL',column))
        self.assertFalse(column_matches('DECIMAL(18,2) NOT NULL',column[:-1]+('0.00',)))

    def test_boolean_and_auto_increment(self):
        self.assertTrue(column_matches('BOOLEAN NULL',('flag','tinyint(1)','YES','',None,None,None)))
        self.assertTrue(column_matches('BIGINT UNSIGNED NOT NULL AUTO_INCREMENT',('id','bigint unsigned','NO','auto_increment',None,None,None)))
        self.assertFalse(column_matches('BIGINT UNSIGNED NOT NULL',('id','bigint unsigned','NO','auto_increment',None,None,None)))

    def test_sensitive_hash_charset_and_text_collation(self):
        self.assertTrue(column_matches('CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL',('sha256','char(64)','NO','','ascii','ascii_bin',None)))
        self.assertFalse(column_matches('VARCHAR(255) NULL',('name','varchar(255)','YES','','latin1','latin1_swedish_ci',None)))


if __name__ == '__main__': unittest.main()
