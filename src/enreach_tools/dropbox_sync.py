from __future__ import annotations

import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

try:
    import dropbox
    from dropbox.exceptions import ApiError, AuthError, BadInputError
    from dropbox.files import CommitInfo, UploadSessionCursor, WriteMode
except ImportError:  # pragma: no cover - optional dependency not installed
    dropbox = None  # type: ignore
    ApiError = AuthError = BadInputError = Exception  # type: ignore
    CommitInfo = UploadSessionCursor = WriteMode = object  # type: ignore

from .env import load_env, project_root

CHUNK_SIZE = 4 * 1024 * 1024


@dataclass
class DropboxConfig:
    token: str
    base_path: str
    data_dir: Path
    enable: bool
    shared_link: str | None = None


def _load_config() -> DropboxConfig | None:
    load_env()
    enable_raw = os.getenv("DROPBOX_ENABLE_SYNC", "1").strip().lower()
    enable = enable_raw not in {"0", "false", "no", "off"}
    token = os.getenv("DROPBOX_ACCESS_TOKEN", "").strip()
    shared_link = os.getenv("DROPBOX_SHARED_LINK", "").strip() or None
    base_path = os.getenv("DROPBOX_TARGET_FOLDER", "").strip()
    data_dir_env = os.getenv("NETBOX_DATA_DIR", "data")
    data_dir = Path(data_dir_env) if os.path.isabs(data_dir_env) else (project_root() / data_dir_env)

    if not enable:
        return None
    if not token or dropbox is None:
        return None
    base = base_path.rstrip("/") if base_path else ""
    return DropboxConfig(
        token=token,
        base_path=base,
        data_dir=data_dir,
        enable=True,
        shared_link=shared_link,
    )


def _client(cfg: DropboxConfig):
    if dropbox is None:
        raise RuntimeError("Dropbox dependency not installed")
    client = dropbox.Dropbox(cfg.token, timeout=60)
    try:
        client.users_get_current_account()
    except AuthError as exc:  # pragma: no cover - requires live token
        raise RuntimeError(f"Dropbox authentication failed: {exc}") from exc
    return client


def _resolve_base_path(client, cfg: DropboxConfig) -> str:
    if cfg.base_path:
        return cfg.base_path
    if cfg.shared_link:
        try:
            meta = client.sharing_get_shared_link_metadata(url=cfg.shared_link, direct_only=True)
            path_lower = getattr(meta, "path_lower", None)
            if path_lower:
                return path_lower
        except (ApiError, BadInputError):  # pragma: no cover - requires live API
            return ""
    return ""


def _iter_paths(paths: Iterable[Path], data_dir: Path) -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    data_dir = data_dir.resolve()
    for p in paths:
        try:
            path = Path(p).resolve()
        except Exception:
            continue
        if not path.exists() or not path.is_file():
            continue
        try:
            rel = path.relative_to(data_dir)
        except ValueError:
            rel = path.name
        out.append((path, str(rel).replace("\\", "/")))
    return out


def _upload(client, dest: str, local_path: Path) -> dict:
    size = local_path.stat().st_size
    with local_path.open("rb") as fh:
        if size <= CHUNK_SIZE:
            client.files_upload(fh.read(), dest, mode=WriteMode.overwrite, mute=True)
        else:  # chunked upload for larger files
            upload_session_start_result = client.files_upload_session_start(fh.read(CHUNK_SIZE))
            cursor = UploadSessionCursor(session_id=upload_session_start_result.session_id, offset=fh.tell())
            commit = CommitInfo(path=dest, mode=WriteMode.overwrite, mute=True)
            while fh.tell() < size:
                chunk = fh.read(CHUNK_SIZE)
                if fh.tell() < size:
                    client.files_upload_session_append_v2(chunk, cursor)
                    cursor.offset = fh.tell()
                else:
                    client.files_upload_session_finish(chunk, cursor, commit)
    return {"path": dest, "size": size}


def sync_paths(paths: Sequence[Path | str], *, note: str | None = None) -> dict:
    cfg = _load_config()
    if cfg is None:
        return {"status": "skipped", "reason": "Dropbox sync disabled or not configured"}

    client = _client(cfg)
    base_path = _resolve_base_path(client, cfg)
    uploads = []
    for local_path, rel in _iter_paths([Path(p) for p in paths], cfg.data_dir):
        dest = f"{base_path}/{rel}" if base_path else f"/{rel}"
        dest = dest.replace("//", "/")
        uploaded = _upload(client, dest, local_path)
        uploads.append(uploaded)
    return {
        "status": "ok",
        "uploaded": uploads,
        "count": len(uploads),
        "note": note,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


def sync_data_dir(*, note: str | None = None) -> dict:
    cfg = _load_config()
    if cfg is None:
        return {"status": "skipped", "reason": "Dropbox sync disabled or not configured"}
    files: list[Path] = []
    for path in cfg.data_dir.glob("**/*"):
        if path.is_file():
            files.append(path)
    return sync_paths(files, note=note or "full")
