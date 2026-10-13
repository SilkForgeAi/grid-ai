# Lets `pytest examples/demo_failing_test` find buggy.py from the repo root.
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
