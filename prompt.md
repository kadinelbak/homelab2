Act as a Senior DevOps Engineer and Systems Architect. I am performing a complete "Ground Zero" rebuild of my homelab. I need you to generate a comprehensive, phased deployment plan, including the exact directory structures and `docker-compose.yml` configurations.

### 1. System Constraints & Context
* **Hardware:** Host machine runs Linux with an NVIDIA RTX 3050 GPU and 16GB of RAM (upgrading to 48GB later).
* **RAM Limitation:** Because I only have 16GB currently, memory management is the highest priority. 
* **The Strategy:** We will use Docker Compose `profiles` (e.g., `profiles: ["core"]`, `profiles: ["ondemand"]`). Lightweight services will be "always-on", while heavy compute services MUST default to off (`restart: "no"`) so I can spin them up only when needed.

### 2. The Complete Service Inventory
Please organize the following specific services into logical Compose files or profiles. 

**Category A: The Core Infrastructure (Always-On)**
* Management: Portainer
* Networking: Nginx Proxy Manager (NPM), Tailscale (Host level, but acknowledge for proxying)
* Identity/Dashboard: Authentik (SSO), Homepage
* Monitoring: Beszel (Hub and Agent), Uptime Kuma
* System Automation: Watchtower, ntfy

**Category B: Media, Storage, & Downloads (Always-On)**
* Media: Jellyfin, Audiobookshelf
* Document Management: Paperless-ngx
* Photo Backup: Immich (with machine learning container)
* Auto-Download Stack: qBittorrent + Gluetun (VPN). CRITICAL: qBittorrent must be strictly routed through the Gluetun container using `network_mode: service:gluetun` to prevent IP leaks.

**Category C: AI, Gaming, & Utility (Always-On)**
* AI Stack: Ollama + Open WebUI. CRITICAL: Ollama must include the NVIDIA container toolkit deployment block to access the RTX 3050.
* Game Server: Minecraft (itzg/minecraft-server image, heavily modded with Biomes O' Plenty).
* Utility/Smart Home: n8n (with PostgreSQL), Home Assistant, Spoolman (3D print tracking), Actual Budget.

**Category D: Heavy Compute & Knowledge (On-Demand / Heavy)**
* Remote Access: Kasm Workspaces, Apache Guacamole
* Cloud/DevOps: Nextcloud, GitLab (or Gitea), Supabase
* Knowledge/Productivity: Kiwix-serve (Offline Wikipedia), Outline (or Docmost), Cal.com, NocoDB.

### 3. Strict Implementation Rules
1. **Permissions:** All volume mounts must map properly to the host user (assume UID 1000 / GID 1000) to prevent `EACCES: permission denied` errors (especially for n8n, Postgres, and Nextcloud).
2. **Database Consolidation:** Where possible, utilize a single centralized PostgreSQL or MariaDB container with multiple databases for different services to save RAM, rather than spinning up 10 different database containers.
3. **Internal Networking:** Ensure containers that need to talk to each other (like Open WebUI -> Ollama, or Authentik -> NPM) share an explicit backend Docker network.

### 4. Required Output
Please provide the following:
1. **The Directory Structure:** How should I organize these folders on my NVMe drive?
2. **The Phased Rollout Plan:** Step-by-step instructions on what to spin up first to ensure dependencies (like databases and proxy) are met.
3. **The Docker Compose Files:** Generate the actual YAML code for the phases. (You can split this across multiple responses if it's too long).
4. **The On-Demand Toggle:** Provide a simple bash script or alias I can use to easily "wake up" and "sleep" the Category D services to protect my 16GB of RAM.