"""Core protocol fixture. In-memory metadata only, no live connection."""
import pathlib
import sys
import tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import core_schema as core
from test_core_schema import Driver

if __name__ == '__main__':
    driver = Driver()
    if sys.argv[1] == 'CoreVerify':
        driver.objects = [(core.database_for(t), t, 'BASE TABLE') for t in core.artifacts()[0]] + [('rc_demo_biz','alembic_version','BASE TABLE')]
    core.dependencies = lambda: driver
    if sys.argv[1] == 'CoreApply':
        schema, ddl, digest = core.artifacts()
        verified = core.verify(driver.cursor(), schema, ddl)
        original = core.DATA
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory); (root / 'evidence').mkdir()
            for name in ('core/schema.sql','core/schema.json','migrations/env.py','migrations/versions/0001_core.py'):
                target = root / name; target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((original / name).read_bytes())
            core.DATA = root
            core.artifacts = lambda: (schema, ddl, digest)
            core.require_da01 = lambda: 'SYNTHETIC-RECEIPT'
            core.migration_dependencies_ready = lambda: True
            core.migration_upgrade = lambda raw: verified
            code = core.main()
        sys.exit(code)
    sys.exit(core.main())
