"""Subprocess fixture: core flows against FakeDriver only, NEVER a real DB."""
import pathlib
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import provision_core as core
from fake_provision_db import FakeDriver

if __name__ == '__main__':
    core.dependencies = lambda: FakeDriver(populated=sys.argv[1] != 'Initialize')
    sys.exit(core.main())
