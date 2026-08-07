import sys
from pathlib import Path

# Ensure the repository root is importable so tests can use package-style imports
# (e.g. `from tests.unit.test_m3_query import ...`) regardless of pytest's rootdir.
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
