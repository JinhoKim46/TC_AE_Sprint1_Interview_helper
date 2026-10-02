import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

from interview_app.config import Settings, get_settings
from interview_app.db import init_db


@pytest.fixture(autouse=True)
def _no_developer_env_file(request, monkeypatch):
    """Unit tests must not depend on the developer's real `.env`: a model override or a lowered limit
    there would make tests pass on one machine and fail on another (or in CI, which has no `.env`).
    Live tests are the exception, they need the API key from it."""
    if request.node.get_closest_marker("live"):
        yield
        return
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    # get_settings() caches one Settings object; clear it so no test sees one built from the real .env.
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def engine():
    """A fresh in-memory database per test. StaticPool keeps the single in-memory
    connection alive; otherwise each new connection would see an empty database."""
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(eng)
    yield eng
    SQLModel.metadata.drop_all(eng)
