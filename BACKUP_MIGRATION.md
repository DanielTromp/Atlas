# Backup System Migration

This document describes the migration from Dropbox backup to the new flexible backup system.

## What Changed

### Removed
- `src/enreach_tools/dropbox_sync.py` - Old Dropbox-specific backup module
- `dropbox>=11.36.0` dependency from `pyproject.toml`
- All Dropbox-related environment variables (`DROPBOX_*`)

### Added
- `src/enreach_tools/backup_sync.py` - New flexible backup module
- `paramiko>=3.0.0` dependency for SFTP support
- New backup environment variables (see Configuration below)

## New Backup Options

The new system supports three backup methods:

1. **Local Backup** (`BACKUP_TYPE=local`)
   - Copies files to a local directory
   - Default and simplest option
   - No external dependencies

2. **SFTP Backup** (`BACKUP_TYPE=sftp`)
   - Uploads files via SFTP protocol
   - Requires `paramiko` library
   - Supports password or private key authentication

3. **SCP Backup** (`BACKUP_TYPE=scp`)
   - Uploads files via SCP command
   - Uses system `scp` command
   - Supports private key authentication

## Configuration

### Environment Variables

```bash
# Enable/disable backup
BACKUP_ENABLE=1

# Backup method: local, sftp, or scp
BACKUP_TYPE=local

# SFTP/SCP Configuration (when BACKUP_TYPE=sftp or scp)
BACKUP_HOST=backup.example.com
BACKUP_PORT=22
BACKUP_USERNAME=backup_user
BACKUP_PASSWORD=your_password_here
# Alternative: use private key instead of password
BACKUP_PRIVATE_KEY_PATH=~/.ssh/id_rsa
BACKUP_REMOTE_PATH=/backups/enreach-tools

# Local Backup Configuration (when BACKUP_TYPE=local)
BACKUP_LOCAL_PATH=backups

# Optional Features
BACKUP_CREATE_TIMESTAMPED_DIRS=false  # Create timestamped subdirectories
BACKUP_COMPRESS=false                 # Future feature for compression
```

### Migration Steps

1. **Update your `.env` file:**
   - Remove all `DROPBOX_*` variables
   - Add new `BACKUP_*` variables (see `.env.example`)

2. **Install new dependencies:**
   ```bash
   uv sync  # This will install paramiko and remove dropbox
   ```

3. **Choose your backup method:**
   - For local backups: Set `BACKUP_TYPE=local` and `BACKUP_LOCAL_PATH`
   - For SFTP: Set `BACKUP_TYPE=sftp` and configure host/credentials
   - For SCP: Set `BACKUP_TYPE=scp` and configure host/credentials

## API Changes

### Web UI
- The admin endpoint changed from `/admin/dropbox-sync` to `/admin/backup-sync`
- Functionality remains the same - triggers a full backup of the data directory

### Code Changes
- All imports changed from `from enreach_tools import dropbox_sync` to `from enreach_tools import backup_sync`
- Function names remain the same: `sync_paths()` and `sync_data_dir()`
- Return format is similar but includes method-specific fields

## Testing

The new backup system has been tested with:
- Local backup functionality
- File and directory structure preservation
- Error handling for missing configuration
- Integration with existing NetBox export scripts

## Security Notes

### SFTP/SCP Authentication
- **Private Key (Recommended):** Store your private key securely and reference it via `BACKUP_PRIVATE_KEY_PATH`
- **Password:** Only use for testing; consider private keys for production
- **Host Key Verification:** The system uses `AutoAddPolicy()` - ensure you trust the target host

### File Permissions
- Local backups inherit source file permissions
- Remote backups depend on the target system's umask and permissions

## Troubleshooting

### Common Issues

1. **"paramiko dependency not installed"**
   - Run `uv sync` to install paramiko

2. **SSH connection failed**
   - Verify host, port, username, and credentials
   - Check network connectivity and firewall rules
   - Ensure SSH service is running on target host

3. **Permission denied**
   - Verify backup user has write permissions to `BACKUP_REMOTE_PATH`
   - For local backups, ensure write permissions to `BACKUP_LOCAL_PATH`

4. **Private key not found**
   - Verify `BACKUP_PRIVATE_KEY_PATH` points to existing key file
   - Ensure key file has correct permissions (600)

### Debug Mode
Set `LOG_LEVEL=DEBUG` in your environment to get detailed backup operation logs.