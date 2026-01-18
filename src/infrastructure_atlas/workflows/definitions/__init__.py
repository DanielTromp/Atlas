"""Pre-built workflow definitions.

Available workflows:
- esd_triage: ESD ticket triage and initial response workflow
"""

from __future__ import annotations

__all__ = [
    "create_esd_triage_workflow",
]


def __getattr__(name: str):
    if name == "create_esd_triage_workflow":
        from .esd_triage import create_esd_triage_workflow
        return create_esd_triage_workflow
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
