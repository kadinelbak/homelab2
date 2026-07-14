# Service Mesh for Resilient Communication Feature Spec

## Overview
Implement a lightweight service mesh to enhance reliability, security, and observability of service-to-service communication within the homelab. This spec introduces traffic management, mutual TLS encryption, retry logic, circuit breaking, and distributed tracing without requiring significant application changes. The goal is to make inter-service communication more resilient to failures, secure against eavesdropping, and observable for debugging and performance tuning.

## Core Components
- **Service Mesh Control Plane**: Manages configuration and policies (could be Consul, Linkerd, or Istio lite)
- **Data Plane Proxies**: Sidecar containers that intercept and manage traffic (e.g., Envoy)
- **Mutual TLS (mTLS)**: Automatic encryption and authentication between services
- **Traffic Management**: Retries, timeouts, circuit breaking, fault injection, traffic splitting
- **Observability**: Distributed tracing, metrics, and access logs for all inter-service calls
- **Security Policies**: Authorization rules, JWT validation, and traffic access controls
- **Ingress/Egress Control**: Manage traffic entering and leaving the mesh
- **Mesh Dashboard**: Visualization of service dependencies, traffic flows, and error rates

## Implementation Plan (Single AI Execution - Lightweight Approach)

Given the scope of a homelab and single execution constraint, we'll implement a simplified service mesh using:
- **Consul** as the control plane (service discovery, configuration, basic mesh features)
- **Envoy sidecars** via Docker Compose dependencies (lightweight alternative to full sidecar injection)
- **Focus on key benefits**: mTLS, retries, observability for critical service connections

### Phase 1: Deploy Consul Control Plane
1. **Add Consul Server** to phase1-core/docker-compose.yml:
   ```yaml
   consul-server:
     image: hashicorp/consul:latest
     container_name: homelab_consul
     restart: unless-stopped
     command: agent -server -bootstrap-expect=1 -ui -client=0.0.0.0
     ports:
       - "8500:8500"  # UI
       - "8600:8600/tcp"  # DNS interface
       - "8600:8600/udp"
     volumes:
       - ${DATA_PATH}/phase1-core/data/consul:/consul/data
     environment:
       - CONSUL_LOCAL_CONFIG={"leave_on_terminate": true}
     networks:
       - homelab_internal
     labels:
       - "com.centurylinklabs.watchtower.enable=true"
       - "homepage.group=Maintenance"
       - "homepage.name=Consul UI"
       - "homepage.href=http://${DOMAIN}:8500"
       - "homepage.description=Service discovery & mesh control"
   ```
2. **Configure Consul Clients** (implicit via joining network):
   - Services will join the Consul cluster by being on the same network
   - Or use `consul agent -join` in entrypoint for explicit joining
3. **Set Up DNS Forwarding** (Optional but recommended):
   - Configure Docker to use Consul for `.consul` domain:
     - Or use Consul's DNS interface directly: `service.consul`
   - For simplicity, we'll use Consul's built-in DNS: `service.service.consul`

