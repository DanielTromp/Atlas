"""Common dependency container passed to application services."""
from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker


@dataclass(slots=True)
class ServiceContext:
    """Aggregates cross-cutting dependencies for application services.

    This thin wrapper provides a transition point while the existing codebase is
    refactored into the new layered architecture. It allows us to inject shared
    resources (database sessions, config, caches) without hard-coding imports in
    service constructors.
    """

    session_factory: sessionmaker
    db_session: Session | None = None
    settings: dict[str, object] | None = None

    def with_session(self, session: Session) -> ServiceContext:
        """Return a copy of the context bound to the provided SQLAlchemy session."""
        return ServiceContext(
            session_factory=self.session_factory,
            db_session=session,
            settings=self.settings,
        )

    @contextmanager
    def session_scope(self) -> Generator[Session, None, None]:
        """Yield a SQLAlchemy session, closing it when the context creates one."""
        if self.db_session is not None:
            yield self.db_session
            return

        session = self.session_factory()
        try:
            yield session
        finally:
            session.close()
