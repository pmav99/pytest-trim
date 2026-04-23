from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

pytest_plugins = ("pytester",)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture
def local_plugin_importable(monkeypatch: pytest.MonkeyPatch) -> Path:
    src_dir = Path(__file__).resolve().parents[1] / "src"
    monkeypatch.syspath_prepend(str(src_dir))

    existing = os.environ.get("PYTHONPATH")
    pythonpath = str(src_dir) if not existing else f"{src_dir}{os.pathsep}{existing}"
    monkeypatch.setenv("PYTHONPATH", pythonpath)
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    return src_dir
