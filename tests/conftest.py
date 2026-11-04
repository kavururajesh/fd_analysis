import os
import sys
import tempfile
from pathlib import Path

os.environ["LLM_MODE"] = "offline"
os.environ["BROWSER_CHANNEL"] = "chromium"
os.environ["SOURCE_MODE"] = "local"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest


@pytest.fixture()
def store(tmp_path):
    from src.memory.store import Store
    return Store(tmp_path / "t.db")


@pytest.fixture(scope="session")
def fixture_site():
    from src.localsite import fixture_server
    fixture_server.set_drift(False)
    return fixture_server.start()


@pytest.fixture()
def browser():
    from src.tools.browser import BrowserManager, BrowserUnavailable
    b = BrowserManager()
    try:
        b._start()
    except BrowserUnavailable:
        pytest.skip("no browser available")
    yield b
    b.close()


@pytest.fixture()
def files(tmp_path):
    from src.datastore.files import DatasetFiles
    return DatasetFiles(tmp_path / "current", tmp_path / "staging")
