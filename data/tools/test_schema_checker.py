"""Check that the independent checker rejects drift using isolated file copies."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]


class SchemaCheckerTests(unittest.TestCase):
    def run_check(self,change=None):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); core=root/'data/core'; core.mkdir(parents=True)
            (root/'data/tools').mkdir()
            (root/'contract.md').write_bytes((ROOT/'contract.md').read_bytes())
            for name in ('schema.sql','schema.json','physical_dictionary.md'):
                content=(ROOT/'data/core'/name).read_text(encoding='utf-8')
                if change is not None: content=change(name,content)
                (core/name).write_text(content,encoding='utf-8')
            script=root/'data/tools/check_core.py'; script.write_bytes((ROOT/'data/tools/check_core.py').read_bytes())
            return subprocess.run([sys.executable,'-B',str(script)],stdout=subprocess.PIPE,stderr=subprocess.PIPE).returncode

    def test_baseline_and_renamed_field(self):
        self.assertEqual(self.run_check(),0)
        self.assertNotEqual(self.run_check(lambda name,text:text.replace('  `id` BIGINT','  `unexpected` BIGINT',1) if name=='schema.sql' else text),0)

    def test_dictionary_type_drift_and_extra_table(self):
        self.assertNotEqual(self.run_check(lambda name,text:text.replace('DECIMAL(18,2) NULL','DECIMAL(18,3) NULL',1) if name=='physical_dictionary.md' else text),0)
        self.assertNotEqual(self.run_check(lambda name,text:text+'\nCREATE TABLE extra (id INT);\n' if name=='schema.sql' else text),0)


if __name__ == '__main__': unittest.main()
