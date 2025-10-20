"""Base Pydantic models configured for domain interoperability."""
from __future__ import annotations

from pydantic import BaseModel


class DomainModel(BaseModel):
    """Common configuration for DTOs created from domain entities."""

    model_config = {
        "from_attributes": True,
        "populate_by_name": True,
        "str_strip_whitespace": True,
    }

    def dict_clean(self) -> dict[str, object]:
        """Return a dict without None values for cleaner responses."""
        return {k: v for k, v in self.model_dump().items() if v is not None}
