# Continuous Security Monitoring & Threat Detection Feature Spec

## Overview
Implement continuous security monitoring and automated threat detection across the homelab infrastructure. This spec extends the baseline monitoring (Spec 01) with security-focused telemetry, intrusion detection, vulnerability scanning, and automated response capabilities. The goal is to detect, analyze, and respond to security threats in real-time while maintaining a strong security posture through continuous compliance checking.

## Core Components
- **Security Information and Event Management (SIEM)**: Centralized security log analysis (leveraging Loki/Prometheus from Spec 01)
- **Intrusion Detection System (IDS)**: Network and host-based detection (Suricata/Snort + OSSEC/Wazuh)
- **Vulnerability Management**: Automated container image scanning (Trivy/Grate) and host CVE scanning
- **Log Analysis & Anomaly Detection**: Security-focused parsing, correlation, and behavioral analytics
- **File Integrity Monitoring (FIM)**: Detect unauthorized changes to critical files
- **Automated Response**: Playbook-driven containment and remediation (via n8n)
- **Threat Intelligence**: Integration with feeds for IOC (Indicators of Compromise) blocking
- **Compliance Monitoring**: Continuous checks against security benchmarks (CIS Docker, Linux)
- **Security Dashboard**: Unified view of security posture, alerts, and trends

## Implementation Plan (Single AI Execution Focus)

### Phase 1: Foundational Security Telemetry
1. **Enhance Existing Logging for Security**:
   - Ensure all services log authentication attempts, access denials, and configuration changes
   - Tag security-relevant logs with specific labels for easy filtering in Loki:
     - `security_event="true"`
     - `event_type="auth_failure" | "privilege_escalation" | "config_change"`
   - Configure services to log to stdout/stderr for easy collection by Promtail

2. **Deploy Security-Focused Exporters**:
   - **Node Exporter Security Extensions**:
     - Enable `collector.filefd`, `collector.hwclock`, `collector.loadavg`, `collector.textfile` (for FIM)
     - Add custom textfile collector for monitoring `/etc/passwd`, `/etc/shadow`, `/etc/group` changes
   - **cAdvisor Security Labels**: Ensure container metadata includes security-relevant labels
   - **Custom Security Exporter** (optional): For metrics like failed login attempts, sudo usage

3. **Deploy Network-Based IDS (Suricata)**:
   - Add to phase1-core/docker-compose.yml:
     ```yaml
     suricata:
       image: jasonish/suricata:latest
       container_name: homelab_suricata
       restart: unless-stopped
       cap_add:
         - NET_ADMIN
         - NET_RAW
       volumes:
         - ${DATA_PATH}/phase1-core/data/suricata:/etc/suricata
         - /var/log/suricata:/var/log/suricata
         - /etc/localtime:/etc/localtime:ro
       networks:
         - homelab_internal   # Monitor internal traffic
       command: ["-c", "/etc/suricata/suricata.yaml", "-i", "eth0"]
       labels:
         - "com.centurylinklabs.watchtower.enable=true"
         - "homepage.group=Security"
         - "homepage.name=Suricata IDS"
         - "homepage.href=http://${DOMAIN}:8092"  # If we add EveBox
         - "homepage.description=Network intrusion detection"
     ```
   - Configure Suricata rules:
     - Enable ET Open rules (free) or Emerging Threats
     - Focus on: C2 traffic, port scans, brute force attempts, malware callbacks
     - Output to EveJSON for easy Loki ingestion

4. **Deploy Host-Based IDS (OSSEC/Wazuh Agent)**:
   - Option A: Wazuh agent (more features, but heavier)
   - Option B: OSSEC agent (lighter, simpler)
   - For simplicity in single execution, we'll document OSSEC approach:
     - Add ossec-agent container or run on host
     - Monitor: `/var/log/auth.log`, `/var/log/secure`, `/etc/passwd`, `/etc/shadow`, Docker logs
     - Rootkit checking, file integrity monitoring
     - Forward alerts to central manager (could be another container or use agentless mode reporting to Loki)

### Phase 2: Vulnerability Management
1. **Automated Container Image Scanning**:
   - Deploy Trivy in a scanning container or as part of CI/CD
   - Add to phase1-core or create a dedicated scanning service:
     ```yaml
     trivy-scan:
       image: aquasec/trivy:latest
       container_name: homelab_trivy
       restart: "no"  # Run on demand or via schedule
       volumes:
         - /var/run/docker.sock:/var/run/docker.sock:ro
         - ${DATA_PATH}/phase1-core/data/trivy:/cache
       environment:
         - TRIVY_SEVERITY=CRITICAL,HIGH
       command: ["sh", "-c", "while true; do /scan/scan-images.sh; sleep 86400; done"]  # Daily
       labels:
         - "com.centurylinklabs.watchtower.enable=true"
         - "homepage.group=Security"
         - "homepage.name=Trivy Scanner"
         - "homepage.description=Vulnerability scanning"
     ```
   - Create `/scan/scan-images.sh`:
     - Scan all local images: `trivy image --severity CRITICAL,HIGH --exit-code 1 --format json $(docker images -q)`
     - Send results to Loki or n8n webhook for alerting
     - Optionally: Auto-create issues in a tracking system (if deployed)

