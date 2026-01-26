# Infrastructure Atlas - Kubernetes Deployment

Complete Kubernetes deployment for Infrastructure Atlas using Helm charts.
Works with **Docker Desktop**, **Rancher Desktop**, and production clusters.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Kubernetes Cluster                                 │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                        Traefik Ingress                                  │ │
│  │   atlas.local → Atlas API    grafana.local → Grafana                   │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  ┌─────────────────────┐  ┌─────────────────────┐  ┌────────────────────┐  │
│  │   atlas namespace   │  │  logging namespace  │  │  infra namespace   │  │
│  │                     │  │                     │  │                    │  │
│  │  ┌───────────────┐  │  │  ┌───────────────┐  │  │  ┌──────────────┐  │  │
│  │  │  Atlas API    │  │  │  │    Loki       │  │  │  │   MongoDB    │  │  │
│  │  │  (Web UI)     │──┼──┼──│    Stack      │  │  │  │              │  │  │
│  │  └───────────────┘  │  │  └───────────────┘  │  │  └──────────────┘  │  │
│  │                     │  │                     │  │                    │  │
│  │  ┌───────────────┐  │  │  ┌───────────────┐  │  │  ┌──────────────┐  │  │
│  │  │  Slack Bot    │  │  │  │   Promtail    │  │  │  │   Qdrant     │  │  │
│  │  └───────────────┘  │  │  │  (DaemonSet)  │  │  │  │  (RAG)       │  │  │
│  │                     │  │  └───────────────┘  │  │  └──────────────┘  │  │
│  │  ┌───────────────┐  │  │                     │  │                    │  │
│  │  │ Telegram Bot  │  │  │  ┌───────────────┐  │  │                    │  │
│  │  └───────────────┘  │  │  │   Grafana     │  │  │                    │  │
│  │                     │  │  └───────────────┘  │  │                    │  │
│  └─────────────────────┘  └─────────────────────┘  └────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Quick Start

### 1. Prerequisites

```bash
# Install Helm (if not already installed)
brew install helm    # macOS
# or: choco install kubernetes-helm  # Windows
# or: curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

# Verify Kubernetes is running
kubectl cluster-info
```

**Enable Kubernetes in Docker Desktop:**
1. Open Docker Desktop → Settings → Kubernetes
2. Check "Enable Kubernetes"
3. Click "Apply & Restart"
4. Wait for green "Kubernetes running" indicator

### 2. Configure Secrets

```bash
cd kubernetes

# Copy the secrets template
cp atlas/values-secrets.example.yaml atlas/values-secrets.yaml

# Edit with your credentials
# Required: atlasSecretKey, atlasUiSecret, netboxUrl, netboxToken
```

### 3. Deploy

```bash
# Deploy everything with one command
./deploy.sh
```

This deploys:
- **MongoDB** — Primary database
- **Qdrant** — Vector database for RAG search
- **Traefik** — Ingress controller
- **Loki Stack** — Logging (Loki + Promtail + Grafana)
- **Atlas** — API server, Web UI, and bots

### 4. Access Services

```bash
# Atlas API and Web UI
kubectl port-forward svc/atlas 8000:8000 -n atlas
open http://localhost:8000/app/

# Grafana (logs dashboard)
kubectl port-forward svc/loki-grafana 3000:80 -n logging
open http://localhost:3000
# Login: admin / atlas-logs
```

## Deployment Options

### Development (values-dev.yaml)

For local development with Docker Desktop:

```bash
helm install atlas ./atlas -n atlas \
  -f atlas/values-dev.yaml \
  -f atlas/values-secrets.yaml
```

Features:
- Single replica
- Lower resource limits
- `hostNetwork: false` (use custom DNS for VPN)
- Local image (`pullPolicy: Never`)

### Production (values-prod.yaml)

For production clusters:

```bash
helm install atlas ./atlas -n atlas \
  -f atlas/values-prod.yaml \
  -f atlas/values-secrets.yaml
```

Features:
- Multiple replicas
- Higher resource limits
- VPN sidecar support
- Container registry image

## VPN Connectivity

### The Challenge

Kubernetes pods have isolated networking and cannot access hosts behind your VPN tunnel by default.

### Solution: Custom DNS (Development)

Configure VPN DNS servers in the pod:

```yaml
# values-dev.yaml
atlas:
  dnsConfig:
    nameservers:
      - 10.0.10.101    # Your VPN DNS server
      - 10.20.10.15    # Secondary DNS
```

### Solution: VPN Sidecar (Production)

For production deployments where `hostNetwork` isn't suitable:

```yaml
# values-prod.yaml
vpnSidecar:
  enabled: true
  type: openvpn
  configSecret: atlas-vpn-config
```

## Accessing Services

### Option 1: Port-Forward (Simplest)

```bash
# Atlas
kubectl port-forward svc/atlas 8000:8000 -n atlas

# Grafana
kubectl port-forward svc/loki-grafana 3000:80 -n logging

# MongoDB (debugging)
kubectl port-forward svc/mongodb 27017:27017 -n infra
```

