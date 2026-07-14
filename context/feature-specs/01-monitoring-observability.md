# Monitoring & Observability Feature Spec

## Overview
Implement comprehensive monitoring and observability stack covering metrics, logs, and tracing for the homelab infrastructure. This stack will provide visibility into system health, performance, and application behavior without requiring manual dashboard configuration.

## Components
- **Prometheus**: Metrics collection and storage
- **Grafana**: Visualization and alerting dashboard
- **Loki**: Log aggregation system
- **Promtail**: Log shipping agent
- **Node Exporter**: System-level metrics collector
- **cAdvisor**: Container metrics collector
- **Alertmanager**: Alert handling and routing

## Implementation Plan (Single AI Execution)

### Phase 1: Infrastructure Deployment
1. **Create monitoring namespace/directory structure**:
   ```
   mkdir -p monitoring/{prometheus,grafana,loki,promtail}
   ```

2. **Deploy Prometheus**:
   - Create `prometheus/prometheus.yml` with scrape configs for:
     - Node Exporter (host metrics)
     - cAdvisor (container metrics)
     - All existing services with metrics endpoints
     - Prometheus self-scraping
   - Create `prometheus/alert.rules` with predefined alerts:
     - High CPU usage (>85% for 5min)
     - High memory usage (>90% for 5min)
     - Disk space low (<10% free)
     - Container restart loops
     - Service downtime (via blackbox exporter later)

3. **Deploy Grafana**:
   - Create `grafana/provisioning/datasources/datasource.yml` pointing to Prometheus
   - Create `grafana/provisioning/dashboards/dashboard.yml` for automatic dashboard loading
   - Import essential dashboards:
     - Node Exporter Full
     - Docker Monitoring
     - Homelab Overview (custom)
     - Service Health Summary

4. **Deploy Loki Stack**:
   - Create `loki/loki-config.yaml` with:
     - Schema config for Loki 2.x
     - Storage configuration (local filesystem)
     - Table management
   - Create `promtail/promtail-config.yaml` to scrape:
     - Docker container logs
     - System logs (/var/log/*.log)
     - Application-specific logs from services

5. **Deploy Exporters**:
   - Node Exporter: Host-level metrics collection
   - cAdvisor: Container resource usage
   - (Optional) Blackbox Exporter: Endpoint probing

### Phase 2: Configuration & Automation
1. **Automated Service Discovery**:
   - Configure Prometheus to auto-discover services via Docker labels
   - Use relabeling to filter and standardize metric names

2. **Pre-built Dashboard Automation**:
   - Create script to automatically import dashboards on Grafana startup
   - Use Grafana's provisioning system for declarative dashboard management

3. **Alert Routing Setup**:
   - Configure Alertmanager to route alerts to:
     - Email (for critical alerts)
     - n8n workflow (for enrichment and routing)
     - Telegram/Mattermost (for team notifications)
   - Create inhibition rules to prevent alert storms

4. **Log Enrichment**:
   - Configure Promtail to add labels from Docker metadata
   - Extract structured logs where possible (JSON format)
   - Add trace IDs where services support it

### Phase 3: Self-Healing & Intelligence
1. **Auto-Remediation Triggers**:
   - Create Alertmanager webhook receiver that triggers n8n workflows
   - Example workflows:
     - High memory → Attempt graceful service restart
     - Disk full → Trigger cleanup scripts
     - Service down → Attempt restart via Docker API

2. **Predictive Elements**:
   - Use Prometheus forecasting functions for capacity planning
   - Create recording rules for derived metrics (e.g., request rates, error budgets)
   - Set up trend analysis for resource growth

### Phase 4: Documentation & Handoff
1. **Auto-generated Documentation**:
   - Create n8n workflow that queries Prometheus for service metadata
   - Generate/update README with:
     - Service dependency graph
     - Current resource usage
     - Health status badges
     - Links to relevant Grafana panels

2. **Runbook Automation**:
   - Create dynamic runbooks that adjust based on current system state
   - Include one-click remediation buttons in Grafana panels
   - Link alerts to specific troubleshooting procedures

## Success Criteria
- All core services export metrics via Prometheus format
- Centralized logging with searchable logs in Grafana Explore
- Pre-configured dashboards showing system health at a glance
- Automated alerting with intelligent routing
- Self-healing capabilities for common failure modes
- Zero-click observability - no manual dashboard creation needed

## Files to Create/Modify
```
context/feature-specs/01-monitoring-observability.md  (this file)
phase1-core/docker-compose.yml                        (add monitoring services)
monitoring/prometheus/prometheus.yml                  (Prometheus config)
monitoring/prometheus/alert.rules                     (Alert rules)
monitoring/grafana/provisioning/datasources/datasource.yml (Grafana datasource)
monitoring/grafana/provisioning/dashboards/dashboard.yml (Dashboard provisioning)
monitoring/loki/loki-config.yaml                      (Loki config)
monitoring/promtail/promtail-config.yaml              (Promtail config)
scripts/deploy-monitoring.sh                          (Deployment helper script)
```

## Dependencies
- Docker Compose v2+
- Sufficient resources (recommend 2GB RAM for monitoring stack)
- Existing phase1-core services running
- Network connectivity between services

## Estimated Effort
Single AI execution to deploy entire stack with configuration. Additional time may be needed for fine-tuning alert thresholds and dashboard customization based on actual usage patterns.