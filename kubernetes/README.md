# Infrastructure Atlas - Kubernetes Deployment

Complete Kubernetes deployment voor Infrastructure Atlas met Helm charts.
Werkt met zowel **Docker Desktop** als **Rancher Desktop**.

## Architectuur Overzicht

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
│  │  │  (+ VPN side) │──┼──┼──│    Stack      │  │  │  │              │  │  │
│  │  └───────────────┘  │  │  └───────────────┘  │  │  └──────────────┘  │  │
│  │                     │  │                     │  │                    │  │
│  │  ┌───────────────┐  │  │  ┌───────────────┐  │  │  ┌──────────────┐  │  │
│  │  │  Slack Bot    │  │  │  │   Promtail    │  │  │  │   Qdrant     │  │  │
│  │  └───────────────┘  │  │  │  (DaemonSet)  │  │  │  │              │  │  │
│  │                     │  │  └───────────────┘  │  │  └──────────────┘  │  │
│  │  ┌───────────────┐  │  │                     │  │                    │  │
│  │  │ Telegram Bot  │  │  │  ┌───────────────┐  │  │                    │  │
│  │  └───────────────┘  │  │  │   Grafana     │  │  │                    │  │
│  │                     │  │  └───────────────┘  │  │                    │  │
│  └─────────────────────┘  └─────────────────────┘  └────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Platform Keuze

| Platform | Development | Production | VPN Support |
|----------|-------------|------------|-------------|
| **Docker Desktop** | ✅ Aanbevolen | ❌ | hostNetwork |
| **Rancher Desktop** | ✅ | ✅ | hostNetwork |
| **K3s / RKE2** | ❌ | ✅ Aanbevolen | VPN sidecar |

### Docker Desktop Setup

1. Open Docker Desktop → Settings → Kubernetes
2. Vink "Enable Kubernetes" aan
3. Klik "Apply & Restart"
4. Wacht tot het groene "Kubernetes running" icoontje verschijnt

### Rancher Desktop Setup

1. Open Rancher Desktop → Preferences → Kubernetes
2. Kies Kubernetes version (1.28+ aanbevolen)
3. Container runtime: containerd of dockerd

---

## Quick Start

### 1. Prerequisites

```bash
# Helm installeren (indien nog niet aanwezig)
brew install helm

# Controleer of Kubernetes draait
kubectl cluster-info
```

### 2. Deploy met één commando

```bash
cd kubernetes

# Maak secrets file (eerste keer)
cp atlas/values-secrets.example.yaml atlas/values-secrets.yaml
# → Vul je credentials in!

# Deploy alles
chmod +x deploy.sh
./deploy.sh
```

### 3. Handmatige stappen (als je meer controle wilt)

```bash
# Helm repos toevoegen
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo add grafana https://grafana.github.io/helm-charts
helm repo add traefik https://traefik.github.io/charts
helm repo add qdrant https://qdrant.github.io/qdrant-helm
helm repo update

# Namespaces
kubectl create namespace atlas
kubectl create namespace logging
kubectl create namespace infra

# Infrastructure
helm install mongodb bitnami/mongodb -n infra -f dependencies/mongodb-values.yaml
helm install qdrant qdrant/qdrant -n infra -f dependencies/qdrant-values.yaml
helm install traefik traefik/traefik -n kube-system -f dependencies/traefik-values.yaml

# Logging
helm install loki grafana/loki-stack -n logging -f logging/loki-stack-values.yaml
kubectl apply -f logging/grafana-dashboards-cm.yaml

# Atlas
helm install atlas ./atlas -n atlas -f atlas/values-dev.yaml -f atlas/values-secrets.yaml
```

---

## VPN Connectiviteit

### Het Probleem

Docker/Kubernetes containers hebben standaard hun eigen netwerk en kunnen niet bij hosts achter je VPN tunnel.

### Oplossing: hostNetwork (Development)

In development mode gebruiken de Atlas pods `hostNetwork: true`. Dit betekent:
- Pod gebruikt het netwerk van je Mac/PC direct
- Heeft toegang tot alles waar jouw machine bij kan, inclusief VPN
- Geen extra configuratie nodig

```yaml
# values-dev.yaml
atlas:
  hostNetwork: true
  dnsPolicy: ClusterFirstWithHostNet
  dnsConfig:
    nameservers:
      - 10.0.10.101    # VPN DNS server 1
      - 10.20.10.15    # VPN DNS server 2
```

### Oplossing: VPN Sidecar (Production)

Voor production waar hostNetwork niet gewenst is:

```yaml
# values-prod.yaml
vpnSidecar:
  enabled: true
  type: openvpn
  configSecret: atlas-vpn-config
```

---

## Toegang tot Services

### Optie 1: Port-forward (Simpelst)

