"""Native-pipe failure fixture, no network or real credentials."""
import pathlib
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import provision_core as core
from fake_provision_db import FakeDriver

if __name__ == '__main__':
    assert sys.argv[1] == 'AcceptDA01'
    driver = FakeDriver(populated=True)
    original = driver.connect
    def connect(**kwargs):
        if kwargs['user'] == 'rc_demo_app':
            raise RuntimeError(1045, 'SYNTHETIC-DO-NOT-PRINT')
        return original(**kwargs)
    driver.connect = connect
    core.dependencies = lambda: driver
    sys.exit(core.main())
