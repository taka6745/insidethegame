"""Developer commands (not deployed); run from narrative-engine/. Test doubles come from tests/doubles."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
