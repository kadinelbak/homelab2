# Self-Documenting Infrastructure Feature Spec

## Overview
Create a homelab that documents itself—automatically generating up-to-date architecture diagrams, service dependencies, configuration summaries, and operational runbooks. This spec ensures documentation stays current with zero manual effort, reducing knowledge silos and making the system accessible to newcomers (including future you).

## Core Components
- **Automated Diagram Generation**: Service dependency graphs, network topology, data flow diagrams from docker-compose files and runtime state
- **Live Configuration Documentation**: Real-time view of active configurations, environment variables, and mounted volumes
- **Service Catalog**: Auto-discovered registry of all services with descriptions, versions, owners, and health status
- **Runbook Generation**: Procedural documentation that adapts to current system state (e.g., "How to restart X" based on actual deployment)
- **Change History & Versioning**: Git-based tracking of infrastructure changes with automated commit messages
- **Knowledge Base Integration**: Linking to troubleshooting guides, FAQs, and decision records
- **Documentation Dashboard**: Centralized view of all generated documentation
- **Accuracy Validation**: Mechanisms to detect and alert on documentation drift

## Implementation Plan (Single AI Execution Focus)

### Phase 1: Metadata Collection Framework
1. **Standardize Service Metadata**:
   - Require all services to include labels:
     - `homelab.service.name`: Human-readable name
     - `homelab.service.description`: Short description
     - `homelab.service.version`: Image tag or version
     - `homelab.service.owner`: Team or person responsible
     - `homelab.service.tier`: critical|important|background
     - `homelab.service.documentation`: URL to detailed docs
     - `homelab.service.dependencies`: Comma-separated list of service names
   - Add these labels to existing services in docker-compose files
   - For services without labels support, use annotations in a sidecar or external registry

2. **Create Metadata Collector Service**:
   - Lightweight service that:
     - Queries Docker API for container labels and state
     - Reads docker-compose files for service definitions
     - Pulls image metadata from registry (if available)
     - Collects runtime state: health status, resource usage, uptime
     - Exposes metadata via REST API and/or Prometheus metrics
   - Add to phase1-core/docker-compose.yml:
     ```yaml
     metadata:
       image: appropriate/curl:latest  # Will replace with custom
       container_name: homelab_metadata
       restart: unless-stopped
       volumes:
         - /var/run/docker.sock:/var/run/docker.sock:ro
         - ${DATA_PATH}/phase1-core:/phase1-core:ro
         - ${DATA_PATH}/phase2-media:/phase2-media:ro
         - ${DATA_PATH}/phase3-ai-gaming:/phase3-ai-gaming:ro
         - ${DATA_PATH}/phase4-ondemand:/phase4-ondemand:ro
       command: ["sh", "-c", "while true; do /collect/metadata.sh; sleep 30; done"]
       labels:
         - "com.centurylinklabs.watchtower.enable=true"
         - "homepage.group=Maintenance"
         - "homepage.name=Metadata Collector"
         - "homepage.description=Collects service metadata"
     ```
   - Create `/collect/metadata.sh` that outputs JSON to a file or serves via simple HTTP

### Phase 2: Dependency Graph & Architecture Diagrams
1. **Service Dependency Extraction**:
   - From labels: `homelab.service.dependencies`
   - From docker-compose: `depends_on`, `links`, shared networks
   - From runtime: DNS queries, network connections (netstat/ss), shared volumes
   - From configuration: e.g., `database_host: homelab_postgres` implies dependency

2. **Diagram Generation**:
   - Use Graphviz, Mermaid, or PlantUML to generate diagrams:
     - **Service Dependency Graph**: Who calls whom
     - **Data Flow Diagram**: How data moves between services (DB, cache, storage)
     - **Network Topology**: Docker networks, external connections (Tailscale, WAN)
     - **Deployment View**: Which services run on which nodes (if multi-node)
     - **Dependency Heatmap**: Criticality and usage frequency
   - Script: `scripts/generate-diagrams.sh` that:
     - Queries metadata collector
     - Creates `.dot` or `.mmd` files
     - Renders to SVG/PNG using `dot` or `mmdc`
     - Stores in `${DATA_PATH}/documentation/diagrams/`

3. **Automated Diagram Updates**:
   - Run diagram generation:
     - On every docker-compose up/down (via post-start hook)
     - Every hour via cron
     - On metadata change detection
   - Integrate with monitoring: alert if diagram generation fails

