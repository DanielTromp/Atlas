from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

try:
    import paramiko
    from paramiko import SFTPClient, SSHClient
except ImportError:  # pragma: no cover - optional dependency not installed
    paramiko = None  # type: ignore
    SSHClient = SFTPClient = object  # type: ignore

from .env import load_env, project_root


@dataclass
class BackupConfig:
    """Configuration for backup operations."""
    backup_type: Literal["sftp", "scp", "local"]
    data_dir: Path
    enable: bool
    
    # SFTP/SCP specific
    host: str | None = None
    port: int = 22
    username: str | None = None
    password: str | None = None
    private_key_path: str | None = None
    remote_path: str | None = None
    
    # Local backup specific
    local_backup_path: Path | None = None
    
    # Common options
    create_timestamped_dirs: bool = False
    compress: bool = False


def _load_config() -> BackupConfig | None:
    """Load backup configuration from environment variables."""
    load_env()
    
    enable_raw = os.getenv("BACKUP_ENABLE", "1").strip().lower()
    enable = enable_raw not in {"0", "false", "no", "off"}
    
    if not enable:
        return None
    
    backup_type = os.getenv("BACKUP_TYPE", "local").strip().lower()
    if backup_type not in {"sftp", "scp", "local"}:
        backup_type = "local"
    
    data_dir_env = os.getenv("NETBOX_DATA_DIR", "data")
    data_dir = Path(data_dir_env) if os.path.isabs(data_dir_env) else (project_root() / data_dir_env)
    
    config = BackupConfig(
        backup_type=backup_type,  # type: ignore
        data_dir=data_dir,
        enable=enable,
        create_timestamped_dirs=os.getenv("BACKUP_CREATE_TIMESTAMPED_DIRS", "false").strip().lower() in {"1", "true", "yes", "on"},
        compress=os.getenv("BACKUP_COMPRESS", "false").strip().lower() in {"1", "true", "yes", "on"},
    )
    
    if backup_type in {"sftp", "scp"}:
        config.host = os.getenv("BACKUP_HOST", "").strip() or None
        config.port = int(os.getenv("BACKUP_PORT", "22"))
        config.username = os.getenv("BACKUP_USERNAME", "").strip() or None
        config.password = os.getenv("BACKUP_PASSWORD", "").strip() or None
        config.private_key_path = os.getenv("BACKUP_PRIVATE_KEY_PATH", "").strip() or None
        config.remote_path = os.getenv("BACKUP_REMOTE_PATH", "").strip() or None
        
        if not config.host or not config.username:
            return None
        if not config.password and not config.private_key_path:
            return None
    
    elif backup_type == "local":
        local_path = os.getenv("BACKUP_LOCAL_PATH", "").strip()
        if local_path:
            config.local_backup_path = Path(local_path) if os.path.isabs(local_path) else (project_root() / local_path)
        else:
            config.local_backup_path = project_root() / "backups"
    
    return config


def _iter_paths(paths: Iterable[Path], data_dir: Path) -> list[tuple[Path, str]]:
    """Iterate over paths and return (local_path, relative_path) tuples."""
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
            rel = Path(path.name)
        
        out.append((path, str(rel).replace("\\", "/")))
    
    return out


def _create_ssh_client(config: BackupConfig):
    """Create and configure SSH client for SFTP/SCP operations."""
    if paramiko is None:
        raise RuntimeError("paramiko dependency not installed (required for SFTP/SCP)")
    
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    connect_kwargs = {
        "hostname": config.host,
        "port": config.port,
        "username": config.username,
    }
    
    if config.private_key_path:
        try:
            key_path = Path(config.private_key_path).expanduser()
            if key_path.exists():
                connect_kwargs["key_filename"] = str(key_path)
            else:
                raise FileNotFoundError(f"Private key not found: {key_path}")
        except Exception as e:
            raise RuntimeError(f"Failed to load private key: {e}") from e
    elif config.password:
        connect_kwargs["password"] = config.password
    
    try:
        client.connect(**connect_kwargs)
    except Exception as e:
        raise RuntimeError(f"SSH connection failed: {e}") from e
    
    return client


