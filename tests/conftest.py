from __future__ import annotations

import sys
from pathlib import Path

pytest_plugins = ("pytester",)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
