#!/bin/bash
# Infrastructure Atlas - Kubernetes Quick Start
# Works with Docker Desktop and Rancher Desktop

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}   Infrastructure Atlas - Kubernetes Deployment${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"

# ─────────────────────────────────────────────────────────────────────────────
# Detect platform
# ─────────────────────────────────────────────────────────────────────────────
detect_platform() {
    local context=$(kubectl config current-context 2>/dev/null || echo "unknown")
    
    if [[ "$context" == "docker-desktop" ]]; then
        echo "docker-desktop"
    elif [[ "$context" == "rancher-desktop" ]]; then
        echo "rancher-desktop"
    elif [[ "$context" =~ "k3d" ]]; then
        echo "k3d"
    else
        echo "unknown"
    fi
}

PLATFORM=$(detect_platform)
echo -e "\n${BLUE}Detected platform: ${PLATFORM}${NC}"

# ─────────────────────────────────────────────────────────────────────────────
# Check prerequisites
# ─────────────────────────────────────────────────────────────────────────────
echo -e "\n${YELLOW}Checking prerequisites...${NC}"

if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}✗ kubectl not found. Please install kubectl.${NC}"
    exit 1
fi
echo -e "${GREEN}✓ kubectl found${NC}"

if ! command -v helm &> /dev/null; then
    echo -e "${RED}✗ helm not found. Install with: brew install helm${NC}"
    exit 1
fi
echo -e "${GREEN}✓ helm found${NC}"

if ! kubectl cluster-info &> /dev/null; then
    echo -e "${RED}✗ Cannot connect to Kubernetes cluster.${NC}"
    echo -e "${YELLOW}  For Docker Desktop: Settings → Kubernetes → Enable Kubernetes${NC}"
    echo -e "${YELLOW}  For Rancher Desktop: Preferences → Kubernetes → Enable${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Kubernetes cluster is running${NC}"

# Check for secrets file
if [ ! -f "atlas/values-secrets.yaml" ]; then
    echo -e "\n${YELLOW}Creating secrets file from example...${NC}"
    cp atlas/values-secrets.example.yaml atlas/values-secrets.yaml
    echo -e "${RED}"
    echo "═══════════════════════════════════════════════════════════════"
    echo "  ⚠  ACTIE VEREIST: Vul je credentials in!"
    echo "═══════════════════════════════════════════════════════════════"
    echo -e "${NC}"
    echo "  Edit: kubernetes/atlas/values-secrets.yaml"
    echo ""
    echo "  Minimaal nodig:"
    echo "    - atlasSecretKey (genereer met: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\")"
    echo "    - atlasUiSecret (genereer met: python -c \"import secrets; print(secrets.token_hex(32))\")"
    echo "    - netboxUrl + netboxToken"
    echo "    - anthropicApiKey"
    echo ""
    echo "  Daarna: ./deploy.sh opnieuw uitvoeren"
    echo ""
    exit 1
fi

# ─────────────────────────────────────────────────────────────────────────────
# Add Helm repositories
# ─────────────────────────────────────────────────────────────────────────────
echo -e "\n${YELLOW}Adding Helm repositories...${NC}"
helm repo add bitnami https://charts.bitnami.com/bitnami 2>/dev/null || true
helm repo add grafana https://grafana.github.io/helm-charts 2>/dev/null || true
helm repo add traefik https://traefik.github.io/charts 2>/dev/null || true
helm repo add qdrant https://qdrant.github.io/qdrant-helm 2>/dev/null || true
helm repo update > /dev/null
echo -e "${GREEN}✓ Helm repositories updated${NC}"

# ─────────────────────────────────────────────────────────────────────────────
# Create namespaces
# ─────────────────────────────────────────────────────────────────────────────
echo -e "\n${YELLOW}Creating namespaces...${NC}"
kubectl create namespace atlas --dry-run=client -o yaml | kubectl apply -f - > /dev/null
kubectl create namespace logging --dry-run=client -o yaml | kubectl apply -f - > /dev/null
kubectl create namespace infra --dry-run=client -o yaml | kubectl apply -f - > /dev/null
echo -e "${GREEN}✓ Namespaces created${NC}"

# ─────────────────────────────────────────────────────────────────────────────
# Build Atlas image
# ─────────────────────────────────────────────────────────────────────────────
echo -e "\n${YELLOW}Building Atlas Docker image...${NC}"

cd ..

if [[ "$PLATFORM" == "docker-desktop" ]]; then
    docker build -t atlas:latest . -q
    echo -e "${GREEN}✓ Image built with Docker${NC}"
