from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.settings import Settings


def create_session_factory(settings: Settings) -> sessionmaker:
    Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{settings.database_path}", future=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    # Stash the engine on the factory so MemoryService can discover it via public attribute
    # instead of reaching into sessionmaker.kw (which is SQLAlchemy-internal).
    factory.engine = engine  # type: ignore[attr-defined]
    return factory