2. **Host Vulnerability Scanning**:
   - Use OpenSCAP or Lynis for periodic host checks
   - Or rely on distro's security update notifications (unattended-upgrades alerts)
   - Integrate with monitoring: alert if `apt list --upgradable` shows security updates

3. **Dependency Scanning** (for custom services):
   - If you develop custom services, integrate Trivy or similar into build process
   - Document in developer experience spec

### Phase 3: Log Analysis, Correlation & Anomaly Detection
1. **Security Log Parsing in Promtail**:
   - Create parsers for common security logs:
     - SSH: `Accepted password for`, `Failed password for`, `Invalid user`
     - Sudo: `sudo:`, `USER=root`
     - Docker: `docker daemon`, container start/stop
     - Authentik: Login failures, admin actions
     - Vaultwarden: Login attempts, admin access
     - Nginx/NPM: 4xx/5xx rates, suspicious user agents
   - Use Promtail's pipeline stages to extract fields and label as `security_event`

2. **Correlation Rules via Alertmanager/Prometheus**:
   - Create recording rules for derived security metrics:
     - `rate(sshd_failed_attempts_total[5m]) > 10` → Brute force attempt
     - `increase(sudo_usage_total[1h]) > 5` → Unusual sudo activity
     - `suricata_alerts_total{severity="high"}[5m] > 0` → High-severity IDS alert
     - `authentik_login_failure_total[15m] > 5` → Potential credential stuffing
   - Create alerting rules that fire when thresholds exceeded

3. **Behavioral Anomaly Detection** (Simple ML via Prometheus):
   - Use Holt-Winters forecasting to detect anomalies in:
     - Login frequency per user/time of day
     - Outbound connection counts
     - Resource usage patterns (sudden crypto miner behavior)
   - Alert when actual deviates significantly from predicted

### Phase 4: File Integrity Monitoring (FIM)
1. **Deploy FIM Agent**:
   - Use OSSEC/Wazuh built-in FIM or standalone tool like `aide` or `tripwire`
   - Monitor critical paths:
     - `/etc/passwd`, `/etc/shadow`, `/etc/group`, `/etc/sudoers`
     - `/etc/ssh/sshd_config`, `/etc/docker/daemon.json`
     - `${DATA_PATH}` (specifically config subdirs)
     - `/usr/local/bin/`, `/opt/`
   - Configure to ignore expected changes (e.g., log files, cache dirs)
   - Alert on: new files, permission changes, unexpected modifications

2. **Docker Daemon & Socket Monitoring**:
   - Monitor `/var/run/docker.sock` access (though hard to do without auditd)
   - Alert on new containers run with privileged flags or dangerous mounts

### Phase 5: Automated Response & Playbooks
1. **Integrate with n8n for Security Orchestration**:
   - Create Alertmanager webhook receiver that triggers n8n workflows
   - Build reusable security playbooks:
     - **Brute Force Response**: Block IP via firewall (ufw/iptables) for 1 hour, notify
     - **Malware Detected**: Isolate container (if possible), collect forensic data, alert
     - **Privilege Escalation Attempt**: Force MFA challenge, log detailed audit
     - **Critical Vulnerability Found**: Auto-create ticket, notify admin, schedule patch
     - **Data Exfiltration Pattern**: Throttle network, snapshot volumes for forensics

2. **Example n8n Workflow: Brute Force Blocker**:
   - Trigger: Alertmanager webhook (SSH brute force alert)
   - Steps:
     1. Extract attacking IP from alert payload
     2. Validate: Check if IP is internal (Tailscale) or known good
     3. Action: Run `ufw insert 1 deny from <IP> to any port 22`
     4. Notify: Send message via ntfy/Telegram/Email: "Blocked IP X for SSH brute force"
     5. Timeout: After 1 hour, run `ufw delete deny from <IP> to any port 22`
     6. Log: Record event in Loki for audit trail

3. **Automated Container Response**:
   - If Suricata detects C2 traffic from a container:
     - Trigger n8n workflow to:
       1. Identify container via connection tracking
       2. Pause container: `docker pause <container>`
       3. Collect forensic snapshot: `docker commit <container> forensics/<timestamp>`
       4. Notify security team
       5. Optionally: Remove container after investigation

### Phase 6: Threat Intelligence Integration
1. **Automated IOC Blocking**:
   - Daily: Fetch IP/domain blocklists from trusted sources (Abuse.ch, Spamhaus, etc.)
   - Format into `ufw deny` rules or `iptables` rules
   - Apply via script: `scripts/update-threat-intel.sh`
   - Monitor for false positives and have whitelist mechanism