### Phase 3: Live Configuration Documentation
1. **Configuration Export Service**:
   - For each service, generate markdown documentation of:
     - Effective environment variables (with sources: .env, docker-compose, defaults)
     - Mounted volumes and their purpose
     - Exposed ports and protocols
     - Healthcheck configuration
     - Resource limits and reservations
     - Labels and annotations
   - Use: `docker inspect --format` or Docker API
   - Template: Jinja2 or simple bash to generate markdown

2. **Configuration Change Detection**:
   - Track changes to:
     - docker-compose files (git)
     - .env file (git)
     - Service-specific configs under `${DATA_PATH}`
   - Use git diff to show what changed between versions
   - Highlight: Secrets changes (redact values but show keys changed)

3. **Config Validation & Drift Detection**:
   - Compare desired state (git) vs actual state (Docker API)
   - Alert on: 
     - Container running different image than specified
     - Missing volume mounts
     - Incorrect environment variables
     - Extra/labels missing
   - Simple: `docker compose config` vs `docker inspect` comparison

### Phase 4: Service Catalog & Registry
1. **Auto-generated Service Catalog**:
   - Markdown file: `docs/SERVICES.md` with table:
     | Service | Description | Version | Tier | Health | Dependencies | Documentation |
     |---------|-------------|---------|------|--------|--------------|---------------|
     | postgres | Central DB | 16-alpine | critical | healthy | - | [link] |
     | jellyfin | Media Server | latest | important | healthy | postgres, redis | [link] |
   - Generated nightly or on change
   - Include badges for health status (if metrics available)
   - Link to source: docker-compose file and line number

2. **Service Discovery Endpoint**:
   - Simple JSON API: `/api/services` returning:
     ```json
     {
       "services": [
         {
           "name": "postgres",
           "description": "Central PostgreSQL database",
           "version": "16-alpine",
           "tier": "critical",
           "health": "healthy",
           "dependencies": [],
           "documentation": "https://docs.homelab.internal/services/postgres"
         }
       ]
     }
     ```
   - Powered by metadata collector

### Phase 5: Adaptive Runbook Generation
1. **Context-Aware Documentation**:
   - Generate runbooks that reflect current deployment:
     - "How to restart PostgreSQL" → Based on actual docker-compose service name and restart policy
     - "How to backup Immich" → Points to actual volume locations and includes current pg_dump command
     - "How to scale Jellyfin" → Shows current resource limits and how to adjust via docker update
   - Template examples:
     ```
     To restart {{service.name}}:
     1. Identify container: `docker ps --filter name={{service.container_name}}`
     2. Restart: `docker restart {{service.container_name}}`
     3. Verify: `docker logs --since 1m {{service.container_name}}`
     ```
   - Variables filled from metadata: `service.container_name`, `service.restart_policy`

2. **Runbook Templates Library**:
   - Create templates for common operations:
     - `templates/runbook/restart-service.md`
     - `templates/runbook/backup-service.md`
     - `templates/runbook/update-service.md`
     - `templates/runbook/troubleshoot-service.md`
     - `templates/runbook/view-logs.md`
   - Use metadata to fill in service-specific details

3. **Runbook Delivery Mechanisms**:
   - Web interface: Browseable `docs/runbooks/`
   - ChatOps: n8n workflow that returns runbook snippet when asked
   - CLI: `homelab runbook <service> <operation>`
   - IDE plugins: Copy-paste ready snippets

### Phase 6: Change History & Knowledge Integration
1. **Automated Changelog Generation**:
   - From git commits: Generate `docs/CHANGELOG.md` with:
     - Infrastructure changes (docker-compose edits)
     - Version bumps (image tag changes)
     - Configuration modifications (.env edits)
     - Service additions/removals
   - Format: Keep a Changelog style or conventional commits
   - Script: `scripts/generate-changelog.sh` that runs on git push or daily

2. **Decision Records (ADR) Integration**:
   - Automatically suggest ADR creation for significant changes:
     - Changing database version
     - Adding new major service
     - Altering security model
     - Changing network topology
   - Template: `docs/adr/0001-use-postgres-16.md`
   - Script: `scripts/check-for-adr.sh` that looks for significant changes in PRs or commits

