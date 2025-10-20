from __future__ import annotations

import importlib
import os
from tempfile import TemporaryDirectory

from infrastructure_atlas.api.app import (
    SuggestionCommentCreate,
    SuggestionCreate,
    SuggestionLikeRequest,
    suggestions_add_comment,
    suggestions_create,
    suggestions_delete,
    suggestions_detail,
    suggestions_like,
    suggestions_list,
)

app_module = importlib.import_module("infrastructure_atlas.api.app")


def test_suggestions_crud_flow():
    tmp = TemporaryDirectory()
    try:
        os.environ["NETBOX_DATA_DIR"] = tmp.name
        os.environ["ATLAS_API_TOKEN"] = ""
        app_module.API_TOKEN = ""

        initial = suggestions_list()
        assert initial["total"] == 0
        assert isinstance(initial["meta"], dict)

        created = suggestions_create(
            SuggestionCreate(
                title="Improve backups",
                summary="Use incremental uploads",
                classification="Must have",
            )
        )
        suggestion_id = created["item"]["id"]
        assert created["item"]["title"] == "Improve backups"

        liked = suggestions_like(suggestion_id, SuggestionLikeRequest(delta=2))
        assert liked["item"]["likes"] == 2

        commented = suggestions_add_comment(suggestion_id, SuggestionCommentCreate(text="Agreed"))
        assert commented["comment"]["text"] == "Agreed"

        detail = suggestions_detail(suggestion_id)
        assert detail["item"]["id"] == suggestion_id
        assert "meta" in detail

        deleted_resp = suggestions_delete(suggestion_id)
        assert deleted_resp["ok"] is True
    finally:
        tmp.cleanup()
        os.environ.pop("NETBOX_DATA_DIR", None)
        os.environ.pop("ATLAS_API_TOKEN", None)
