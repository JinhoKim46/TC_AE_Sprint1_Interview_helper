import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

from interview_app.db import init_db


@pytest.fixture
def engine():
    """A fresh in-memory database per test. StaticPool keeps the single in-memory
    connection alive; otherwise each new connection would see an empty database."""
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(eng)
    yield eng
    SQLModel.metadata.drop_all(eng)
