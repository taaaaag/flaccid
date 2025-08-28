# Ensure the project src/ directory is on sys.path for imports during tests
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if SRC.exists() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Optionally, reduce Rich tracebacks noise in tests
os.environ.setdefault("PYTHONWARNINGS", "ignore")