```bash
# Atlas API
kubectl port-forward svc/atlas 8000:8000 -n atlas

# Grafana
kubectl port-forward svc/loki-grafana 3000:80 -n logging
```

Open http://localhost:8000 en http://localhost:3000

### Optie 2: Ingress met /etc/hosts

Voeg toe aan `/etc/hosts`:
```
127.0.0.1 atlas.local grafana.local traefik.local
```

| Service | URL |
|---------|-----|
| Atlas API + UI | http://atlas.local |
| Grafana | http://grafana.local |
| Traefik Dashboard | http://traefik.local/dashboard/ |

### Optie 3: NodePort (Docker Desktop)

Als ingress problemen geeft, gebruik NodePort:

```bash
# Pas service type aan
kubectl patch svc atlas -n atlas -p '{"spec": {"type": "NodePort"}}'

# Bekijk poort
kubectl get svc atlas -n atlas
```

---

## Image Building

### Docker Desktop

Docker images zijn automatisch beschikbaar in Kubernetes:

```bash
# Build image
docker build -t atlas:latest .

# Gebruik in Kubernetes (pullPolicy: Never of IfNotPresent)
```

### Rancher Desktop (containerd)

```bash
# Met nerdctl
nerdctl build -t atlas:latest .

# Of via docker context
docker context use rancher-desktop
docker build -t atlas:latest .
```

---

## Troubleshooting

### Pods starten niet

```bash
# Bekijk pod status
kubectl get pods -n atlas

# Bekijk logs
kubectl logs -f deployment/atlas -n atlas

# Beschrijf pod voor events
kubectl describe pod -l app.kubernetes.io/name=atlas -n atlas
```

### VPN werkt niet in pod

1. Controleer of VPN actief is op host: `ping 10.0.10.101`
2. Controleer of hostNetwork aan staat: `kubectl get pod -n atlas -o yaml | grep hostNetwork`
3. Test DNS in pod: `kubectl exec -it deployment/atlas -n atlas -- nslookup netbox.internal`

### MongoDB connectie faalt

```bash
# Check MongoDB status
kubectl get pods -n infra -l app.kubernetes.io/name=mongodb

# Port-forward voor debugging
kubectl port-forward svc/mongodb 27017:27017 -n infra
mongosh mongodb://localhost:27017
```

### Image pull errors

```bash
# Voor lokale images, zet imagePullPolicy
kubectl patch deployment atlas -n atlas -p '{"spec":{"template":{"spec":{"containers":[{"name":"atlas","imagePullPolicy":"Never"}]}}}}'
```

---

## Directory Structuur

```
kubernetes/
├── README.md                    # Dit bestand
├── deploy.sh                    # One-click deployment
├── .gitignore
│
├── atlas/                       # Atlas Helm chart
│   ├── Chart.yaml
│   ├── values.yaml              # Defaults
│   ├── values-dev.yaml          # Development (hostNetwork)
│   ├── values-prod.yaml         # Production (VPN sidecar)
│   ├── values-secrets.example.yaml
│   └── templates/
│       ├── _helpers.tpl
│       ├── deployment.yaml
│       ├── service.yaml
│       ├── ingress.yaml
│       ├── configmap.yaml
│       ├── secrets.yaml
│       ├── pvc.yaml
│       ├── serviceaccount.yaml
│       ├── slack-bot.yaml
│       ├── telegram-bot.yaml
│       └── NOTES.txt
│
├── dependencies/                # Values voor externe charts
│   ├── mongodb-values.yaml
│   ├── qdrant-values.yaml
│   └── traefik-values.yaml
│
└── logging/                     # PLG Stack
    ├── loki-stack-values.yaml
    └── grafana-dashboards-cm.yaml
```

---

## Upgraden

```bash
# Atlas upgraden na code changes
docker build -t atlas:latest .
helm upgrade atlas ./atlas -n atlas -f atlas/values-dev.yaml -f atlas/values-secrets.yaml

# Force pod restart (als image tag niet verandert)
kubectl rollout restart deployment/atlas -n atlas
```

## Cleanup

```bash
# Alles verwijderen
helm uninstall atlas -n atlas
helm uninstall loki -n logging
helm uninstall qdrant -n infra
helm uninstall mongodb -n infra
helm uninstall traefik -n kube-system

# Namespaces verwijderen
kubectl delete namespace atlas logging infra

# PVCs verwijderen (DATA LOSS!)
kubectl delete pvc --all -n atlas
kubectl delete pvc --all -n infra
kubectl delete pvc --all -n logging
```

---

## Volgende Stappen

1. **Development**: Start met `values-dev.yaml` en hostNetwork
2. **Testen**: Valideer VPN toegang naar NetBox, Zabbix, vCenter
3. **Logging**: Check Grafana voor gecentraliseerde logs
4. **Production**: Migreer naar datacenter met `values-prod.yaml`

Voor vragen: Systems Infrastructure team