2. **DNS Sinkholing** (Optional):
   - Deploy Pi-hole or AdGuard Home configured to block known malicious domains
   - Integrate with threat intelligence feeds
   - Monitor blocked queries as potential infection indicators

### Phase 7: Compliance & Benchmarking
1. **Automated CIS Benchmarks**:
   - Use `docker-bench-security` or `kube-bench` (adapted for Docker) periodically
   - Or use OpenSCAP with Docker profiles
   - Alert on failures: e.g., "Container running as root", "Privileged container", "Insecure registry"
   - Track compliance score over time in Grafana

2. **Linux System Hardening Checks**:
   - Weekly Lynis scan
   - Check for: world-writable files in /etc, unused listening services, weak SSH configs
   - Integrate results into monitoring dashboard

### Phase 8: Security Dashboard & Reporting
1. **Grafana Security Dashboard** (provisioned via Spec 03):
   - Panels showing:
     - Top 10 source IPs of blocked connections (Suricata)
     - Authentication failure trends by service
     - Privileged container count
     - Vulnerability count by severity (Trivy)
     - File integrity changes
     - Threat intelligence hits
     - Compliance score (CIS Docker/Linux)
   - Include world map of attack origins if geolocation available
   - Add "Security Score" widget (0-100) based on weighted factors

2. **Automated Security Reports**:
   - Weekly: Email summary of security events, top risks, actions taken
   - Monthly: Compliance report, trend analysis, recommendations
   - Generated via n8n workflow querying Loki/Prometheus

## Success Criteria
- Security-relevant events from all services are collected, labeled, and searchable in Loki
- Network IDS (Suricata) is monitoring internal traffic and generating actionable alerts
- Host-based monitoring (OSSEC/Wazuh agent) is detecting file changes, login anomalies, and rootkits
- Container images are scanned weekly for critical/high vulnerabilities with alerts on failures
- Host vulnerability status is monitored and alerts trigger on available security updates
- Behavioral anomaly detection identifies unusual patterns (brute force, data exfiltration, crypto mining)
- File integrity monitoring alerts on unauthorized changes to critical system and config files
- Automated response playbooks execute for common threats (brute force, malware detection)
- Threat intelligence feeds are automatically consumed and applied to block malicious IPs/domains
- Continuous compliance monitoring shows deviation from CIS Docker/Linux benchmarks
- Security dashboard provides real-time view of security posture and trends
- Mean Time to Detect (MTTD) for security incidents is < 5 minutes
- Mean Time to Respond (MTTR) for automated threats is < 15 minutes
- False positive rate is tuned to < 10% for automated alerts
- All security telemetry is retained for at least 30 days for forensic analysis

## Files to Create/Modify
```
context/feature-specs/07-continuous-security-monitoring.md  (this file)
scripts/update-threat-intel.sh                              (TI feed fetcher)
scripts/scan-images.sh                                      (Trivy scanning wrapper)
phase1-core/docker-compose.yml                              (add suricata, trivy-scan services)
suricata/                                                   (Suricata config)
  - suricata.yaml
  - rules/
      - local.rules
      - etopen/  (if downloading)
ossec/                                                      (if using OSSEC agent)
  - ossec.conf
  - keys/
  - rules/
      - local_rules.xml
trivy/                                                      (Trivy cache/config)
  - config.yaml
docs/SECURITY-MONITORING.md                                 (runbook/playbook documentation)
monitoring/grafana/provisioning/dashboards/security-dashboard.json
scripts/ossec-agent-setup.sh                                (if deploying agent)
scripts/fim-check.sh                                        (custom FIM if needed)
README.md                                                   (add security section post-deploy)
.env                                                        (add any needed API keys for TI feeds)
```

## Dependencies
- Docker Compose v2+ with capability to add `cap_add` and privileged containers
- Sufficient resources: Suricata needs ~512MB-1GB RAM depending on ruleset and traffic
- For Suricata: Network interface in promiscuous mode or TAP (if monitoring specific segment)
- For host-based IDS: Agent needs read access to logs and system files (run as root or with capabilities)
- Internet access for updating threat intelligence feeds and vulnerability databases
- jq, curl, awk for log processing in scripts
- Basic understanding of network traffic and Linux security concepts

## Estimated Effort
Single AI execution to:
- Define comprehensive security telemetry collection strategy
- Create Suricata IDS deployment with basic ruleset
- Implement automated container vulnerability scanning (Trivy)
- Design security log parsing and correlation rules for Alertmanager
- Outline FIM and host-based monitoring approach
- Create framework for automated response playbooks via n8n
- Specify security dashboard components
Actual rule tuning, false positive reduction, and playbook refinement will require ongoing effort but the foundation for continuous security monitoring is achievable in one go.