3. **FAQ & Troubleshooting Auto-generation**:
   - From monitoring alerts: Create troubleshooting guides for common alert patterns
   - From n8n workflows: Document common automation patterns
   - From commit messages: Extract "why" changes were made
   - Simple: `scripts/generate-faq.sh` that creates Q&A from templates and data

### Phase 7: Documentation Dashboard & Validation
1. **Documentation Hub**:
   - Simple static site or dashboard showing:
     - Last updated timestamps for each doc type
     - Diagram freshness indicator
     - Service catalog search
     - Recent changes feed
     - Documentation coverage percentage
   - Could be a simple homepage tile or Grafana dashboard with text panels

2. **Accuracy Monitoring**:
   - **Diagram Validation**: Compare generated dependencies with actual runtime connections (netstat, lsof)
   - **Config Validation**: As in Phase 3, report drift percentage
   - **Link Validation**: Check that documentation URLs are reachable
   - **Staleness Detection**: Alert if any documentation type hasn't updated in X hours
   - **Coverage Measurement**: % of services with descriptions, owners, etc.

3. **Feedback Loop**:
   - Allow users to upvote/downvote documentation usefulness
   - Track which docs are most accessed
   - Suggest improvements: "Service X has no owner assigned"

## Success Criteria
- Architecture diagrams are automatically generated and updated within 5 minutes of any infrastructure change
- Service catalog is always accurate: lists all running services with correct versions and health status
- Configuration documentation shows effective values (not just docker-compose defaults)
- Runbooks reflect actual deployment: commands match current service names, volume paths, and configurations
- Change history captures all infrastructure modifications with clear, searchable commit messages
- Documentation dashboard shows >95% accuracy across all documentation types
- Mean time to detect documentation drift: < 15 minutes
- New contributor can understand system architecture and perform basic operations in < 15 minutes using generated docs
- Documentation is accessible via multiple formats: web, CLI, and IDE integrations
- No manual documentation updates required for routine infrastructure changes
- Documentation includes decision rationale for significant architectural choices
- Troubleshooting guides are generated for common alert patterns from monitoring stack
- Service dependencies are accurately captured: both declared (depends_on) and discovered (runtime)
- Documentation generation process itself is monitored and alerts on failures

## Files to Create/Modify
```
context/feature-specs/10-self-documenting-infrastructure.md  (this file)
scripts/generate-diagrams.sh                                 (Dependency graph & diagrams)
scripts/export-config.sh                                     (Live config exporter)
scripts/generate-service-catalog.md                          (Service catalog generator)
scripts/generate-changelog.sh                                (From git history)
scripts/generate-faq.sh                                      (From alerts & templates)
scripts/validate-documentation.sh                            (Accuracy checker)
metadata/                                                    (Metadata collector service)
  - Dockerfile
  - collect/metadata.sh
  - config/
templates/
  - runbook/
    - restart-service.md
    - backup-service.md
    - update-service.md
    - troubleshoot-service.md
    - view-logs.md
  - diagram/
    - dependency-graph.mmd
    - data-flow.mmd
    - network-topology.mmd
docs/                                                        (Output directory)
  - SERVICES.md
  - CHANGELOG.md
  - diagrams/
    - service-dependency.svg
    - data-flow.svg
  - runbooks/
  - adr/
  - FAQ.md
monitoring/grafana/provisioning/dashboards/documentation-dashboard.json
scripts/post-deploy.sh                                       (Extend to trigger initial doc gen)
.env                                                         (Add any needed vars for doc generation)
README.md                                                    (Auto-updated section)
```

## Dependencies
- Docker API access (via socket mount)
- Graphviz (`dot`) or Mermaid CLI (`mmdc`) or PlantUML for diagram rendering
- Git for change history and config tracking
- Jinja2 or similar templating engine (or bash string substitution)
- Basic understanding of service dependencies and infrastructure components
- Optional: Web framework for metadata API (can use simple netcat or Python http.server)
- Optional: Graph database for complex dependency queries (not needed for MVP)

## Estimated Effort
Single AI execution to:
- Define metadata labeling standard for services
- Create metadata collector service that queries Docker API and docker-compose files
- Implement dependency extraction from labels, compose files, and runtime state
- Create diagram generation scripts using Graphviz/Mermaid
- Build live configuration exporter using Docker inspect
- Create service catalog and changelog generators
- Design runbook templating system
- Specify documentation dashboard components
Actual diagram styling, template refinement, and validation tuning will require iteration but the foundation for self-documenting infrastructure is achievable in one go.