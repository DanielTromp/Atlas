#!/bin/bash
# Test script voor Atlas Kubernetes deployment
# Controleert of alles correct draait

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${YELLOW}   Infrastructure Atlas - Deployment Test${NC}"
echo -e "${YELLOW}═══════════════════════════════════════════════════════════════${NC}"

# ─────────────────────────────────────────────────────────────────────────────
# Check pods
# ─────────────────────────────────────────────────────────────────────────────
echo -e "\n${YELLOW}Checking pod status...${NC}"

echo -e "\n${YELLOW}Atlas namespace:${NC}"
kubectl get pods -n atlas -o wide

echo -e "\n${YELLOW}Infra namespace:${NC}"
kubectl get pods -n infra -o wide

echo -e "\n${YELLOW}Logging namespace:${NC}"
kubectl get pods -n logging -o wide

# ─────────────────────────────────────────────────────────────────────────────
# Check services
# ─────────────────────────────────────────────────────────────────────────────
echo -e "\n${YELLOW}Checking services...${NC}"
kubectl get svc -n atlas
kubectl get svc -n infra
kubectl get svc -n logging

# ─────────────────────────────────────────────────────────────────────────────
# Test Atlas API
# ─────────────────────────────────────────────────────────────────────────────
echo -e "\n${YELLOW}Testing Atlas API health endpoint...${NC}"

# Port forward in background
kubectl port-forward svc/atlas 18000:8000 -n atlas &
PF_PID=$!
sleep 3

if curl -s http://localhost:18000/api/health > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Atlas API is responding${NC}"
    curl -s http://localhost:18000/api/health | head -c 200
    echo ""
else
    echo -e "${RED}✗ Atlas API not responding${NC}"
fi

kill $PF_PID 2>/dev/null || true

# ─────────────────────────────────────────────────────────────────────────────
# Test VPN connectivity from pod
# ─────────────────────────────────────────────────────────────────────────────
echo -e "\n${YELLOW}Testing VPN connectivity from Atlas pod...${NC}"

ATLAS_POD=$(kubectl get pod -n atlas -l app.kubernetes.io/name=atlas -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)

if [ -n "$ATLAS_POD" ]; then
    echo "Pod: $ATLAS_POD"
    
    # Test DNS resolution
    echo -e "\n${YELLOW}Testing DNS resolution for VPN hosts...${NC}"
    
    # Get NETBOX_URL from secret (not configmap)
    NETBOX_HOST=$(kubectl get secret atlas-secrets -n atlas -o jsonpath='{.data.NETBOX_URL}' 2>/dev/null | base64 -d 2>/dev/null | sed 's|https://||' | sed 's|/.*||')
    
    if [ -n "$NETBOX_HOST" ]; then
        echo "Testing: $NETBOX_HOST"
        if kubectl exec -n atlas "$ATLAS_POD" -- sh -c "getent hosts $NETBOX_HOST" 2>/dev/null; then
            echo -e "${GREEN}✓ DNS resolution works for $NETBOX_HOST${NC}"
        else
            echo -e "${RED}✗ Cannot resolve $NETBOX_HOST - VPN DNS might not be configured${NC}"
        fi
    fi
    
    # Test connectivity
    echo -e "\n${YELLOW}Testing network connectivity...${NC}"
    
    # Test MongoDB
    if kubectl exec -n atlas "$ATLAS_POD" -- sh -c "nc -z mongodb.infra.svc.cluster.local 27017" 2>/dev/null; then
        echo -e "${GREEN}✓ Can reach MongoDB${NC}"
    else
        echo -e "${RED}✗ Cannot reach MongoDB${NC}"
    fi
    
    # Test Qdrant
    if kubectl exec -n atlas "$ATLAS_POD" -- sh -c "nc -z qdrant.infra.svc.cluster.local 6333" 2>/dev/null; then
        echo -e "${GREEN}✓ Can reach Qdrant${NC}"
    else
        echo -e "${RED}✗ Cannot reach Qdrant${NC}"
    fi
else
    echo -e "${RED}✗ No Atlas pod found${NC}"
fi

# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────
echo -e "\n${YELLOW}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${YELLOW}   Test Complete${NC}"
echo -e "${YELLOW}═══════════════════════════════════════════════════════════════${NC}"

echo -e "\n${YELLOW}Quick access:${NC}"
echo "  kubectl port-forward svc/atlas 8000:8000 -n atlas"
echo "  kubectl port-forward svc/loki-grafana 3000:80 -n logging"
echo ""
echo "  Atlas:   http://localhost:8000"
echo "  Grafana: http://localhost:3000 (admin / atlas-logs)"
