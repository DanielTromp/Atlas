"""Context models shared across LangChain agents."""

from __future__ import annotations

import json
from collections.abc import MutableMapping
from dataclasses import dataclass, field
from typing import Any

__all__ = ["AgentContext"]


@dataclass(slots=True)
class AgentContext:
    """Lightweight container for chat session context."""

    session_id: str | None = None
    user: str | None = None
    variables: MutableMapping[str, Any] = field(default_factory=dict)

    def as_prompt_fragment(self) -> str:
        """Render the context as a deterministic prompt fragment."""

        lines: list[str] = []
        if self.session_id:
            lines.append(f"session.id = {self.session_id}")
        if self.user:
            lines.append(f"session.user = {self.user}")
        if self.variables:
            try:
                payload = json.dumps(dict(self.variables), sort_keys=True, ensure_ascii=True)
            except Exception:
                payload = str(dict(self.variables))
            lines.append(f"context.vars = {payload}")
        if not lines:
            return "(no additional context)"
        return "\n".join(lines)