### Option 2: Ingress with /etc/hosts

Add to `/etc/hosts`:
```
127.0.0.1 atlas.local grafana.local
```

| Service | URL |
|---------|-----|
| Atlas API + UI | http://atlas.local |
| Grafana | http://grafana.local |

## Common Operations

### Update After Code Changes

```bash
# Rebuild the Docker image
docker build -t atlas:latest .

# Restart the deployment
kubectl rollout restart deploy/atlas -n atlas

# Watch the rollout
kubectl rollout status deploy/atlas -n atlas
```

### View Logs

```bash
# Atlas API logs
kubectl logs -f deploy/atlas -n atlas

# Slack bot logs
kubectl logs -f deploy/atlas-slack-bot -n atlas

# All pods in atlas namespace
kubectl logs -f -l app.kubernetes.io/instance=atlas -n atlas
```

### Check Status

```bash
# All pods
kubectl get pods -A | grep -E "atlas|mongodb|qdrant|loki"

# Atlas health
curl http://localhost:8000/api/health

# Resource usage
kubectl top pods -n atlas
```

### Helm Operations

```bash
# Upgrade Atlas
helm upgrade atlas ./atlas -n atlas \
  -f atlas/values-dev.yaml \
  -f atlas/values-secrets.yaml

# View current values
helm get values atlas -n atlas

# Rollback
helm rollback atlas -n atlas
```

## Cleanup

```bash
# Uninstall Atlas
helm uninstall atlas -n atlas

# Uninstall dependencies
helm uninstall mongodb -n infra
helm uninstall qdrant -n infra
helm uninstall loki -n logging
helm uninstall traefik -n kube-system

# Delete namespaces (removes everything)
kubectl delete namespace atlas logging infra

# Delete persistent volumes (DATA LOSS!)
kubectl delete pvc --all -n atlas
kubectl delete pvc --all -n infra
kubectl delete pvc --all -n logging
```

## Troubleshooting

### Pods Not Starting

```bash
# Check pod status
kubectl get pods -n atlas

# View pod events
kubectl describe pod -l app.kubernetes.io/name=atlas -n atlas

# Check logs
kubectl logs -f deploy/atlas -n atlas
```

### VPN/DNS Issues

```bash
# Test DNS resolution from pod
ATLAS_POD=$(kubectl get pod -n atlas -l app.kubernetes.io/name=atlas -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n atlas $ATLAS_POD -- nslookup netbox.example.com

# Test connectivity
kubectl exec -n atlas $ATLAS_POD -- curl -s http://netbox.example.com/api/
```

### MongoDB Connection Issues

```bash
# Check MongoDB status
kubectl get pods -n infra -l app.kubernetes.io/name=mongodb

# Test connection
kubectl exec -n infra mongodb-0 -- mongosh --eval "db.adminCommand('ping')"
```

### Image Pull Errors

```bash
# For local images, ensure pullPolicy is correct
kubectl get deploy atlas -n atlas -o jsonpath='{.spec.template.spec.containers[0].imagePullPolicy}'

# Should be "Never" for local images
```

## Directory Structure

```
kubernetes/
├── README.md                    # This file
├── deploy.sh                    # One-click deployment script
├── test.sh                      # Validation script
│
├── atlas/                       # Atlas Helm chart
│   ├── Chart.yaml
│   ├── values.yaml              # Default values
│   ├── values-dev.yaml          # Development config
│   ├── values-prod.yaml         # Production config
│   ├── values-secrets.example.yaml
│   └── templates/
│       ├── deployment.yaml
│       ├── service.yaml
│       ├── ingress.yaml
│       ├── configmap.yaml
│       ├── secrets.yaml
│       ├── pvc.yaml
│       ├── slack-bot.yaml
│       └── telegram-bot.yaml
│
├── dependencies/                # External chart values
│   ├── mongodb-values.yaml
│   ├── qdrant-values.yaml
│   └── traefik-values.yaml
│
└── logging/                     # Loki stack
    ├── loki-stack-values.yaml
    └── grafana-dashboards-cm.yaml
```

## Platform Compatibility

| Platform | Development | Production | Notes |
|----------|-------------|------------|-------|
| Docker Desktop | ✅ Recommended | ❌ | Enable Kubernetes in settings |
| Rancher Desktop | ✅ | ✅ | containerd or dockerd runtime |
| K3s | ✅ | ✅ | Lightweight Kubernetes |
| EKS/GKE/AKS | ❌ | ✅ | Cloud managed Kubernetes |

## Next Steps

1. **Verify Deployment**: Run `./test.sh` to validate all services
2. **Check Logs**: Open Grafana at http://localhost:3000
3. **Test Integrations**: Verify NetBox, Zabbix, vCenter connectivity
4. **Configure Bots**: Set up Slack/Telegram tokens in secrets

For questions or issues, see the main [documentation](../docs/).
