# Automated Backup & Disaster Recovery Feature Spec

## Overview
Implement a comprehensive, automated backup and disaster recovery system that protects all homelab data, configurations, and secrets. The system should enable point-in-time recovery, protect against ransomware and accidental deletion, and provide verified restore procedures—all with minimal manual intervention. Backups should be encrypted, versioned, and stored in multiple locations (local and off-site) following the 3-2-1 rule.

## Core Components
- **Backup Orchestrator**: Centralized scheduling and management (could be n8n workflows or dedicated tool like Borgmatic/Restic)
- **Data Backup**: PostgreSQL dumps, bind-mounted application data, configuration files
- **Secrets Backup**: Encrypted exports of Vaultwarden, .env files, and other sensitive data
- **Snapshot Strategy**: Filesystem snapshots (Btrfs/ZFS/LVM) where available for instant recovery
- **Encryption**: AES-256 encryption for all backups at rest and in transit
- **Storage Tiers**: Local fast storage for recent backups, cold/off-site storage for archival
- **Verification**: Automated restore testing and backup integrity checks
- **Monitoring**: Backup health metrics, success/failure alerts, and retention policy compliance
- **Disaster Recovery Playbook**: Documented, tested procedures for full system recovery

## Implementation Plan (Single AI Execution Focus)

### Phase 1: Define Backup Scope & Strategy
1. **Identify What to Backup**:
   - **Databases**: PostgreSQL instances (central, Immich, etc.) via logical dumps and/or snapshots
   - **Application Data**: All `${DATA_PATH}` bind mounts (media, configs, caches—excluding transient data)
   - **Configurations**: Docker-compose files, `.env`, service-specific config under `${DATA_PATH}`
   - **Secrets**: Vaultwarden exports (encrypted), `.env` file, SSL/TLS certificates (if self-signed)
   - **System State**: Docker images/volumes list, container configurations, network settings
   - **Exclude**: Temporary files, caches, build artifacts, log rotation directories (to save space)

2. **Define Backup Types & Schedule**:
   - **Full Backup**: Weekly (Sunday 2 AM) - complete dataset
   - **Incremental Backup**: Daily (every day at 2 AM) - changes since last backup
   - **Snapshot Backup**: Hourly (where filesystem supports) for instant rollback
   - **Log Backup**: Continuous WAL archiving for PostgreSQL (Point-in-Time Recovery capability)
   - **Retention Policy**:
     - Hourly snapshots: 24 hours
     - Daily increments: 14 days
     - Weekly fulls: 3 months
     - Monthly archival: 12 months (off-site)

### Phase 2: Implement Backup Tools & Storage
1. **Choose Backup Technology** (Recommend: Restic for simplicity, encryption, deduplication):
   - Install restic in a backup container or host
   - Initialize repositories for different data tiers:
     - `local-recent`: Fast local SSD for daily/weekly
     - `local-archive`: Slower HDD for monthly
     - `offsite`: Encrypted cloud (Backblaze B2, AWS S3, or another homelab via Tailscale)

2. **Create Backup Container/Service**:
   - Add to phase1-core/docker-compose.yml:
     ```yaml
     backup:
       image: restic/restic:latest
       container_name: homelab_backup
       restart: unless-stopped
       volumes:
         - ${DATA_PATH}:/data:ro
         - ./backup:/backup
         - /etc/localtime:/etc/localtime:ro
       environment:
         - RESTIC_REPOSITORY=/backup/local
         - RESTIC_PASSWORD_FILE=/backup/secrets/restic-pass
         - AWS_ACCESS_KEY_ID=${S3_ACCESS_KEY}  # For offsite
         - AWS_SECRET_ACCESS_KEY=${S3_SECRET_KEY}
         - AWS_DEFAULT_REGION=us-east-1
         - S3_ENDPOINT=${S3_ENDPOINT:-s3.amazonaws.com}
       command: ["sh", "-c", "while true; do /backup/run-backup.sh; sleep 3600; done"]
       labels:
         - "com.centurylinklabs.watchtower.enable=true"
         - "homepage.group=Maintenance"
         - "homepage.name=Backup Orchestrator"
         - "homepage.icon=harddisk"
         - "homepage.href=http://${DOMAIN}:8091"  # If we add a backup dashboard
         - "homepage.description=Automated backups"
     ```
   - Create `/backup/run-backup.sh` script that performs:
     - PostgreSQL dumps (using `pg_dumpall` or per-db)
     - Restic backup of `${DATA_PATH}` with excludes
     - Vaultwarden export (encrypted)
     - `.env` file backup
     - Docker volume snapshots (if using Btrfs/ZFS)
     - Upload to offsite if configured
     - Prune old backups per retention policy

3. **Secrets Management for Backup**:
   - Generate strong random password for restic: `openssl rand -base64 32`
   - Store in `.env` as `RESTIC_PASSWORD` and also in file for container
   - For offsite: Generate S3 credentials, restrict to backup bucket only
   - Seed backup credentials into Vaultwarden under "System Backups"

### Phase 3: Snapshot & Instant Recovery (Where Supported)
1. **If using Btrfs/ZFS on host**:
   - Create hourly snapshots of `${DATA_PATH}` subvolumes/datasets
   - Use snapshots for instant rollback of accidental deletions
   - Integrate snapshots into backup strategy (backup the snapshots, not live data, for consistency)
   - Create scripts: `scripts/snapshot-create.sh`, `scripts/snapshot-rollback.sh`

