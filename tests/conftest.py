import importlib.util
import sys
from pathlib import Path

import pytest

MAIN_PATH = Path(__file__).parent.parent / "main.py"


@pytest.fixture
def load_main(monkeypatch):
    """Import a fresh copy of main.py with DATA_PORTAL_API_KEY set (or unset)."""
    loaded: list[str] = []

    def _load(api_key: str | None = None):
        if api_key is None:
            monkeypatch.delenv("DATA_PORTAL_API_KEY", raising=False)
        else:
            monkeypatch.setenv("DATA_PORTAL_API_KEY", api_key)
        name = f"main_under_test_{len(loaded)}"
        spec = importlib.util.spec_from_file_location(name, MAIN_PATH)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        loaded.append(name)
        spec.loader.exec_module(module)
        return module

    yield _load
    for name in loaded:
        sys.modules.pop(name, None)
