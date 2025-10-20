"""Smoke tests for the logging scaffolding introduced during the refactor."""
from infrastructure_atlas.infrastructure.logging import setup_logging


def test_setup_logging_idempotent():
    """Calling setup_logging multiple times should not raise exceptions."""
    setup_logging()
    setup_logging()
