#!/bin/bash
# Generate self-signed certificates with a local CA
# Usage: ./generate-certs.sh [domain1] [domain2] ...
#
# Example: ./generate-certs.sh atlas.internal atlas-dev.internal
#
# Output: /var/lib/data/traefik/certs/
#   - ca.crt       (CA certificate - install in browsers)
#   - ca.key       (CA private key - keep secure)
#   - atlas.crt    (Server certificate)
#   - atlas.key    (Server private key)

set -e

CERT_DIR="/var/lib/data/traefik/certs"
DOMAINS="${@:-atlas.internal atlas-dev.internal}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Atlas Certificate Generator ===${NC}"
echo "Domains: $DOMAINS"
echo "Output: $CERT_DIR"
echo ""

# Create cert directory
mkdir -p "$CERT_DIR"
cd "$CERT_DIR"

# Generate CA if it doesn't exist
if [ ! -f ca.key ]; then
    echo -e "${YELLOW}Generating CA certificate...${NC}"

    # CA private key
    openssl genrsa -out ca.key 4096

    # CA certificate (valid for 10 years)
    openssl req -x509 -new -nodes \
        -key ca.key \
        -sha256 \
        -days 3650 \
        -out ca.crt \
        -subj "/C=NL/ST=Netherlands/L=Amsterdam/O=Atlas Internal/CN=Atlas CA"

    echo -e "${GREEN}CA certificate generated: ca.crt${NC}"
else
    echo -e "${YELLOW}Using existing CA certificate${NC}"
fi

# Build SAN (Subject Alternative Names) string
SAN="DNS:localhost,IP:127.0.0.1"
for domain in $DOMAINS; do
    SAN="$SAN,DNS:$domain"
done

echo "SAN: $SAN"

# Generate server certificate
echo -e "${YELLOW}Generating server certificate...${NC}"

# Server private key
openssl genrsa -out atlas.key 2048

# Certificate Signing Request
openssl req -new \
    -key atlas.key \
    -out atlas.csr \
    -subj "/C=NL/ST=Netherlands/L=Amsterdam/O=Atlas/CN=atlas.internal"

# Create extension file for SAN
cat > atlas.ext << EOF
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage = digitalSignature, nonRepudiation, keyEncipherment, dataEncipherment
subjectAltName = $SAN
EOF

# Sign the certificate with our CA (valid for 2 years)
openssl x509 -req \
    -in atlas.csr \
    -CA ca.crt \
    -CAkey ca.key \
    -CAcreateserial \
    -out atlas.crt \
    -days 730 \
    -sha256 \
    -extfile atlas.ext

# Cleanup
rm -f atlas.csr atlas.ext

# Set permissions
chmod 600 ca.key atlas.key
chmod 644 ca.crt atlas.crt

echo ""
echo -e "${GREEN}=== Certificates Generated ===${NC}"
echo ""
echo "Files created in $CERT_DIR:"
ls -la "$CERT_DIR"
echo ""
echo -e "${YELLOW}To trust these certificates:${NC}"
echo ""
echo "On RHEL/Rocky/Alma Linux:"
echo "  sudo cp $CERT_DIR/ca.crt /etc/pki/ca-trust/source/anchors/atlas-ca.crt"
echo "  sudo update-ca-trust"
echo ""
echo "On Ubuntu/Debian:"
echo "  sudo cp $CERT_DIR/ca.crt /usr/local/share/ca-certificates/atlas-ca.crt"
echo "  sudo update-ca-certificates"
echo ""
echo "On macOS:"
echo "  sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain $CERT_DIR/ca.crt"
echo ""
echo "In browsers:"
echo "  Import ca.crt as a trusted Certificate Authority"
echo ""
