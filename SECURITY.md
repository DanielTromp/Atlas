# Security Policy

## Supported Versions

We release patches for security vulnerabilities. Currently supported versions:

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

We take the security of Infrastructure Atlas seriously. If you believe you have found a security vulnerability, please report it to us as described below.

### Where to Report

**Please do NOT report security vulnerabilities through public GitHub issues.**

Instead, please report them via email to: **drpgmtromp@gmail.com**

You should receive a response within 48 hours. If for some reason you do not, please follow up via email to ensure we received your original message.

### What to Include

Please include the following information in your report:

- Type of issue (e.g., buffer overflow, SQL injection, cross-site scripting, etc.)
- Full paths of source file(s) related to the manifestation of the issue
- The location of the affected source code (tag/branch/commit or direct URL)
- Any special configuration required to reproduce the issue
- Step-by-step instructions to reproduce the issue
- Proof-of-concept or exploit code (if possible)
- Impact of the issue, including how an attacker might exploit it

This information will help us triage your report more quickly.

### Disclosure Policy

- Security issues will be investigated and addressed as quickly as possible
- We ask that you give us a reasonable amount of time to fix the issue before public disclosure
- We will credit you for the discovery (unless you prefer to remain anonymous)
- Once a fix is released, we will publish a security advisory on GitHub

## Security Best Practices

When deploying Infrastructure Atlas, please follow these security best practices:

### Environment Variables

- **Never commit `.env` files** to version control
- Use strong, unique values for all tokens and API keys
- Rotate credentials regularly
- Use the provided `.env.example` as a template only

### Secrets Management

- Generate a strong `ATLAS_SECRET_KEY` (32-byte Fernet key)
- Set complex passwords for `ATLAS_UI_PASSWORD` and `ATLAS_DEFAULT_ADMIN_PASSWORD`
- Use unique API tokens for `ATLAS_API_TOKEN`
- Store sensitive credentials in the encrypted secret store (database-backed)

### HTTPS/TLS

- **Always use HTTPS in production** (configure `ATLAS_SSL_CERTFILE` and `ATLAS_SSL_KEYFILE`)
- Use valid SSL certificates (not self-signed in production)
- Keep certificates up to date and secure private keys

### Authentication

- Enable authentication for the API (`ATLAS_API_TOKEN`)
- Enable authentication for the web UI (`ATLAS_UI_PASSWORD`)
- Use role-based access control (RBAC) to limit user permissions
- Regularly review user accounts and API keys

### Network Security

- **Do not expose the application directly to the internet**
- Use a reverse proxy (nginx, Apache, etc.) with proper security headers
- Implement rate limiting at the reverse proxy level
- Restrict access to trusted networks/IPs when possible

### Database

- The default SQLite database is stored in `data/atlas.db`
- Ensure proper file permissions on the database (readable only by the application user)
- Back up the database regularly (it contains encrypted secrets)
- Do not share database files (they contain sensitive data)

### Updates

- Keep dependencies up to date: `uv sync --upgrade`
- Monitor security advisories for Python packages
- Subscribe to GitHub notifications for this repository

### Data Exports

- Files in `data/`, `exports/`, `reports/`, and `logs/` may contain sensitive infrastructure information
- Ensure these directories are properly protected (already in `.gitignore`)
- Implement access controls on any shared export locations
- Sanitize data before sharing reports externally

### API Integration Tokens

External service tokens (NetBox, vCenter, Commvault, Zabbix, Confluence, etc.):
- Use service accounts with **minimum required permissions**
- Rotate tokens according to your organization's security policy
- Monitor API usage for anomalies
- Revoke tokens immediately if compromised

## Known Security Considerations

### Secret Store

- Secrets are encrypted using Fernet symmetric encryption
- The encryption key (`ATLAS_SECRET_KEY`) must be kept secure
- If the encryption key is lost, secrets cannot be recovered
- If the encryption key is compromised, rotate all secrets immediately

### Web UI Session Management

- Sessions are stored server-side with secure, httpOnly cookies
- Configure `ATLAS_UI_SECRET` for session encryption
- Sessions expire after inactivity

### AI Chat Integration

- API keys for OpenAI, Anthropic, Google, and OpenRouter are stored encrypted
- Chat sessions may contain sensitive infrastructure information
- Review chat history retention policies
- Consider data residency requirements for AI providers

## Vulnerability Response

When a vulnerability is reported:

1. **Acknowledgment**: We will acknowledge receipt within 48 hours
2. **Investigation**: We will investigate and determine severity within 7 days
3. **Fix Development**: Critical issues will be patched within 14 days
4. **Release**: Security fixes will be released as soon as possible
5. **Disclosure**: Public disclosure will occur after a fix is available

## Questions?

If you have questions about this security policy, please contact: drpgmtromp@gmail.com