2. **If using LVM**:
   - Create logical volumes for `${DATA_PATH}` with snapshot capacity
   - Schedule lvcreate -s for snapshots
   - Backup from snapshot to ensure consistency

### Phase 4: Backup Verification & Monitoring
1. **Automated Restore Testing**:
   - Weekly: Spin up a temporary container, restore latest backup, verify basic functionality
   - Monthly: Full restore test of critical services (PostgreSQL, Vaultwarden) to isolated environment
   - Script: `scripts/verify-backup.sh` that:
     - Restores PostgreSQL dump to temp instance
     - Runs `pg_dump` and compares schema
     - Checks that key files exist in restored backup
     - Reports success/failure to ntfy/email

2. **Monitoring Integration** (Leverage Spec 01):
   - **Prometheus Metrics**: Expose via backup container:
     - `backup_last_success_timestamp`
     - `backup_size_bytes`
     - `backup_duration_seconds`
     - `backup_retention_count`
     - `backup_verification_status` (0/1)
   - **Grafana Dashboard**: Pre-built panel showing:
     - Backup success/failure over time
     - Storage usage by tier
     - Time since last successful backup
     - Estimated recovery point objective (RPO)
   - **Alerting** (Alertmanager rules):
     - Backup failed for 2 consecutive runs → Critical alert
     - No successful backup in 25 hours → Warning
     - Backup verification failed → Critical
     - Offsite backup sync lag > 1 hour → Warning

### Phase 5: Disaster Recovery Documentation & Automation
1. **Create Runbook**: `docs/DISASTER-RECOVERY.md` with:
   - Step-by-step recovery from offsite backup
   - Service startup order (dependencies: network → storage → postgres/redis → others)
   - Secrets restoration process
   - Validation steps post-recovery
   - Estimated RTO (Recovery Time Objective) for different scenarios

2. **Automated DR Scripts** (Optional but valuable):
   - `scripts/dr-start-network.sh`: Brings up minimal network/services
   - `scripts/dr-restore-phase1.sh`: Restores postgres, redis, vaultwarden
   - `scripts/dr-validate-services.sh`: Smoke tests key endpoints
   - These could be triggered by n8n workflow or run manually

### Phase 6: Ransomware Protection
1. **Immutable Backups**:
   - For offsite: Use S3 Object Lock or versioning with MFA Delete
   - For local: Snapshots as read-only where filesystem supports
   - Ensure backup credentials cannot modify/delete existing backups (append-only)

2. **Air Gap Considerations**:
   - Optionally: Weekly backup to encrypted external drive stored offline
   - Script to automate: `scripts/backup-to-offline-drive.sh`

## Success Criteria
- All critical data (databases, app data, configs, secrets) is backed up according to schedule
- Backups are encrypted at rest and in transit using strong encryption (AES-256)
- Multiple storage locations: local fast, local archive, offsite (3-2-1 rule)
- Automated verification confirms backups are restorable
- Monitoring alerts on backup failures or anomalies
- Documented and tested restore procedures exist for:
  - Single service recovery (e.g., just restore Immich)
  - Partial system recovery (e.g., lose a disk)
  - Full disaster recovery (bare metal restore)
- Recovery Point Objective (RPO) < 24 hours for daily-changing data
- Recovery Time Objective (RTO) < 2 hours for critical services (PostgreSQL, Redis, Vaultwarden)
- Offsite backup sync completes within defined SLA
- Backup storage usage trends are monitored and alert on unexpected growth

## Files to Create/Modify
```
context/feature-specs/06-automated-backup-disaster-recovery.md  (this file)
scripts/run-backup.sh                                         (main backup executor)
scripts/verify-backup.sh                                      (automated restore test)
scripts/snapshot-create.sh                                    (if Btrfs/ZFS)
scripts/snapshot-rollback.sh                                  (if Btrfs/ZFS)
scripts/dr-start-network.sh                                   (disaster recovery helpers)
scripts/dr-restore-phase1.sh
scripts/dr-validate-services.sh
scripts/backup-to-offline-drive.sh                            (optional offline)
phase1-core/docker-compose.yml                                (add backup service)
backup/                                                       (directory for backup scripts/config)
  - restic-pass                                               (password file, chmod 400)
  - exclude-list                                              (files/dirs to skip)
docs/DISASTER-RECOVERY.md                                     (runbook)
.env                                                          (add RESTIC_PASSWORD, S3_* vars)
README.md                                                     (add backup section post-deploy)
monitoring/grafana/provisioning/dashboards/backup-dashboard.json (if creating custom)
```

## Dependencies
- Sufficient storage space under `${DATA_PATH}/backup` or dedicated backup drive
- restic installed (or chosen backup tool) - can be run in container
- For snapshots: Btrfs, ZFS, or LVM on host (optional but recommended for instant recovery)
- For offsite: Cloud storage account (B2, S3, etc.) or secondary homelab via Tailscale
- PostgreSQL client tools (`pg_dump`, `pg_restore`) available in backup container
- jq for parsing JSON in scripts (if needed)
- Basic bash utilities: find, tar, gzip, openssl

## Estimated Effort
Single AI execution to:
- Define comprehensive backup scope and strategy
- Create the backup orchestration service (docker-compose addition)
- Write the main backup script with rotation, encryption, and offsite sync
- Implement automated verification scripts
- Create disaster recovery documentation outline
- Add monitoring integration points (to be fleshed out with Spec 01)
Actual testing of restore procedures and fine-tuning of retention policies may require iteration but the automated backup foundation is achievable in one go.