def _backup_sftp(config: BackupConfig, file_paths: list[tuple[Path, str]]) -> dict:
    """Backup files using SFTP."""
    client = _create_ssh_client(config)
    uploads = []
    
    try:
        sftp = client.open_sftp()
        
        # Create base directory if it doesn't exist
        base_path = config.remote_path or "."
        if config.create_timestamped_dirs:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            base_path = f"{base_path.rstrip('/')}/{timestamp}"
        
        # Ensure remote directory exists
        try:
            sftp.mkdir(base_path)
        except Exception:
            pass  # Directory might already exist
        
        for local_path, rel_path in file_paths:
            remote_file = f"{base_path}/{rel_path}".replace("//", "/")
            
            # Create remote directory structure if needed
            remote_dir = "/".join(remote_file.split("/")[:-1])
            if remote_dir:
                try:
                    sftp.mkdir(remote_dir)
                except Exception:
                    pass  # Directory might already exist
            
            # Upload file
            sftp.put(str(local_path), remote_file)
            uploads.append({
                "local_path": str(local_path),
                "remote_path": remote_file,
                "size": local_path.stat().st_size,
            })
        
        sftp.close()
    finally:
        client.close()
    
    return {
        "status": "ok",
        "method": "sftp",
        "uploaded": uploads,
        "count": len(uploads),
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


def _backup_scp(config: BackupConfig, file_paths: list[tuple[Path, str]]) -> dict:
    """Backup files using SCP command."""
    uploads = []
    
    # Prepare base path
    base_path = config.remote_path or "."
    if config.create_timestamped_dirs:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_path = f"{base_path.rstrip('/')}/{timestamp}"
    
    # Create remote directory using SSH
    client = _create_ssh_client(config)
    try:
        stdin, stdout, stderr = client.exec_command(f"mkdir -p {base_path}")
        stdout.channel.recv_exit_status()  # Wait for command to complete
    finally:
        client.close()
    
    for local_path, rel_path in file_paths:
        remote_file = f"{base_path}/{rel_path}".replace("//", "/")
        remote_target = f"{config.username}@{config.host}:{remote_file}"
        
        # Build SCP command
        cmd = ["scp", "-P", str(config.port)]
        
        if config.private_key_path:
            cmd.extend(["-i", config.private_key_path])
        
        cmd.extend([str(local_path), remote_target])
        
        # Execute SCP
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            uploads.append({
                "local_path": str(local_path),
                "remote_path": remote_file,
                "size": local_path.stat().st_size,
            })
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"SCP failed for {local_path}: {e.stderr}") from e
    
    return {
        "status": "ok",
        "method": "scp",
        "uploaded": uploads,
        "count": len(uploads),
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


def _backup_local(config: BackupConfig, file_paths: list[tuple[Path, str]]) -> dict:
    """Backup files to local directory."""
    if not config.local_backup_path:
        raise RuntimeError("Local backup path not configured")
    
    # Prepare backup directory
    backup_dir = config.local_backup_path
    if config.create_timestamped_dirs:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = backup_dir / timestamp
    
    backup_dir.mkdir(parents=True, exist_ok=True)
    
    copies = []
    for local_path, rel_path in file_paths:
        dest_path = backup_dir / rel_path
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Copy file
        shutil.copy2(local_path, dest_path)
        copies.append({
            "local_path": str(local_path),
            "backup_path": str(dest_path),
            "size": local_path.stat().st_size,
        })
    
    return {
        "status": "ok",
        "method": "local",
        "copied": copies,
        "count": len(copies),
        "backup_dir": str(backup_dir),
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


def sync_paths(paths: Sequence[Path | str], *, note: str | None = None) -> dict:
    """Sync specified paths using the configured backup method."""
    config = _load_config()
    if config is None:
        return {"status": "skipped", "reason": "Backup sync disabled or not configured"}
    
    file_paths = _iter_paths([Path(p) for p in paths], config.data_dir)
    if not file_paths:
        return {"status": "skipped", "reason": "No files to backup"}
    
    try:
        if config.backup_type == "sftp":
            result = _backup_sftp(config, file_paths)
        elif config.backup_type == "scp":
            result = _backup_scp(config, file_paths)
        elif config.backup_type == "local":
            result = _backup_local(config, file_paths)
        else:
            return {"status": "error", "reason": f"Unknown backup type: {config.backup_type}"}
        
        if note:
            result["note"] = note
        
        return result
    
    except Exception as e:
        return {
            "status": "error",
            "reason": str(e),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }


def sync_data_dir(*, note: str | None = None) -> dict:
    """Sync all files in the data directory using the configured backup method."""
    config = _load_config()
    if config is None:
        return {"status": "skipped", "reason": "Backup sync disabled or not configured"}
    
    files: list[Path] = []
    for path in config.data_dir.glob("**/*"):
        if path.is_file():
            files.append(path)
    
    return sync_paths(files, note=note or "full")