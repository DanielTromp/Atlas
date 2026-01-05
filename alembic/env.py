from __future__ import annotations

import importlib.util
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# Add src to path for imports
root = Path(__file__).resolve().parents[1]
src_path = str(root / "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)


def _load_models_directly():
    """Load models.py directly without triggering package __init__.py imports.

    This avoids the circular import where:
    infrastructure_atlas/__init__.py -> cli.py -> api/app.py -> init_database() -> alembic
    """
    models_path = root / "src" / "infrastructure_atlas" / "db" / "models.py"
    spec = importlib.util.spec_from_file_location("_alembic_models", models_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load models from {models_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["_alembic_models"] = module
    spec.loader.exec_module(module)
    return module.Base


def _get_database_url() -> str:
    """Get database URL directly to avoid circular import."""
    url = os.getenv("ATLAS_DB_URL", "").strip()
    if url:
        return url
    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "atlas.sqlite3"
    return f"sqlite:///{path.as_posix()}"


# Target metadata for autogenerate - load models directly to avoid circular imports
Base = _load_models_directly()
target_metadata = Base.metadata

# Alembic Config object
config = context.config

# Setup logging from config file
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set database URL
config.set_main_option("sqlalchemy.url", _get_database_url())


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
