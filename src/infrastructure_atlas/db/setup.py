from __future__ import annotations

from alembic import command
from alembic.config import Config

from ..env import project_root
from .config import get_database_url


def _alembic_config() -> Config:
    root = project_root()
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", get_database_url())
    return cfg


def init_database() -> None:
    cfg = _alembic_config()
    command.upgrade(cfg, "head")


def alembic_revision(message: str) -> None:
    cfg = _alembic_config()
    command.revision(cfg, message=message, autogenerate=True)


def alembic_downgrade(target: str) -> None:
    cfg = _alembic_config()
    command.downgrade(cfg, target)
