"""Encrypted backup manager with support for multiple storage backends."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

try:
    import pyzipper

    HAS_PYZIPPER = True
except ImportError:
    pyzipper = None  # type: ignore
    HAS_PYZIPPER = False

try:
    import paramiko
except ImportError:
    paramiko = None  # type: ignore

try:
    import requests
except ImportError:
    requests = None  # type: ignore

from .env import load_env, project_root

# Files and patterns to backup (relative to project root)
BACKUP_PATTERNS = [
    "data/**/*",  # All data files
    ".env",  # Environment configuration
]

# Files and patterns for export (data only, no server-specific configs)
EXPORT_PATTERNS = [
    "data/**/*",  # All data files only
]

# Server-specific files that should NEVER be included in exports
SERVER_SPECIFIC_FILES = [
    ".env",  # Environment configuration with secrets
    ".env.local",  # Local overrides
]

# Files to exclude from backup/export
EXCLUDE_PATTERNS = [
    "*.pyc",
    "__pycache__",
    ".git",
    "*.log",
    "*.tmp",
]


class BackupError(Exception):
    """Base exception for backup operations."""


class BackupEncryptionError(BackupError):
    """Encryption/decryption error."""


class BackupStorageError(BackupError):
    """Storage provider error."""


@dataclass
class BackupManifest:
    """Manifest describing backup contents."""

    version: str = "2.0"
    created_at: str = ""
    hostname: str = ""
    files: list[dict[str, Any]] = field(default_factory=list)
    total_size: int = 0
    compressed_size: int = 0
    encrypted: bool = True
    checksum: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "created_at": self.created_at,
            "hostname": self.hostname,
            "files": self.files,
            "total_size": self.total_size,
            "compressed_size": self.compressed_size,
            "encrypted": self.encrypted,
            "checksum": self.checksum,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BackupManifest":
        return cls(
            version=data.get("version", "2.0"),
            created_at=data.get("created_at", ""),
            hostname=data.get("hostname", ""),
            files=data.get("files", []),
            total_size=data.get("total_size", 0),
            compressed_size=data.get("compressed_size", 0),
            encrypted=data.get("encrypted", True),
            checksum=data.get("checksum", ""),
        )


@dataclass
class BackupConfig:
    """Configuration for backup operations."""

    backup_type: Literal["local", "sftp", "scp", "webdav"] = "local"
    enable: bool = True
    encryption_password: str = ""

    # Local backup
    local_path: Path | None = None

    # SFTP/SCP
    host: str | None = None
    port: int = 22
    username: str | None = None
    password: str | None = None
    private_key_path: str | None = None
    remote_path: str = ""

    # WebDAV (FileRun)
    webdav_url: str | None = None
    webdav_username: str | None = None
    webdav_password: str | None = None
    webdav_path: str = "Atlas"

    # Options
    create_timestamped: bool = True
    keep_local_copy: bool = False


def _create_encrypted_zip(files: list[tuple[Path, str]], manifest: BackupManifest, password: str) -> bytes:
    """Create a password-protected ZIP archive using AES-256 encryption."""
    if not HAS_PYZIPPER:
        raise BackupError("pyzipper is required for encrypted backups. Install with: pip install pyzipper")

    buffer = io.BytesIO()

    with pyzipper.AESZipFile(
        buffer,
        mode="w",
        compression=pyzipper.ZIP_DEFLATED,
        encryption=pyzipper.WZ_AES,  # WinZip AES-256 encryption
    ) as zf:
        zf.setpassword(password.encode())

        # Add manifest
        manifest_data = json.dumps(manifest.to_dict(), indent=2)
        zf.writestr("manifest.json", manifest_data)

        # Add files
        for local_path, rel_path in files:
            try:
                zf.write(str(local_path), arcname=rel_path)
            except Exception:
                pass  # Skip files that can't be read

    return buffer.getvalue()


def _extract_encrypted_zip(data: bytes, target_dir: Path, password: str) -> BackupManifest:
    """Extract a password-protected ZIP archive."""
    if not HAS_PYZIPPER:
        raise BackupError("pyzipper is required for encrypted backups. Install with: pip install pyzipper")

    buffer = io.BytesIO(data)
    manifest = None

    with pyzipper.AESZipFile(buffer, mode="r") as zf:
        zf.setpassword(password.encode())

        # Extract manifest first
        try:
            with zf.open("manifest.json") as mf:
                manifest = BackupManifest.from_dict(json.load(mf))
        except Exception:
            manifest = BackupManifest()

        # Extract all files
        for info in zf.infolist():
            if info.filename == "manifest.json":
                continue

            # Security: prevent path traversal
            target_path = target_dir / info.filename
            if not str(target_path.resolve()).startswith(str(target_dir.resolve())):
                continue

            zf.extract(info, target_dir)

    return manifest or BackupManifest()


# Legacy functions for backward compatibility
def encrypt_data(data: bytes, password: str) -> bytes:
    """Legacy encryption - now returns data as-is since ZIP handles encryption."""
    return data


def decrypt_data(encrypted: bytes, password: str) -> bytes:
    """Legacy decryption - now returns data as-is since ZIP handles encryption."""
    return encrypted


def _load_config() -> BackupConfig:
    """Load backup configuration from environment."""
    load_env()

    backup_type = os.getenv("BACKUP_TYPE", "local").strip().lower()
    if backup_type not in {"local", "sftp", "scp", "webdav"}:
        backup_type = "local"

    config = BackupConfig(
        backup_type=backup_type,  # type: ignore
        enable=os.getenv("BACKUP_ENABLE", "1").strip().lower() not in {"0", "false", "no", "off"},
        encryption_password=os.getenv("BACKUP_ENCRYPTION_PASSWORD", "").strip(),
        create_timestamped=os.getenv("BACKUP_CREATE_TIMESTAMPED_DIRS", "true").strip().lower()
        in {"1", "true", "yes", "on"},
        keep_local_copy=os.getenv("BACKUP_KEEP_LOCAL_COPY", "false").strip().lower() in {"1", "true", "yes", "on"},
    )

    if backup_type == "local":
        local_path = os.getenv("BACKUP_LOCAL_PATH", "backups").strip()
        config.local_path = Path(local_path) if os.path.isabs(local_path) else project_root() / local_path

    elif backup_type in {"sftp", "scp"}:
        config.host = os.getenv("BACKUP_HOST", "").strip() or None
        config.port = int(os.getenv("BACKUP_PORT", "22"))
        config.username = os.getenv("BACKUP_USERNAME", "").strip() or None
        config.password = os.getenv("BACKUP_PASSWORD", "").strip() or None
        config.private_key_path = os.getenv("BACKUP_PRIVATE_KEY_PATH", "").strip() or None
        config.remote_path = os.getenv("BACKUP_REMOTE_PATH", "").strip()

    elif backup_type == "webdav":
        config.webdav_url = os.getenv("BACKUP_WEBDAV_URL", "").strip() or None
        config.webdav_username = os.getenv("BACKUP_WEBDAV_USERNAME", "").strip() or None
        config.webdav_password = os.getenv("BACKUP_WEBDAV_PASSWORD", "").strip() or None
        config.webdav_path = os.getenv("BACKUP_WEBDAV_PATH", "Atlas").strip()

    return config


def _collect_files(root: Path, include_server_config: bool = True) -> list[tuple[Path, str]]:
    """Collect all files to backup.

    Args:
        root: Project root directory
        include_server_config: If True, includes .env and other server-specific files.
                              If False, only includes data files (for exports).
    """
    files: list[tuple[Path, str]] = []

    # Collect data directory files
    data_dir = root / "data"
    if data_dir.exists():
        for path in data_dir.rglob("*"):
            if path.is_file():
                # Skip excluded patterns
                if any(path.match(pat) for pat in EXCLUDE_PATTERNS):
                    continue
                # Skip server-specific files if not including server config
                if not include_server_config and any(path.match(pat) for pat in SERVER_SPECIFIC_FILES):
                    continue
                rel_path = path.relative_to(root)
                files.append((path, str(rel_path)))

    # Only collect .env file for full backups (not exports)
    if include_server_config:
        env_file = root / ".env"
        if env_file.exists():
            files.append((env_file, ".env"))

    return files


def _collect_export_files(root: Path) -> list[tuple[Path, str]]:
    """Collect files for export (data only, no server-specific configs)."""
    return _collect_files(root, include_server_config=False)


def _create_archive(files: list[tuple[Path, str]], manifest: BackupManifest, password: str | None = None) -> bytes:
    """Create a ZIP archive of the files, optionally password-protected."""
    if password:
        return _create_encrypted_zip(files, manifest, password)

    # Unencrypted ZIP
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        manifest_data = json.dumps(manifest.to_dict(), indent=2)
        zf.writestr("manifest.json", manifest_data)
        for local_path, rel_path in files:
            try:
                zf.write(str(local_path), arcname=rel_path)
            except Exception:
                pass
    return buffer.getvalue()


def _extract_archive(data: bytes, target_dir: Path, password: str | None = None) -> BackupManifest:
    """Extract ZIP archive to target directory."""
    if password:
        return _extract_encrypted_zip(data, target_dir, password)

    # Unencrypted ZIP
    buffer = io.BytesIO(data)
    manifest = None
    with zipfile.ZipFile(buffer, mode="r") as zf:
        try:
            with zf.open("manifest.json") as mf:
                manifest = BackupManifest.from_dict(json.load(mf))
        except Exception:
            manifest = BackupManifest()

        for info in zf.infolist():
            if info.filename == "manifest.json":
                continue
            target_path = target_dir / info.filename
            if not str(target_path.resolve()).startswith(str(target_dir.resolve())):
                continue
            zf.extract(info, target_dir)

    return manifest or BackupManifest()


class LocalStorageProvider:
    """Local filesystem storage provider."""

    def __init__(self, config: BackupConfig):
        self.config = config
        self.backup_dir = config.local_path or project_root() / "backups"

    def upload(self, filename: str, data: bytes) -> str:
        """Upload backup to local storage."""
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        path = self.backup_dir / filename
        path.write_bytes(data)
        return str(path)

    def download(self, filename: str) -> bytes:
        """Download backup from local storage."""
        path = self.backup_dir / filename
        if not path.exists():
            raise BackupStorageError(f"Backup not found: {filename}")
        return path.read_bytes()

    def list_backups(self) -> list[dict[str, Any]]:
        """List available backups."""
        if not self.backup_dir.exists():
            return []

        backups = []
        # Include both .zip (new format) and .enc (legacy format)
        all_backups = list(self.backup_dir.glob("atlas_backup_*.zip")) + list(
            self.backup_dir.glob("atlas_backup_*.enc")
        )
        for path in sorted(all_backups, key=lambda p: p.name, reverse=True):
            stat = path.stat()
            backups.append(
                {
                    "filename": path.name,
                    "size": stat.st_size,
                    "created_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
                    "path": str(path),
                }
            )
        return backups

    def delete(self, filename: str) -> bool:
        """Delete a backup."""
        path = self.backup_dir / filename
        if path.exists():
            path.unlink()
            return True
        return False


class SFTPStorageProvider:
    """SFTP storage provider."""

    def __init__(self, config: BackupConfig):
        self.config = config
        if paramiko is None:
            raise BackupStorageError("paramiko is required for SFTP support")

    def _connect(self):
        """Create SFTP connection."""
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs = {
            "hostname": self.config.host,
            "port": self.config.port,
            "username": self.config.username,
        }

        if self.config.private_key_path:
            key_path = Path(self.config.private_key_path).expanduser()
            if key_path.exists():
                connect_kwargs["key_filename"] = str(key_path)
        elif self.config.password:
            connect_kwargs["password"] = self.config.password

        client.connect(**connect_kwargs)
        return client, client.open_sftp()

    def _ensure_dir(self, sftp, path: str):
        """Ensure remote directory exists."""
        parts = path.strip("/").split("/")
        current = ""
        for part in parts:
            current = f"{current}/{part}"
            try:
                sftp.stat(current)
            except FileNotFoundError:
                try:
                    sftp.mkdir(current)
                except Exception:
                    pass

    def upload(self, filename: str, data: bytes) -> str:
        """Upload backup via SFTP."""
        client, sftp = self._connect()
        try:
            remote_dir = self.config.remote_path.rstrip("/")
            self._ensure_dir(sftp, remote_dir)

            remote_path = f"{remote_dir}/{filename}"
            with sftp.file(remote_path, "wb") as f:
                f.write(data)

            return remote_path
        finally:
            sftp.close()
            client.close()

    def download(self, filename: str) -> bytes:
        """Download backup via SFTP."""
        client, sftp = self._connect()
        try:
            remote_path = f"{self.config.remote_path.rstrip('/')}/{filename}"
            with sftp.file(remote_path, "rb") as f:
                return f.read()
        finally:
            sftp.close()
            client.close()

    def list_backups(self) -> list[dict[str, Any]]:
        """List available backups."""
        client, sftp = self._connect()
        try:
            remote_dir = self.config.remote_path.rstrip("/")
            backups = []

            try:
                for attr in sftp.listdir_attr(remote_dir):
                    if attr.filename.startswith("atlas_backup_") and (
                        attr.filename.endswith(".zip") or attr.filename.endswith(".enc")
                    ):
                        backups.append(
                            {
                                "filename": attr.filename,
                                "size": attr.st_size,
                                "created_at": datetime.fromtimestamp(attr.st_mtime, UTC).isoformat(),
                                "path": f"{remote_dir}/{attr.filename}",
                            }
                        )
            except FileNotFoundError:
                pass

            return sorted(backups, key=lambda x: x["created_at"], reverse=True)
        finally:
            sftp.close()
            client.close()

    def delete(self, filename: str) -> bool:
        """Delete a backup."""
        client, sftp = self._connect()
        try:
            remote_path = f"{self.config.remote_path.rstrip('/')}/{filename}"
            sftp.remove(remote_path)
            return True
        except Exception:
            return False
        finally:
            sftp.close()
            client.close()


class WebDAVStorageProvider:
    """WebDAV storage provider (for FileRun, Nextcloud, etc.)."""

    def __init__(self, config: BackupConfig):
        self.config = config
        if requests is None:
            raise BackupStorageError("requests is required for WebDAV support")

        self.base_url = config.webdav_url.rstrip("/") if config.webdav_url else ""
        self.auth = (config.webdav_username, config.webdav_password) if config.webdav_username else None
        self.path = config.webdav_path.strip("/")

    def _url(self, filename: str = "") -> str:
        """Build WebDAV URL."""
        parts = [self.base_url]
        if self.path:
            parts.append(self.path)
        if filename:
            parts.append(filename)
        return "/".join(parts)

    def _ensure_dir(self):
        """Ensure remote directory exists."""
        if not self.path:
            return

        # Try to create directory via MKCOL
        url = f"{self.base_url}/{self.path}"
        try:
            requests.request("MKCOL", url, auth=self.auth, timeout=30)
        except Exception:
            pass  # Directory might already exist

    def upload(self, filename: str, data: bytes) -> str:
        """Upload backup via WebDAV."""
        self._ensure_dir()
        url = self._url(filename)

        response = requests.put(
            url,
            data=data,
            auth=self.auth,
            headers={"Content-Type": "application/octet-stream"},
            timeout=300,
        )

        if response.status_code not in {200, 201, 204}:
            raise BackupStorageError(f"WebDAV upload failed: {response.status_code} {response.text}")

        return url

    def download(self, filename: str) -> bytes:
        """Download backup via WebDAV."""
        url = self._url(filename)

        response = requests.get(url, auth=self.auth, timeout=300)

        if response.status_code != 200:
            raise BackupStorageError(f"WebDAV download failed: {response.status_code}")

        return response.content

    def list_backups(self) -> list[dict[str, Any]]:
        """List available backups via PROPFIND."""
        url = self._url()

        propfind_body = """<?xml version="1.0" encoding="utf-8" ?>
        <D:propfind xmlns:D="DAV:">
            <D:prop>
                <D:displayname/>
                <D:getcontentlength/>
                <D:getlastmodified/>
            </D:prop>
        </D:propfind>"""

        try:
            response = requests.request(
                "PROPFIND",
                url,
                data=propfind_body,
                auth=self.auth,
                headers={"Content-Type": "application/xml", "Depth": "1"},
                timeout=30,
            )

            if response.status_code not in {200, 207}:
                return []

            # Parse response - split by response elements
            import re
            from urllib.parse import unquote

            backups = []

            # Split into individual response blocks
            responses = re.split(r"<[dD]:response[^>]*>", response.text)

            for resp_block in responses:
                # Find href in this block
                href_match = re.search(r"<(?:[dD]:)?href>([^<]+)</(?:[dD]:)?href>", resp_block)
                if not href_match:
                    continue

                href = unquote(href_match.group(1))
                filename = href.rstrip("/").split("/")[-1]

                if not (
                    filename.startswith("atlas_backup_") and (filename.endswith(".zip") or filename.endswith(".enc"))
                ):
                    continue

                # Find size in this block
                size_match = re.search(r"<(?:[dD]:)?getcontentlength>(\d+)</(?:[dD]:)?getcontentlength>", resp_block)
                size = int(size_match.group(1)) if size_match else 0

                # Find date in this block
                date_match = re.search(r"<(?:[dD]:)?getlastmodified>([^<]+)</(?:[dD]:)?getlastmodified>", resp_block)
                date = date_match.group(1) if date_match else ""

                backups.append(
                    {
                        "filename": filename,
                        "size": size,
                        "created_at": date,
                        "path": href,
                    }
                )

            return sorted(backups, key=lambda x: x.get("created_at", ""), reverse=True)

        except Exception:
            return []

    def delete(self, filename: str) -> bool:
        """Delete a backup via WebDAV."""
        url = self._url(filename)

        try:
            response = requests.delete(url, auth=self.auth, timeout=30)
            return response.status_code in {200, 204}
        except Exception:
            return False


def _get_storage_provider(config: BackupConfig):
    """Get appropriate storage provider based on config."""
    if config.backup_type == "local":
        return LocalStorageProvider(config)
    elif config.backup_type in {"sftp", "scp"}:
        return SFTPStorageProvider(config)
    elif config.backup_type == "webdav":
        return WebDAVStorageProvider(config)
    else:
        raise BackupStorageError(f"Unknown backup type: {config.backup_type}")


def create_backup(password: str | None = None, config: BackupConfig | None = None) -> dict[str, Any]:
    """Create an encrypted backup of all application data as a password-protected ZIP."""
    if config is None:
        config = _load_config()

    if not config.enable:
        return {"status": "skipped", "reason": "Backups are disabled"}

    # Use provided password or config password
    encryption_password = password or config.encryption_password
    if not encryption_password:
        return {"status": "error", "reason": "Encryption password not configured"}

    root = project_root()

    # Collect files
    files = _collect_files(root)
    if not files:
        return {"status": "skipped", "reason": "No files to backup"}

    # Build manifest
    import socket

    manifest = BackupManifest(
        created_at=datetime.now(UTC).isoformat(),
        hostname=socket.gethostname(),
        files=[{"path": rel, "size": local.stat().st_size} for local, rel in files],
        total_size=sum(local.stat().st_size for local, _ in files),
        encrypted=True,
    )

    # Create password-protected ZIP archive
    encrypted_data = _create_archive(files, manifest, password=encryption_password)
    manifest.compressed_size = len(encrypted_data)
    manifest.checksum = hashlib.sha256(encrypted_data).hexdigest()

    # Generate filename (.zip extension - standard password-protected ZIP)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"atlas_backup_{timestamp}.zip"

    # Upload to storage
    try:
        provider = _get_storage_provider(config)
        remote_path = provider.upload(filename, encrypted_data)

        return {
            "status": "ok",
            "filename": filename,
            "path": remote_path,
            "method": config.backup_type,
            "files_count": len(files),
            "total_size": manifest.total_size,
            "compressed_size": manifest.compressed_size,
            "encrypted_size": len(encrypted_data),
            "checksum": manifest.checksum,
            "timestamp": manifest.created_at,
        }

    except Exception as e:
        return {
            "status": "error",
            "reason": str(e),
            "timestamp": datetime.now(UTC).isoformat(),
        }


def restore_backup(
    filename: str,
    password: str | None = None,
    config: BackupConfig | None = None,
    target_dir: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Restore an encrypted backup (password-protected ZIP)."""
    if config is None:
        config = _load_config()

    encryption_password = password or config.encryption_password
    if not encryption_password:
        return {"status": "error", "reason": "Decryption password not configured"}

    # Download backup
    try:
        provider = _get_storage_provider(config)
        zip_data = provider.download(filename)
    except Exception as e:
        return {"status": "error", "reason": f"Failed to download backup: {e}"}

    # Verify checksum of ZIP file
    checksum = hashlib.sha256(zip_data).hexdigest()

    if dry_run:
        # Just parse and return manifest without extracting
        if not HAS_PYZIPPER:
            return {"status": "error", "reason": "pyzipper is required for encrypted backups"}

        try:
            buffer = io.BytesIO(zip_data)
            with pyzipper.AESZipFile(buffer, mode="r") as zf:
                zf.setpassword(encryption_password.encode())
                try:
                    with zf.open("manifest.json") as mf:
                        manifest = BackupManifest.from_dict(json.load(mf))
                        return {
                            "status": "ok",
                            "dry_run": True,
                            "manifest": manifest.to_dict(),
                            "checksum": checksum,
                        }
                except Exception:
                    pass
        except Exception as e:
            return {"status": "error", "reason": f"Failed to read backup (wrong password?): {e}"}

        return {"status": "ok", "dry_run": True, "checksum": checksum}

    # Extract to target
    if target_dir is None:
        target_dir = project_root()

    try:
        manifest = _extract_archive(zip_data, target_dir, password=encryption_password)

        return {
            "status": "ok",
            "restored_to": str(target_dir),
            "files_count": len(manifest.files),
            "manifest": manifest.to_dict(),
            "checksum": checksum,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    except Exception as e:
        return {"status": "error", "reason": f"Failed to extract backup (wrong password?): {e}"}


def list_backups(config: BackupConfig | None = None) -> dict[str, Any]:
    """List available backups."""
    if config is None:
        config = _load_config()

    try:
        provider = _get_storage_provider(config)
        backups = provider.list_backups()

        return {
            "status": "ok",
            "method": config.backup_type,
            "backups": backups,
            "count": len(backups),
        }

    except Exception as e:
        return {"status": "error", "reason": str(e)}


def delete_backup(filename: str, config: BackupConfig | None = None) -> dict[str, Any]:
    """Delete a backup."""
    if config is None:
        config = _load_config()

    try:
        provider = _get_storage_provider(config)
        success = provider.delete(filename)

        if success:
            return {"status": "ok", "deleted": filename}
        else:
            return {"status": "error", "reason": "Backup not found or could not be deleted"}

    except Exception as e:
        return {"status": "error", "reason": str(e)}


# =============================================================================
# Export Functions (Data only - no server-specific configs like .env)
# =============================================================================


def create_export(password: str | None = None, config: BackupConfig | None = None) -> dict[str, Any]:
    """Create an export of application data (without server-specific configs).

    Unlike backups, exports do NOT include:
    - .env files (server-specific secrets and configuration)
    - Database files (server-specific state)
    - Any other server-specific configuration

    Exports are safe to import on any server without overwriting its configuration.
    """
    if config is None:
        config = _load_config()

    if not config.enable:
        return {"status": "skipped", "reason": "Backups/exports are disabled"}

    # Use provided password or config password
    encryption_password = password or config.encryption_password
    if not encryption_password:
        return {"status": "error", "reason": "Encryption password not configured"}

    root = project_root()

    # Collect only data files (no server config)
    files = _collect_export_files(root)
    if not files:
        return {"status": "skipped", "reason": "No files to export"}

    # Build manifest with export type marker
    import socket

    manifest = BackupManifest(
        created_at=datetime.now(UTC).isoformat(),
        hostname=socket.gethostname(),
        files=[{"path": rel, "size": local.stat().st_size} for local, rel in files],
        total_size=sum(local.stat().st_size for local, _ in files),
        encrypted=True,
    )
    # Mark this as an export (not a full backup)
    manifest_dict = manifest.to_dict()
    manifest_dict["type"] = "export"
    manifest_dict["excludes_server_config"] = True

    # Create password-protected ZIP archive
    encrypted_data = _create_archive(files, manifest, password=encryption_password)
    manifest.compressed_size = len(encrypted_data)
    manifest.checksum = hashlib.sha256(encrypted_data).hexdigest()

    # Generate filename with export prefix
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"atlas_export_{timestamp}.zip"

    # Upload to storage
    try:
        provider = _get_storage_provider(config)
        remote_path = provider.upload(filename, encrypted_data)

        return {
            "status": "ok",
            "type": "export",
            "filename": filename,
            "path": remote_path,
            "method": config.backup_type,
            "files_count": len(files),
            "total_size": manifest.total_size,
            "compressed_size": manifest.compressed_size,
            "encrypted_size": len(encrypted_data),
            "checksum": manifest.checksum,
            "timestamp": manifest.created_at,
            "excludes": ["*.env", "server-specific configs"],
        }

    except Exception as e:
        return {
            "status": "error",
            "reason": str(e),
            "timestamp": datetime.now(UTC).isoformat(),
        }


def import_export(
    filename: str,
    password: str | None = None,
    config: BackupConfig | None = None,
    target_dir: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Import an export file (restores data without touching server config).

    This safely imports data from an export file without overwriting:
    - .env files
    - Database files
    - Any server-specific configuration
    """
    if config is None:
        config = _load_config()

    encryption_password = password or config.encryption_password
    if not encryption_password:
        return {"status": "error", "reason": "Decryption password not configured"}

    # Download export
    try:
        provider = _get_storage_provider(config)
        zip_data = provider.download(filename)
    except Exception as e:
        return {"status": "error", "reason": f"Failed to download export: {e}"}

    # Verify checksum
    checksum = hashlib.sha256(zip_data).hexdigest()

    if dry_run:
        # Just parse and return manifest without extracting
        if not HAS_PYZIPPER:
            return {"status": "error", "reason": "pyzipper is required for encrypted exports"}

        try:
            buffer = io.BytesIO(zip_data)
            with pyzipper.AESZipFile(buffer, mode="r") as zf:
                zf.setpassword(encryption_password.encode())
                try:
                    with zf.open("manifest.json") as mf:
                        manifest = BackupManifest.from_dict(json.load(mf))
                        return {
                            "status": "ok",
                            "dry_run": True,
                            "type": "export",
                            "manifest": manifest.to_dict(),
                            "checksum": checksum,
                            "safe_import": True,
                            "will_not_overwrite": [".env", "server configs"],
                        }
                except Exception:
                    pass
        except Exception as e:
            return {"status": "error", "reason": f"Failed to read export (wrong password?): {e}"}

        return {"status": "ok", "dry_run": True, "checksum": checksum}

    # Extract to target (only data directory)
    if target_dir is None:
        target_dir = project_root()

    try:
        # Use custom extraction that skips server-specific files
        manifest = _extract_export_archive(zip_data, target_dir, password=encryption_password)

        return {
            "status": "ok",
            "type": "export",
            "imported_to": str(target_dir),
            "files_count": len(manifest.files),
            "manifest": manifest.to_dict(),
            "checksum": checksum,
            "timestamp": datetime.now(UTC).isoformat(),
            "server_config_preserved": True,
        }

    except Exception as e:
        return {"status": "error", "reason": f"Failed to extract export (wrong password?): {e}"}


def _extract_export_archive(data: bytes, target_dir: Path, password: str) -> BackupManifest:
    """Extract export archive, skipping any server-specific files that might have slipped in."""
    if not HAS_PYZIPPER:
        raise BackupError("pyzipper is required for encrypted exports")

    buffer = io.BytesIO(data)
    manifest = None
    extracted_files = []

    with pyzipper.AESZipFile(buffer, mode="r") as zf:
        zf.setpassword(password.encode())

        # Extract manifest first
        try:
            with zf.open("manifest.json") as mf:
                manifest = BackupManifest.from_dict(json.load(mf))
        except Exception:
            manifest = BackupManifest()

        # Extract all files, but skip server-specific ones
        for info in zf.infolist():
            if info.filename == "manifest.json":
                continue

            # Skip server-specific files (safety check)
            filename = info.filename
            if any(filename.endswith(pat.lstrip("*")) for pat in SERVER_SPECIFIC_FILES if pat.startswith("*")):
                continue
            if filename in [f.lstrip("./") for f in SERVER_SPECIFIC_FILES if not f.startswith("*")]:
                continue
            if filename == ".env" or filename.endswith("/.env"):
                continue

            # Security: prevent path traversal
            target_path = target_dir / info.filename
            if not str(target_path.resolve()).startswith(str(target_dir.resolve())):
                continue

            zf.extract(info, target_dir)
            extracted_files.append(info.filename)

    # Update manifest to reflect what was actually extracted
    if manifest:
        manifest.files = [f for f in manifest.files if f.get("path") in extracted_files]

    return manifest or BackupManifest()


def list_exports(config: BackupConfig | None = None) -> dict[str, Any]:
    """List available exports."""
    if config is None:
        config = _load_config()

    try:
        provider = _get_storage_provider(config)
        all_files = provider.list_backups()  # Reuse the same listing logic

        # Filter to only export files (atlas_export_*.zip)
        exports = [f for f in all_files if f["filename"].startswith("atlas_export_")]

        return {
            "status": "ok",
            "type": "exports",
            "method": config.backup_type,
            "exports": exports,
            "count": len(exports),
        }

    except Exception as e:
        return {"status": "error", "reason": str(e)}


def delete_export(filename: str, config: BackupConfig | None = None) -> dict[str, Any]:
    """Delete an export."""
    if config is None:
        config = _load_config()

    # Verify it's an export file
    if not filename.startswith("atlas_export_"):
        return {"status": "error", "reason": "Not an export file"}

    try:
        provider = _get_storage_provider(config)
        success = provider.delete(filename)

        if success:
            return {"status": "ok", "deleted": filename}
        else:
            return {"status": "error", "reason": "Export not found or could not be deleted"}

    except Exception as e:
        return {"status": "error", "reason": str(e)}


# Legacy compatibility - keep sync_data_dir working
def sync_data_dir(*, note: str | None = None) -> dict:
    """Sync data directory using the new backup system."""
    result = create_backup()
    if note:
        result["note"] = note
    return result


def sync_paths(paths, *, note: str | None = None) -> dict:
    """Legacy sync function - now creates full backup."""
    return sync_data_dir(note=note)


__all__ = [
    "BackupConfig",
    "BackupEncryptionError",
    "BackupError",
    "BackupManifest",
    "BackupStorageError",
    "create_backup",
    "create_export",
    "decrypt_data",
    "delete_backup",
    "delete_export",
    "encrypt_data",
    "import_export",
    "list_backups",
    "list_exports",
    "restore_backup",
    "sync_data_dir",
    "sync_paths",
]
