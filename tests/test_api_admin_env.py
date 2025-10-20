from __future__ import annotations

import os

from infrastructure_atlas.api.app import admin_env_settings


def test_admin_env_settings_response_shape():
    os.environ["BACKUP_ENABLE"] = "1"
    os.environ["BACKUP_TYPE"] = "local"
    os.environ["BACKUP_LOCAL_PATH"] = "custom_backups"

    payload = admin_env_settings()
    assert "settings" in payload
    assert "backup" in payload
    assert isinstance(payload["settings"], list)
    assert payload["backup"]["enabled"] is True
    assert payload["backup"]["type"] == "local"
    assert payload["backup"]["target"] == "custom_backups"

    os.environ.pop("BACKUP_ENABLE", None)
    os.environ.pop("BACKUP_TYPE", None)
    os.environ.pop("BACKUP_LOCAL_PATH", None)
