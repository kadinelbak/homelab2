# Current Issues

## Known Issues
- No known critical issues reported (as of latest check)
- Homelab infrastructure appears to be stable with recent updates
- Minor DNS resolution issues with Pi-hole occasionally requiring cache flush
- Some services experiencing occasional high memory usage during peak loads

## Technical Debt
- Legacy service configurations using outdated Docker image tags should be updated to specific versions
- Some service configurations lack proper resource limits (memory/CPU)
- Backup verification procedures need automation and regular testing
- Documentation for some services is incomplete or outdated
- Network topology documentation needs updates to reflect recent changes

## Open Questions
- Should we implement centralized authentication (OAuth2/LDAP) for all services?
- What is the optimal backup strategy for our homelab (local vs cloud vs hybrid)?
- Should we implement monitoring for service uptime with alerts?
- How should we handle GPU passthrough for media transcoding services?
- What is the best approach for managing secrets across services (Vault, Docker secrets, etc.)?
- Should we implement a service mesh for inter-service communication?

## Recent Changes
- Based on git history, recent activity includes:
  - Added Traefik as reverse proxy replacing individual service ports
  - Updated Docker Compose files to use specific image versions instead of 'latest'
  - Added Prometheus and Grafana for monitoring
  - Implemented automated certificate renewal with Let's Encrypt
  - Added Vaultwarden for password management
  - Updated Pi-hole configuration for better ad blocking
  - These suggest active development around improving security and monitoring

## Blockers
- No obvious blockers identified
- Homelab depends on stable hardware and network connectivity
- Some services may have dependencies on external APIs or services