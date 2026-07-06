# Code Standards

## General

- Keep configurations small and single-purpose
- Fix root causes, do not layer workarounds
- Do not mix unrelated concerns in one configuration file
- Use clear, descriptive names for services, volumes, networks, and variables
- Comment complex logic, not obvious configurations
- Follow established conventions for each file type (YAML, JSON, etc.)

## Configuration Specific

- Use descriptive service names that indicate their purpose
- Use version numbers for images when appropriate (avoid 'latest' in production)
- Define explicit dependencies between services using depends_on
- Use environment variables for configuration that may change between environments
- Store sensitive information in secret management systems or Docker secrets
- Use named volumes for persistent data that needs to survive container recreation
- Define resource limits (memory, CPU) for services when appropriate
- Use restart policies to ensure service resilience

## Formatting

- Use consistent indentation (2 spaces for YAML, 4 spaces for JSON where applicable)
- Keep line width reasonable (aim for 80-100 characters)
- Use blank lines to separate logical sections in configuration files
- Align similar configuration items for readability
- Use consistent quoting style (prefer double quotes for strings in YAML/JISON)

## Documentation

- Document all services and their purpose in docker-compose.yml or README.md
- Include comments in configuration files explaining non-obvious decisions
- Keep README.md updated with major architectural changes
- Document external dependencies and required external services
- Include setup and deployment instructions in documentation

## Testing

- Validate configuration files with appropriate tools (docker-compose config, yamllint, etc.)
- Test service configurations in isolated environments when possible
- Verify that services start correctly and expose expected ports
- Test backup and restore procedures regularly
- Add validation checks when fixing configuration issues to prevent regression

## File Organization

- docker-compose.yml — Main container orchestration file
- docker-compose.override.yml — Local overrides for development
- services/ — Individual service configurations and customizations
  - home-assistant/ - Home Assistant configuration files
  - mosquitto/ - MQTT broker configuration
  - pi-hole/ - Pi-hole DNS configuration
  - unifi-controller/ - UniFi Network controller configuration
  - nextcloud/ - Nextcloud configuration and custom apps
  - vaultwarden/ - Bitwarden server configuration
  - grafana/ - Grafana dashboards and datasources
  - prometheus/ - Prometheus scraping rules and alerts
  - docker-registry/ - Private registry configuration
- networks/ — Custom Docker network configurations
- volumes/ — Named volume definitions (when not defined in compose)
- traefik/ — Traefik dynamic configuration, middleware, and routers
- ansible/ — Ansible playbooks, roles, and inventory
- monitoring/ — Monitoring stack configurations and dashboards
- backups/ — Backup scripts and retention policies
- scripts/ — Helper scripts for maintenance, updates, and operations
- docs/ — Documentation files
- context/ — Project context files (internal documentation, specs, etc.)
- Root directory should contain only:
  - Essential configuration files: .gitattributes, .gitignore, docker-compose.yml
  - Standard project files: CHANGELOG.md, LICENSE, README.md
  - Tool configuration: opencode.json
  - No loose configuration files, documentation files, or temporary files

### Organization Principles
1. **Separation of Concerns**: Each directory has a clear, single purpose
2. **Consistency**: Follow established patterns for file placement
3. **Clarity**: Root directory should be clean and minimal
4. **Automation**: Generated files (logs, backups) should be excluded from version control
5. **Discoverability**: Related files should be colocated in logical directories
6. **Environment Separation**: Distinguish between development, staging, and production configurations where applicable
