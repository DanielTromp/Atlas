# Claude Code Prompt: Kubernetes Configuration Review

## Context

Infrastructure Atlas wordt gemigreerd van Docker Compose naar Kubernetes. Er is een complete Helm chart setup gemaakt in `/kubernetes/` die moet werken met zowel Docker Desktop als Rancher Desktop voor development, en later productie in het datacenter.

## Doel

Review en valideer de volledige Kubernetes configuratie. Stel bij waar nodig zodat:
1. Development deployment werkt op Docker Desktop met Kubernetes enabled
2. VPN connectiviteit werkt via hostNetwork
3. PLG logging stack (Promtail/Loki/Grafana) correct integreert
4. Helm charts best practices volgen
5. Configuratie klaar is voor productie migratie later

## Te reviewen bestanden

```
kubernetes/
├── README.md
├── deploy.sh
├── test.sh
├── .gitignore
├── atlas/
│   ├── Chart.yaml
│   ├── values.yaml
│   ├── values-dev.yaml
│   ├── values-prod.yaml
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
├── dependencies/
│   ├── mongodb-values.yaml
│   ├── qdrant-values.yaml
│   └── traefik-values.yaml
└── logging/
    ├── loki-stack-values.yaml
    └── grafana-dashboards-cm.yaml
```

## Review Checklist

### 1. Helm Chart Structuur
- [ ] Chart.yaml heeft correcte metadata en versioning
- [ ] values.yaml heeft goede defaults met documentatie
- [ ] _helpers.tpl templates zijn correct en herbruikbaar
- [ ] Alle templates gebruiken correcte indentation (nindent)
- [ ] Labels en selectors zijn consistent

### 2. Deployment Template
- [ ] hostNetwork configuratie werkt correct voor VPN
- [ ] dnsPolicy en dnsConfig zijn correct voor hostNetwork mode
- [ ] Resource limits zijn realistisch voor development
- [ ] Health checks (liveness/readiness) zijn correct geconfigureerd
- [ ] Volume mounts kloppen met PVC definities
- [ ] VPN sidecar configuratie is correct (voor prod)
- [ ] Image pull policy werkt voor lokale images

### 3. Service & Ingress
- [ ] Service type en ports zijn correct
- [ ] Ingress annotations werken met Traefik
- [ ] TLS configuratie is voorbereid voor productie
- [ ] Host-based routing werkt

### 4. ConfigMap & Secrets
- [ ] Alle environment variables uit .env.example zijn meegenomen
- [ ] Secrets worden correct gerefereerd
- [ ] existingSecret optie werkt voor externe secret management
- [ ] Sensitive data staat NIET in configmap

### 5. Persistence
- [ ] PVC templates zijn correct
- [ ] StorageClass configuratie werkt voor Docker Desktop
- [ ] Access modes zijn correct (ReadWriteOnce)

### 6. Bot Deployments (Slack/Telegram)
- [ ] Aparte deployments voor bots
- [ ] Delen dezelfde config/secrets als main deployment
- [ ] Correct command voor bot startup
- [ ] Kunnen onafhankelijk enabled/disabled worden

### 7. Dependencies
- [ ] MongoDB values zijn correct voor Bitnami chart
- [ ] Qdrant values zijn correct
- [ ] Traefik values werken voor zowel Docker Desktop als Rancher

### 8. Logging Stack
- [ ] Loki configuratie is correct
- [ ] Promtail scrape configs pakken Atlas logs
- [ ] Grafana datasource is geconfigureerd
- [ ] Dashboard JSON is valide
- [ ] Retention settings zijn realistisch

### 9. Scripts
- [ ] deploy.sh detecteert platform correct
- [ ] deploy.sh heeft goede error handling
- [ ] test.sh valideert alle componenten
- [ ] Scripts zijn executable (chmod +x)

### 10. Security
- [ ] Secrets worden niet gelogd
- [ ] ServiceAccount is aangemaakt
- [ ] Geen hardcoded credentials
- [ ] .gitignore voorkomt secret commits

## Specifieke Aandachtspunten

### VPN Connectiviteit
De belangrijkste reden voor Kubernetes migratie is VPN toegang. Controleer:
- `hostNetwork: true` in development
- `dnsConfig` met VPN DNS servers (10.0.10.101, 10.20.10.15)
- `dnsPolicy: ClusterFirstWithHostNet`

### Docker Desktop Specifiek
- Images moeten lokaal gebouwd kunnen worden
- `imagePullPolicy: Never` of `IfNotPresent` voor lokale images
- LoadBalancer service type mapped naar localhost

### Environment Variables Mapping
Vergelijk met `/Atlas/.env.example` en zorg dat alle variables beschikbaar zijn:
- MONGODB_URI
- ATLAS_RAG_QDRANT_HOST/PORT
- Alle NETBOX_*, ATLASSIAN_*, ZABBIX_* variables
- Bot tokens (SLACK_*, TELEGRAM_*)

## Verwachte Output

1. **Lijst van gevonden issues** met ernst (kritiek/waarschuwing/suggestie)
2. **Concrete fixes** voor elk issue
3. **Verbeterde bestanden** waar nodig
4. **Test instructies** om te valideren dat alles werkt

## Commando's voor Validatie

```bash
# Helm lint
helm lint kubernetes/atlas

# Template rendering test
helm template atlas kubernetes/atlas -f kubernetes/atlas/values-dev.yaml

# Dry-run install
helm install atlas kubernetes/atlas --dry-run --debug -n atlas -f kubernetes/atlas/values-dev.yaml

# Kubernetes manifest validatie
helm template atlas kubernetes/atlas | kubectl apply --dry-run=client -f -
```

## Na Review

Als alles correct is, documenteer de volgende stappen:
1. Hoe te deployen op een verse Docker Desktop installatie
2. Hoe VPN connectiviteit te testen
3. Hoe logs te bekijken in Grafana
4. Hoe te upgraden na code changes

---

Start de review door eerst alle bestanden te lezen, dan systematisch de checklist door te werken.
