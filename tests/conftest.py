import pytest

from radar.db import Database
from radar.sources import Paper


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "radar.sqlite3")
    # Las pruebas de inferencia simulada no deben emitir avisos reales en el escritorio.
    database.set_meta("settings", {"model": "gemma3:4b", "desktop_notifications": False,
                                   "unload_after_paper": False})
    return database


@pytest.fixture
def sample():
    return Paper("arxiv", "2610.00001", "1", "A paper about AI agents", ["Test Author"],
                 "We evaluate a planning method for AI agents.", "2026-10-01T12:00:00Z",
                 "2026-10-01T12:00:00Z", ["cs.AI"], "https://arxiv.org/abs/2610.00001v1",
                 "https://arxiv.org/pdf/2610.00001v1")
