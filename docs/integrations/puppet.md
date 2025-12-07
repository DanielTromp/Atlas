# Puppet Integration

Infrastructure Atlas integrates with Puppet Git repositories to visualize Linux user and group management.

## Configuration

### Setup via Admin UI

1. Navigate to **Admin → Puppet** (`/app/#admin`)
2. Click **＋ Add Puppet Repo**
3. Configure:
   - **Name** — Display name (e.g., "Puppet")
   - **Git Remote URL** — `git@gitlab.com:org/puppet.git`
   - **Branch** — `production` (default)
   - **SSH Key Path** — Path to private key (optional)

### Git Authentication

For private repositories, provide an SSH key path that the server can read.

## CLI Commands

### API Access

```bash
# List configured repositories
curl http://localhost:8000/puppet/configs

# Get users from a config
curl "http://localhost:8000/puppet/users?config_id=<id>"

# Get groups
curl "http://localhost:8000/puppet/groups?config_id=<id>"

# Export to Excel
curl -o puppet_export.xlsx "http://localhost:8000/puppet/export?config_id=<id>"
```

## API Endpoints

### GET /puppet/configs

List Puppet repository configurations.

### GET /puppet/users

Get users from Puppet manifests.

| Parameter | Description |
|-----------|-------------|
| `config_id` | Repository configuration ID |

### GET /puppet/groups

Get groups from Puppet manifests.

### GET /puppet/export

Export data to Excel with all sheets.

## Web UI

The **Puppet** page (`/app/#puppet`) provides:

### Tabs

| Tab | Description |
|-----|-------------|
| **Users** | All users with UID, email, status, sudo, groups, auth |
| **Groups** | All groups with GID, member count, members list |
| **Access Matrix** | User × Group membership grid |

### Features

- Search across all views
- Export to Excel (color-coded security warnings)
- Security analysis badges

### Security Badges

| Badge | Meaning |
|-------|---------|
| 🔐 SHA-512 | Strong password hash (modern default) |
| 🔐 MD5 ⚠️ | Weak password hash (vulnerable) |
| 🔑 RSA 4096b | Strong SSH key |
| 🔑 RSA 1024b ⚠️ | Weak SSH key (too short) |
| 🔑 ED25519 | Modern SSH key (recommended) |

Hover over badges for detailed security explanations.

## Manifest Structure

The parser reads Puppet layouts:

| Path | Content |
|------|---------|
| `site/user/manifests/virtual_users/*.pp` | User definitions (uid, password, SSH keys) |
| `site/user/manifests/virtual_groups/*.pp` | Group definitions with members |
| `site/user/manifests/groups/*_full.pp` | Sudo access grants |
| `site/user/files/groups/*_full` | Sudoers file content |

## Parsed Data

### Users

| Field | Description |
|-------|-------------|
| Username | Login name |
| UID | User ID |
| Email | Contact email |
| Status | enabled/disabled |
| Groups | Group memberships |
| Sudo | Sudo access |
| Auth Methods | Password hash type, SSH keys |

### Groups

| Field | Description |
|-------|-------------|
| Group Name | Group name |
| GID | Group ID |
| Members | List of member usernames |
| Member Count | Number of members |

## Security Analysis

The parser extracts and analyzes credentials:

### Password Hashes

| Type | Security |
|------|----------|
| SHA-512 (`$6$`) | ✅ Strong |
| SHA-256 (`$5$`) | ⚠️ Acceptable |
| MD5 (`$1$`) | ❌ Weak |
| DES | ❌ Very weak |

### SSH Keys

| Type | Security |
|------|----------|
| ED25519 | ✅ Recommended |
| RSA 4096b | ✅ Strong |
| RSA 2048b | ⚠️ Acceptable |
| RSA 1024b | ❌ Weak |
| DSA | ❌ Deprecated |

## Export Format

Excel export includes three sheets:

1. **Users** — All user data with auth analysis
2. **Groups** — All groups with members
3. **Access Matrix** — User × Group grid

Color coding highlights security issues:
- Red — Weak passwords/keys
- Yellow — Deprecated algorithms
- Green — Strong credentials

## Related Documentation

- [Configuration](../configuration.md) — Environment variables
- [Foreman Integration](foreman.md) — Puppet via Foreman
- [Web UI Guide](../web-ui.md) — Frontend features
