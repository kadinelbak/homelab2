# Developer Experience & Inner Loop Feature Spec

## Overview
Create a streamlined developer experience for building, testing, and deploying custom services and modifications to the homelab. This spec focuses on reducing the inner loop time (code → test → deploy) to minutes, providing consistent local development environments, automated testing, and easy integration with the existing homelab infrastructure. The goal is to make it as easy to develop for the homelab as it is to develop for a standard cloud-native platform.

## Core Components
- **Local Development Templates**: Pre-configured project scaffolds for common service types (web apps, APIs, workers)
- **Consistent Environments**: Docker Compose overrides for local development that mimic production
- **Automated Testing**: Unit, integration, and contract testing frameworks with CI/CD integration
- **Live Reload & Hot Module Replacement**: Instant feedback during development
- **Service Mesh for Dev**: Easy inter-service communication in development
- **Mocking & Service Virtualization**: Ability to develop against mocked dependencies
- **Preview Environments**: Automatic deployment of temporary environments for pull requests
- **Integration Testing**: Tools to test against real homelab services in isolation
- **Deployment Scaffolding**: One-command generation of docker-compose snippets and configs
- **Observability in Dev**: Access to logs, metrics, and tracing during development
- **Documentation Generation**: Auto-generated API docs and READMEs

## Implementation Plan (Single AI Execution Focus)

### Phase 1: Developer Environment Setup
1. **Create `dev/` Directory Structure**:
   ```
   dev/
     templates/                 # Service templates
       web-app/                 # Full-stack web application
       api-service/             # REST/gRPC API service
       worker/                  # Background job processor
       cron-job/                # Scheduled task
       dashboard/               # Grafana panel or custom UI
     local-overrides/           # Docker compose overrides for local dev
     scripts/                   # Developer helper scripts
     testing/                   # Testing frameworks and utilities
   ```

2. **Create Service Templates**:
   - Each template includes:
     - Dockerfile (multi-stage build)
     - docker-compose.dev.yml (local development composition)
     - README.md with usage instructions
     - Basic CI/CD configuration (GitHub Actions example)
     - Example code (Hello World)
     - Testing setup (Jest, PyTest, Go test, etc. - language agnostic)
     - Logging and health check implementation
     - Configuration management (viper, configure, etc. or env vars)
   - Focus on simplicity: Developer fills in business logic

3. **Local Development Overrides**:
   - Create `dev/local-overrides/docker-compose.override.yml` that:
     - Uses `:dev` tags or local builds for images
     - Mounts source code for live reload
     - Exposes debug ports
     - Uses development configuration (lower resource limits, verbose logging)
     - Points to local services (e.g., uses local PostgreSQL instead of external)
   - Example:
     ```yaml
     services:
       myservice:
         build:
           context: .
           dockerfile: Dockerfile.dev
         volumes:
           - ./src:/app/src:cached
           - ./:/app:ro
         ports:
           - "3000:3000"  # Debug port
         environment:
           - NODE_ENV=development
           - LOG_LEVEL=debug
           - DATABASE_URL=postgres://homelab:homelab@host.docker.internal:5432/devdb
         extra_hosts:
           - "host.docker.internal:host-gateway"
     ```

### Phase 2: Automated Testing Framework
1. **Testing Library Selection**:
   - Language-agnostic approach: Provide examples for popular stacks
   - Include:
     - Unit testing: Jest (JS/TS), PyTest (Python), Go test, JUnit (Java)
     - Integration testing: Testcontainers, Docker Compose in tests
     - Contract testing: Pact (if applicable)
     - End-to-end: Cypress, Playwright (for web apps)
   - Provide `dev/testing/Makefile` or scripts to run tests