### Phase 2: Enable mTLS for Critical Service Connections
1. **Generate Consul CA and Certificates**:
   - Consul can auto-generate CA when in server mode
   - Or use: `consul tls ca create` etc. (we'll rely on auto-generation)
2. **Configure Services to Use Consul Connect**:
   - For each service we want to protect, we'll deploy an Envoy sidecar
   - Instead of direct service-to-service, traffic goes: Service A → Envoy A → Consul → Envoy B → Service B
3. **Select Pilot Services** (Start with high-value connections):
   - **Grafana → Prometheus** (for dashboard queries)
   - **Prometheus → Node Exporter** (for metrics scraping)
   - **Loki → Promtail** (for log shipping)
   - **n8n → Ollama** (for AI workflows)
   - **Homepage → Authentik** (for SSO validation)
   - **Actual approach**: We'll demonstrate with one pair, then document the pattern

### Phase 3: Deploy Envoy Sidecars for Pilot Connection
Let's implement **Grafana → Prometheus with mTLS** as an example:

1. **Create Consul Service Definitions** (via CLI or config):
   ```bash
   # After Consul is up, register services
   consul services register -name=grafana -port=3000
   consul services register -name=prometheus -port=9090
   ```
   - Better: Use Consul service-definition files or automate via script

2. **Deploy Envoy Sidecar for Grafana**:
   - Modify grafana service in phase1-core/docker-compose.yml:
     ```yaml
     grafana:
       # ... existing config ...
       networks:
         - homelab_internal
       # Add sidecar
       # We'll use docker-compose depends_on and network aliases
     ```
   - Actually, simpler: Create separate envoy container that proxies to grafana
   - Pattern:
     ```yaml
     grafana:
       # ... existing (binds to internal network only, not published)
     grafana-envoy:
       image: envoyproxy/envoy:v1.25-latest
       container_name: grafana_envoy
       restart: unless-stopped
       volumes:
         - ./consul/envoy/grafana.yaml:/etc/envoy/envoy.yaml:ro
       networks:
         - homelab_internal
       command: ["envoy", "-c", "/etc/envoy/envoy.yaml"]
       labels:
         - "homepage.group=Monitoring"
         - "homepage.name=Grafana Envoy"
         - "homepage.description=Envoy proxy for Grafana"
     ```
   - Then change prometheus to scrape `grafana-envoy:10000` instead of `grafana:3000`
   - And expose grafana-envoy on the proxy port

3. **Envoy Configuration (grafana.yaml)**:
   ```yaml
   static_resources:
     listeners:
     - name: listener_0
       address:
         socket_address: { address: 0.0.0.0, port_value: 10000 }
       filter_chains:
       - filters:
         - name: envoy.filters.network.http_connection_manager
           typed_config:
             "@type": type.googleapis.com/envoy.extensions.filters.network.http_connection_manager.v3.HttpConnectionManager
             stat_prefix: ingress_http
             route_config:
               name: local_route
               virtual_hosts:
               - name: backend
                 domains: ["*"]
                 routes:
                 - match: { prefix: "/" }
                   route:
                     cluster: grafana_backend
                     timeout: 5s
             http_filters:
             - name: envoy.filters.network.http_connection_manager
           # Actually, this is wrong - we need two filters? Let's simplify.
   ```
   - Better approach: Use Consul Connect's built-in Envoy integration
   - Consul has `consul connect envoy` command that configures Envoy automatically
   - So we'd do:
     ```yaml
     grafana-envoy:
       image: hashicorp/consul:latest
       container_name: grafana_envoy
       restart: unless-stopped
       command: ["connect", "envoy", "-sidecar-for", "grafana"]
       volumes:
         - ${DATA_PATH}/phase1-core/data/consul:/consul/data
       networks:
         - homelab_internal
       depends_on:
         - consul-server
     ```
   - And we need to tell Consul that grafana service exists:
     - Either via service registration or sidecar proxy definition

Given the complexity of full sidecar injection in a single execution, let's adjust the approach:

### Phase 3 (Revised): Implement Key Service Mesh Features Without Full Sidecars
We'll focus on achieving the core benefits through alternative mechanisms:

#### A. **Service Discovery & Load Balancing** (via Consul DNS)
1. **Configure Services to Use Consul DNS**:
   - Instead of hardcoding `homelab_prometheus:9090`, use `prometheus.service.consul:9090`
   - Requires updating docker-compose files or providing a DNS overlay
   - Simpler: Use environment variable substitution in docker-compose:
     ```yaml
     prometheus:
       # ...
       environment:
         - PROMETHEUS_STORAGE_TSDB_PATH=/prometheus
       # Add:
       - PROMETHEUS_ENABLE_API_ADMIN=true
       # For service discovery, we'll rely on Consul but keep simple names for now
     ```
   - Actually, let's use Consul's DNS directly by configuring Docker daemon or using a local DNS forwarder
   - For single execution, we'll document the pattern and implement for one service pair

#### B. **Observability via Proxy-less Telemetry**
1. **Leverage Existing Telemetry** (Spec 01 + 07):
   - Use metrics from services themselves (Prometheus endpoints)
   - Use access logs from proxies (NPM) or services
   - Use distributed tracing via OpenTelemetry libraries in services (where available)
   - For services without native tracing, log correlation IDs

#### C. **Resilience Patterns via Libraries or Side-Effects**
1. **Retry Logic in Applications**:
   - Document that services should implement retries (e.g., n8n already has retry on nodes)
   - Provide helper libraries or examples
2. **Timeout Configuration**:
   - Configure timeouts in service configs where available
   - Use nginx-proxy-manager custom locations for timeout settings
3. **Circuit Breaking**:
   - Use libraries like Hystrix (Java) or opossum (NodeJS) or go-resilience (Go)
   - Or implement at the reverse proxy level (NPM doesn't have this built-in)

#### D. **Traffic Splitting & Canary (Future)**
- Note: For advanced traffic management, true sidecars are needed
- For homelab, manual traffic weighting via multiple service instances is sufficient

### Phase 4: Ingress & Egress Control
1. **Ingress via Existing NPM**:
   - Nginx Proxy Manager already acts as ingress controller
   - Enhance with:
     - Rate limiting (via custom nginx configs)
     - WAF capabilities (ModSecurity or similar via custom config)
     - Authentication at ingress (Authelia/OAuth2-Proxy - covered in Spec 04)
2. **Egress Control**:
   - Control outbound traffic from services (e.g., prevent data exfiltration)
   - Use Consul intentions to deny by default, allow specific connections
   - Or use egress gateways in Consul Connect

### Phase 5: Mesh Dashboard & Observability
1. **Consul UI**:
   - Already deployed: Shows service members, nodes, intentions
   - Provides basic service discovery view
2. **Service Graph**:
   - Consul provides service graph via API: `/v1/catalog/service-graph`
   - Can visualize in Grafana via JSON plugin
3. **Intention Monitoring**:
   - Alert when intentions are changed or violated
   - Log intention checks via Consul audit device

### Phase 6: Automation & Standardization
1. **Service Registration Helper**:
   - Create script: `scripts/register-with-consul.sh <service-name> <port>`
   - Uses Consul HTTP API to register service
   - Can be run in container's entrypoint or as init container
2. **Envoy Sidecar Template**:
   - Create `templates/envoy/sidecar.yaml` for common configurations
   - Parameterize for service name, ports
3. **Consul Intention Manager**:
   - Script: `scripts/set-consul-intention.sh <source> <dest> <action>`
   - Where action is allow/deny

## Success Criteria
- Critical service connections (e.g., Grafana→Prometheus, n8n→Ollama) can be encrypted with mTLS via Envoy sidecars
- Service discovery via Consul DNS is available for services that opt-in
- Intention-based access control can restrict service-to-service communication
- Basic observability (service mesh metrics) is available through Consul telemetry
- Traffic management (retries, timeouts) can be configured via Envoy or service-level settings
- Ingress traffic is controllable via existing NPM with enhanced security features
- Egress traffic can be restricted to prevent unauthorized outbound connections
- Mesh dashboard shows service dependencies, traffic flows, and error rates
- Mean time to deploy a new service with mesh protection: < 10 minutes (after learning curve)
- Added latency from mesh components: < 5ms for local traffic
- Services can opt-in to mesh features gradually
- Documentation and templates make adoption straightforward

## Files to Create/Modify
```
context/feature-specs/11-service-mesh-for-resilient-communication.md  (this file)
scripts/register-with-consul.sh                                       (Service registration helper)
scripts/set-consul-intention.sh                                       (Intention management)
templates/envoy/sidecar.yaml                                          (Envoy sidecar template)
consul/                                                               (Consul config)
  - server.json
  - client.json
  - policies/
  - intentions/
phase1-core/docker-compose.yml                                        (add consul-server, example envoy)
  - Example: Add grafana-envoy and reconfigure grafana/prometheus to use it
docs/SERVICE-MESH.md                                                  # How to add services to mesh
monitoring/grafana/provisioning/dashboards/service-mesh-dashboard.json
README.md                                                             # Add service mesh section
.env                                                                  # Add any needed Consul vars
```

## Dependencies
- Docker Compose v2+
- Consul server and client containers
- Envoy proxy container (for sidecar approach)
- Services modified to either:
  - Use Consul DNS for service discovery (`*.service.consul`)
  - Send traffic through Envoy sidecar (localhost:port -> envoy -> service)
  - Or use Consul Connect's native sidecar injection (more complex)
- Basic understanding of service mesh concepts: mTLS, sidecars, intentions, traffic management
- Optional: Consul CLI for management
- For full mesh: Would need to modify service entrypoints to launch Consul Connect envoy

## Estimated Effort
Single AI execution to:
- Deploy Consul control plane with UI
- Demonstrate mTLS for one critical service pair (e.g., Grafana→Prometheus) using Envoy sidecars
- Create service registration and intention management scripts
- Provide documentation and templates for adding other services
- Outline how to extend to traffic management and observability
Actual full mesh adoption across all services will require iterative effort but the foundation for secure, observable inter-service communication is achievable in one go.