elif [[ "$PLATFORM" == "rancher-desktop" ]]; then
    if command -v nerdctl &> /dev/null; then
        nerdctl build -t atlas:latest . -q
        echo -e "${GREEN}✓ Image built with nerdctl${NC}"
    else
        docker build -t atlas:latest . -q
        echo -e "${GREEN}✓ Image built with Docker${NC}"
    fi
else
    docker build -t atlas:latest . -q
    echo -e "${GREEN}✓ Image built${NC}"
fi

cd kubernetes

# ─────────────────────────────────────────────────────────────────────────────
# Deploy Infrastructure
# ─────────────────────────────────────────────────────────────────────────────
echo -e "\n${YELLOW}Deploying MongoDB...${NC}"
helm upgrade --install mongodb bitnami/mongodb \
    -n infra \
    -f dependencies/mongodb-values.yaml \
    --wait --timeout 3m > /dev/null
echo -e "${GREEN}✓ MongoDB deployed${NC}"

echo -e "\n${YELLOW}Deploying Qdrant...${NC}"
helm upgrade --install qdrant qdrant/qdrant \
    -n infra \
    -f dependencies/qdrant-values.yaml \
    --wait --timeout 3m > /dev/null
echo -e "${GREEN}✓ Qdrant deployed${NC}"

echo -e "\n${YELLOW}Deploying Traefik Ingress...${NC}"
helm upgrade --install traefik traefik/traefik \
    -n kube-system \
    -f dependencies/traefik-values.yaml \
    --wait --timeout 2m > /dev/null
echo -e "${GREEN}✓ Traefik deployed${NC}"

# ─────────────────────────────────────────────────────────────────────────────
# Deploy Logging Stack
# ─────────────────────────────────────────────────────────────────────────────
echo -e "\n${YELLOW}Deploying Loki logging stack...${NC}"
helm upgrade --install loki grafana/loki-stack \
    -n logging \
    -f logging/loki-stack-values.yaml \
    --wait --timeout 5m > /dev/null
echo -e "${GREEN}✓ Loki stack deployed${NC}"

echo -e "\n${YELLOW}Applying Grafana dashboards...${NC}"
kubectl apply -f logging/grafana-dashboards-cm.yaml > /dev/null
echo -e "${GREEN}✓ Dashboards configured${NC}"

# ─────────────────────────────────────────────────────────────────────────────
# Deploy Atlas
# ─────────────────────────────────────────────────────────────────────────────
echo -e "\n${YELLOW}Deploying Infrastructure Atlas...${NC}"
helm upgrade --install atlas ./atlas \
    -n atlas \
    -f atlas/values-dev.yaml \
    -f atlas/values-secrets.yaml \
    --set atlas.image.pullPolicy=Never \
    --wait --timeout 3m > /dev/null
echo -e "${GREEN}✓ Atlas deployed${NC}"

# ─────────────────────────────────────────────────────────────────────────────
# Wait and verify
# ─────────────────────────────────────────────────────────────────────────────
echo -e "\n${YELLOW}Waiting for pods to be ready...${NC}"
sleep 5

kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=atlas -n atlas --timeout=120s 2>/dev/null || true

# ─────────────────────────────────────────────────────────────────────────────
# Print status
# ─────────────────────────────────────────────────────────────────────────────
echo -e "\n${GREEN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}   ✓ Deployment Complete!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"

echo -e "\n${BLUE}Pod Status:${NC}"
kubectl get pods -n atlas --no-headers 2>/dev/null | while read line; do
    echo "  $line"
done

echo -e "\n${BLUE}Toegang via Port-Forward (aanbevolen):${NC}"
echo "  Atlas:   kubectl port-forward svc/atlas 8000:8000 -n atlas"
echo "  Grafana: kubectl port-forward svc/loki-grafana 3000:80 -n logging"
echo ""
echo "  Open: http://localhost:8000 (Atlas)"
echo "  Open: http://localhost:3000 (Grafana, admin/atlas-logs)"

echo -e "\n${BLUE}Of via Ingress:${NC}"
echo "  Voeg toe aan /etc/hosts:"
echo "    127.0.0.1 atlas.local grafana.local"
echo ""
echo "  Open: http://atlas.local"
echo "  Open: http://grafana.local"

echo -e "\n${BLUE}Handige commando's:${NC}"
echo "  kubectl get pods -A                     # Alle pods"
echo "  kubectl logs -f deploy/atlas -n atlas   # Atlas logs"
echo "  helm list -A                            # Helm releases"

echo -e "\n${BLUE}Upgrade na code changes:${NC}"
echo "  docker build -t atlas:latest . && kubectl rollout restart deploy/atlas -n atlas"
echo ""
