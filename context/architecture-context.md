# Architecture Context

Machine-readable implementation state lives in `context/architecture-state.yaml`. Use that file as the status source of truth before making Jarvis architecture changes.

## Stack

| Layer     | Technology                  | Role   |
| --------- | --------------------------- | ------ |
| OS        | Ubuntu/Debian Linux         | Base operating system |
| Virtualization | Docker, Docker Compose    | Container orchestration |
| Services  | Various (Home Assistant, Mosquitto, etc.) | Homelab applications |
| Networking | Traefik, Nginx              | Reverse proxy and routing |
| Storage   | Local disks, NFS, TrueNAS   | Data persistence |
| Monitoring | Prometheus, Grafana         | Metrics and visualization |
| Logging   | Loki, Promtail              | Log aggregation |
| Automation | Ansible, Bash scripts      | Configuration management |

## System Boundaries

- `docker-compose.yml` — Main container orchestration file
- `services/` — Individual service configurations:
  - `home-assistant/` - Home automation platform
  - `mosquitto/` - MQTT broker
  - `pi-hole/` - Network-wide ad blocking
  - `unifi-controller/` - Network device management
  - `nextcloud/` - Personal cloud storage
  - `vaultwarden/` - Self-hosted password manager
  - `grafana/` - Monitoring and visualization
  - `prometheus/` - Metrics collection
  - `docker-registry/` - Private container registry
- `networks/` — Docker network configurations
- `volumes/` — Persistent storage configurations
- `traefik/` — Reverse proxy and routing configuration
- `ansible/` — Automation playbooks and roles
- `monitoring/` — Monitoring stack configurations
- `backups/` — Backup strategies and scripts
- `docs/` — Documentation files
- `context/` — Project context files (internal documentation, specs, etc.)
- `scripts/` — Helper scripts for maintenance and operations

## Storage Model

- **Local Disks**: Primary storage for media, backups, and service data
- **Network Storage**: NFS shares for centralized data access
- **Container Volumes**: Docker volumes for service-specific persistent data
- **Backup Targets**: External drives or cloud storage for archival backups
- **Database Storage**: Internal databases for services (PostgreSQL, MySQL, SQLite)

## Auth and Access Model

- **Authentication**: Varies by service (local users, LDAP, OAuth, etc.)
- **Access Control**: Role-based access where supported, network segmentation
- **External Access**: Selective exposure via Traefik with authentication
- **Internal Access**: Services accessible within homelab network
- **Management Access**: SSH key-based access for administration

## Invariants

1. All services maintain network isolation where appropriate
2. Data persistence is configured for all stateful services
3. Services expose only necessary ports and interfaces
4. Backup procedures are tested and verified regularly
5. Security updates are applied in a timely manner
6. Resource usage is monitored to prevent exhaustion
7. Configuration changes are version-controlled and reviewed
8. Service dependencies are documented and maintained
9. Jarvis Core owns durable approvals, audit, automations, and orchestration state; other interfaces bridge into it.
10. Jarvis workers expose typed capabilities with deterministic authorization and approval policy. Do not add an unrestricted browser, shell, Docker, Gmail, or filesystem agent.
11. Reversible actions and previews come before consequential actions. Mutating worker results must include verification evidence where practical.
