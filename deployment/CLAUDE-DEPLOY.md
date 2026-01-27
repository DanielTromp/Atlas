# Claude Code Deployment Prompt

Use this prompt with Claude Code on sa-mgmt-tools-prod2 to deploy Atlas.

---

## Prompt

```
Deploy Atlas on this server following the deployment guide. The repositories are already cloned:
- Production: /var/lib/data/Atlas
- Development: /var/lib/data/Atlas-dev

Execute the deployment steps from /var/lib/data/Atlas/deployment/README.md:

1. Verify Podman is installed, if not install it
2. Create the directory structure as documented
3. Generate SSL certificates for internal DNS (atlas.internal, atlas-dev.internal)
4. Copy the deployment compose files to the correct locations
5. Create the Traefik reverse proxy configuration
6. Copy the .env.example to .env for both prod and dev
7. Start Traefik first, then prod, then dev
8. Install the systemd services for auto-start on boot
9. Verify all services are healthy

For the .env files, I will provide the secret values when prompted. Use the existing values from Kubernetes if available.

Document any issues encountered and their solutions.
```

---

## Quick Reference Commands

### Check Current Status
```bash
# Podman version
podman --version

# Running containers
podman ps -a

# System resources
df -h /var/lib/data
free -h
```

### Start Everything
```bash
cd /var/lib/data/traefik && podman-compose up -d
cd /var/lib/data/Atlas && podman-compose up -d
cd /var/lib/data/Atlas-dev && podman-compose up -d
```

### View Logs
```bash
# All services
cd /var/lib/data/Atlas && podman-compose logs -f

# Specific service
podman logs -f atlas-prod
podman logs -f atlas-mongodb-prod
```

### Restart Services
```bash
sudo systemctl restart atlas-prod
sudo systemctl restart atlas-dev
```

### Check Health
```bash
curl -k https://localhost/health
curl -k https://localhost:8443/health
```

---

## Expected Endpoints After Deployment

| URL | Service |
|-----|---------|
| https://atlas.internal | Production Atlas |
| https://atlas.internal/app/ | Production Web UI |
| https://atlas-dev.internal:8443 | Development Atlas |
| https://atlas-dev.internal:8443/app/ | Development Web UI |
| http://localhost:8080 | Traefik Dashboard |

---

## Troubleshooting

### SELinux Issues
```bash
# Check if SELinux is blocking
sudo ausearch -m avc -ts recent

# Fix volume permissions
sudo chcon -Rt svirt_sandbox_file_t /var/lib/data/
```

### Network Issues
```bash
# Check if traefik network exists
podman network ls

# Create if missing
podman network create traefik-net
```

### Port Conflicts
```bash
# Check what's using ports
sudo ss -tlnp | grep -E ':443|:8443|:27017|:27018'
```

---

## Data Migration from Kubernetes

If migrating data from existing Kubernetes deployment:

```bash
# On the machine with kubectl access:
kubectl exec -n atlas atlas-mongodb-0 -- mongodump --archive > mongodb-backup.archive

# Copy to this server
scp mongodb-backup.archive user@sa-mgmt-tools-prod2:/tmp/

# On this server, restore:
podman exec -i atlas-mongodb-prod mongorestore --archive < /tmp/mongodb-backup.archive
```