2. **Test Database & Service Isolation**:
   - Create scripts to spin up ephemeral test environments:
     ```bash
     # dev/testing/run-test-env.sh
     docker compose -f docker-compose.test.yml up -d
     # Wait for healthy
     # Run tests against test environment
     # Tear down
     ```
   - Test environment uses:
     - In-memory databases where possible (sqlite:///:memory:)
     - Separate PostgreSQL database with random name
     - Mock external dependencies
     - Fresh Redis instance

3. **Pre-commit & Pre-push Hooks**:
   - Provide `.pre-commit-config.yaml` for:
     - Code formatting (prettier, black, gofmt)
     - Linting (eslint, pylint, golangci-lint)
     - Security scanning (detect secrets, gosec, bandit)
     - Running unit tests
   - Template includes `pre-commit` setup instructions

### Phase 3: Live Reload & Rapid Iteration
1. **Hot Module Replacement (HMR) Setup**:
   - For Node.js: Include nodemon or ts-node-dev in templates
   - For Python: Include watchdog or uvicorn with reload
   - For Go: Include air or reflex
   - For Java: Include spring-boot-devtools or JRebel (OSS alternative)
   - Volume mounts that enable instant refresh

2. **Development Proxy**:
   - Create a local reverse proxy (Traefik or Nginx) that:
     - Routes `service.local.homelab:3000` to local development service
     - Provides HTTPS with local CA
     - Handles websockets
     - Supports routing to production services for integration testing
   - Example: `api.myservice.local.homelab` → localhost:3000 (dev service)

3. **Automatic Rebuild on Change**:
   - Use `docker-compose watch` (Compose v2+) or `tilt`/`skaffold` for simpler setups
   - Or simple script: `find . -name "*.go" -exec docker compose build {} \;`

### Phase 4: Integration Testing with Homelab
1. **Test Against Real Services (Carefully)**:
   - Provide helper scripts that:
     - Spin up isolated test namespace
     - Deploy test version of service
     - Point to real backing services (PostgreSQL, Redis) but with test schemas
     - Use test accounts/users in Authentik/Vaultwarden
     - Run integration tests
     - Tear down
   - Emphasis on: "Test against real dependencies, but isolate your changes"

2. **Contract Testing**:
   - For services that consume/generate APIs:
     - Use Pact to define contracts
     - Verify provider (homelab service) meets contract
     - Verify consumer (your service) meets contract
   - Especially useful for: n8n workflows, Home Assistant automations, custom APIs

3. **Test Data Management**:
   - Provide scripts to anonymize production data for testing
   - Or generate realistic test data
   - Include fixtures for common scenarios

### Phase 5: Preview Environments (GitOps Flow)
1. **Pull Request Previews**:
   - When PR is opened:
     - Deploy temporary environment with PR code
     - Assign unique subdomain: `pr-123.myservice.local.homelab`
     - Deploy to shared cluster with resource limits
     - Automatically destroy when PR closed/merged
   - Implementation options:
     - Use `docker compose` with project names: `docker compose -p pr-123 up -d`
     - Use Kubernetes namespaces (if moving to K8s later)
     - Use Docker Swarm with labels
   - Simple implementation: Script that creates unique project name and deploys

2. **Preview Environment Template**:
   - Similar to local dev but:
     - Uses `:latest` or specific commit image
     - No live reload mounts (for stability)
     - Standard resource limits
     - Isolated network
     - Points to test backing services

### Phase 6: Service Discovery & Communication in Dev
1. **Internal Developer DNS**:
   - Use CoreDNS or similar to provide:
     - `myservice.dev.internal` → local service
     - `postgres.dev.internal` → test PostgreSQL
     - `redis.dev.internal` → test Redis
   - Or simpler: Use `/etc/hosts` modifications via script
   - Even simpler: Leverage Docker's built-in service discovery within a custom network

2. **Shared Development Network**:
   - Create `dev-network` that all dev services join
   - Enables: `docker-compose -p dev up -d` where services can find each other by name
   - Isolates dev from production but allows pointing to prod services when needed

### Phase 7: Observability in Development
1. **Development-Focused Metrics & Logging**:
   - Ensure services log to stdout/stderr with structured format (JSON)
   - Include development-specific metrics: `dev_request_duration`, `dev_cache_hits`
   - Enable profiling when env var set: `ENABLE_PROFILING=true`
   - Provide `dev/` Grafana dashboard that shows dev services only

2. **Distributed Tracing in Dev**:
   - If using Jaeger/Tempo: Provide lightweight collector for dev
   - Or use logging-based trace IDs that can be correlated
   - Simple: Include request ID in logs that developers can grep

3. **Debugging Helpers**:
   - Provide `dev/scripts/attach-debugger.sh` for common languages
   - Include debug configurations for VS Code (`launch.json`)
   - Provide `dev/scripts/log-tail <service>` helper

### Phase 8: Deployment Scaffolding
1. **One-Command Service Creation**:
   - Script: `dev/scripts/create-service.sh <name> <type> [language]`
   - Creates:
     - Directory: `dev/services/<name>/`
     - Populated from template: `dev/templates/<type>/`
     - Initialized git repo
     - Basic docker-compose.dev.yml
     - README with next steps
   - Example: `./create-service.sh my-webapp web-app node`

2. **Docker Compose Snippet Generator**:
   - Script: `dev/scripts/generate-compose-snippet.sh`
   - Outputs:
     - Service definition for `phase*-core/docker-compose.yml`
     - Environment variables needed
     - Volume mounts
     - Labels for Homepage, Traefik, etc.
     - Healthcheck configuration
   - Based on service type and options

3. **Configuration Management Helper**:
   - Script: `dev/scripts/generate-config.sh`
   - Creates:
     - `.env.example` with required variables
     - Config file templates (yaml, json, toml)
     - Validation scripts
   - Ensures new services follow homelab conventions

### Phase 9: Documentation Generation
1. **Auto-generated API Docs**:
   - For OpenAPI/Swagger: Include `swagger-cli` or `docfx` in templates
   - For gRPC: Include protoc-gen-doc or similar
   - For GraphQL: Include graphql-doc or schema stitching
   - Output to `docs/api/` that gets included in homelab documentation

2. **README Generation**:
   - Template includes placeholders that get filled:
     - Service description
     - API endpoints
     - Environment variables
     - Dependencies
     - Deployment instructions
   - Script updates README based on code annotations

3. **Architecture Diagrams**:
   - Optional: Use `structurizr` or `plantuml` to generate diagrams from code
   - Or rely on manual updates

### Phase 10: Integration with Homelab CI/CD
1. **GitHub Actions Templates**:
   - Provide `.github/workflows/ci.yml` that:
     - Runs on push to main and PRs
     - Sets up dependencies
     - Runs unit tests
     - Builds Docker image
     - Scans for vulnerabilities (Trivy)
     - Pushes to registry (if configured)
   - Separate workflow for CD that deploys to homelab

2. **Homelab-Specific CI Steps**:
   - Step: "Deploy to test environment" - uses `docker compose -f docker-compose.test.yml`
   - Step: "Run integration tests against test services"
   - Step: "Perform security scan"
   - Step: "Check for breaking changes" (api diff, contract verification)

3. **Approval Gates**:
   - For production deployment: Require manual approval
   - Or: Automatic to staging, manual to prod

## Success Criteria
- Developer can create a new service in < 5 minutes using `create-service.sh`
- Local development environment starts in < 30 seconds with `docker compose -f docker-compose.dev.yml up -d`
- Code changes trigger live reload in < 2 seconds (for interpreted languages) or < 10 seconds (for compiled with watchers)
- Unit tests run in < 10 seconds for typical service
- Integration test environment spins up in < 60 seconds
- Developer can test against real homelab services (PostgreSQL, Redis, Authentik) without affecting production
- Preview environments are automatically created for PRs and destroyed on close
- Services follow homelab conventions for logging, metrics, health checks, and labels
- Generated docker-compose snippets work when copied to phase*-core/
- Developer has access to logs, metrics, and tracing during development
- Documentation (API, README) stays in sync with code via automation
- Inner loop time (change code → see result) is < 1 minute for web services
- Developer can easily add monitoring (Prometheus metrics) and logging (structured JSON) to new service
- New service can be deployed to production homelab with `./deploy-to-homelab.sh <service>`
- Rollback to previous version is simple and documented

## Files to Create/Modify
```
context/feature-specs/09-developer-experience-inner-loop.md  (this file)
dev/                                                       (New top-level directory)
  - templates/
      - web-app/
        - Dockerfile
        - docker-compose.dev.yml
        - src/
        - README.md
        - .gitignore
      - api-service/
        - (similar structure)
      - worker/
      - cron-job/
      - dashboard/
  - local-overrides/
      - docker-compose.override.yml
  - scripts/
      - create-service.sh
      - generate-compose-snippet.sh
      - attach-debugger.sh
      - log-tail.sh
      - deploy-to-homelab.sh
      - run-test-env.sh
  - testing/
      - Makefile
      - docker-compose.test.yml
      - test-helpers/
  - services/                                              # Where developers create services
    - README.md
local-overrides/                                           # For existing services to use in dev
  - docker-compose.override.yml                            # Applied to all services in dev
docs/DEVELOPER-GUIDE.md                                    # Comprehensive developer guide
README.md                                                  # Add developer section
.gitignore                                                 # Ignore dev/ if desired, or include templates
```

## Dependencies
- Docker Compose v2+ (for `docker compose watch` if used)
- Language-specific development tools (node, python, go, java, etc.) - developer provides
- Git for version control
- Make or similar for running tasks (optional but helpful)
- Basic understanding of Docker and containerization
- Access to homelab's Docker daemon (via socket or TLS) for testing
- Optional: Kind, k3s, or minikube if wanting Kubernetes dev experience
- Optional: Tilt, Skaffold, or DevSpace for advanced dev loops

## Estimated Effort
Single AI execution to:
- Create developer directory structure
- Create templates for web-app, api-service, worker, cron-job, and dashboard
- Create local development overrides that can be applied to existing services
- Create core developer helper scripts (create-service, generate-snippet)
- Set up testing framework examples
- Create deployment scaffolding scripts
- Document the developer workflow
Actual template refinement, language-specific adjustments, and testing of the inner loop will require iteration but the foundation for a streamlined developer experience is achievable in one go.