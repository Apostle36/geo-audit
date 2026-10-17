"""Lets a single file run directly, for example: python -m unittest tests.test_run_contract.

Discovery (python -m unittest discover -s tests) puts this directory on the path
itself; the tests import their shared fixtures and the scripts as top-level modules.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for path in (HERE, HERE.parent / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
