# Smart Boot & Remote Boot Feature Spec

## Overview
Implement intelligent power management capabilities for the homelab server, including Wake-on-LAN (WoL) based remote booting and smart boot schedules based on contextual triggers like calendar events, usage patterns, and environmental factors.

## Components
- **Wake-on-LAN (WoL)**: Hardware-level remote power on capability
- **ethtool**: Configure WoL settings on network interface
- **n8n**: Workflow automation for smart boot triggers
- **Home Assistant**: Context awareness and automation hub
- **Tailscale**: Secure network fabric for remote triggers
- **Custom WoL Scripts**: Secure remote execution mechanisms
- **UPS Integration** (Optional): Graceful shutdown and power loss handling

## Implementation Plan (Single AI Execution)

### Phase 1: Hardware Preparation & Base Setup
1. **Enable WoL in BIOS/UEFI**:
   - Reboot and enter BIOS setup
   - Enable "Wake on LAN" or "Power on by PCI-E/PCI" option
   - Save and exit

2. **Configure Network Interface**:
   ```bash
   # Check current WoL settings
   ethtool eth0 | grep "Wake-on"
   
   # Enable WoL (persistent across reboots may require additional steps)
   ethtool -s eth0 wol g
   
   # Make persistent (add to rc.local or network config)
   echo "ethtool -s eth0 wol g" >> /etc/rc.local
   ```

3. **Get MAC Address**:
   ```bash
   ip link show eth0 | grep "link/ether" | awk '{print $2}'
   # or
   cat /sys/class/net/eth0/address
   ```

### Phase 2: Remote Boot Infrastructure
1. **Create WoL Helper Scripts**:
   - Create `/usr/local/bin/wol-server`:
   ```bash
   #!/bin/bash
   # Secure WoL triggering script
   MAC_ADDRESS="$(cat /etc/wol/mac.address 2>/dev/null || echo "CHANGE_ME")"
   
   if [ "$1" = "status" ]; then
       echo "WoL MAC: $MAC_ADDRESS"
       exit 0
   fi
   
   if [ -z "$MAC_ADDRESS" ] || [ "$MAC_ADDRESS" = "CHANGE_ME" ]; then
       echo "Error: MAC address not configured"
       exit 1
   fi
   
   # Send magic packet
   wakeonlan -i 255.255.255.255 "$MAC_ADDRESS"
   echo "WoL packet sent to $MAC_ADDRESS"
   ```
   
   - Make executable: `chmod +x /usr/local/bin/wol-server`
   - Store MAC securely: `echo "aa:bb:cc:dd:ee:ff" > /etc/wol/mac.address && chmod 600 /etc/wol/mac.address`

2. **Create Secure Remote Trigger Endpoint**:
   - Create simple Flask/FastAPI service for authorized WoL triggering:
   ```python
   # wol-api.py
   from flask import Flask, request, jsonify
   import subprocess
   import os
   from functools import wraps
   
   app = Flask(__name__)
   API_KEY = os.environ.get("WOL_API_KEY", "change-me")
   
   def require_api_key(f):
       @wraps(f)
       def decorated(*args, **kwargs):
           if request.headers.get('X-API-Key') != API_KEY:
               return jsonify({'error': 'Unauthorized'}), 401
           return f(*args, **kwargs)
       return decorated
   
   @app.route('/wol', methods=['POST'])
   @require_api_key
   def trigger_wol():
       mac = os.environ.get("WOL_MAC_ADDRESS")
       if not mac:
           return jsonify({'error': 'Server misconfigured'}), 500
       
       try:
           subprocess.run(['wakeonlan', '-i', '255.255.255.255', mac], check=True)
           return jsonify({'status': 'success', 'message': 'WoL packet sent'})
       except subprocess.CalledProcessError:
           return jsonify({'error': 'Failed to send WoL packet'}), 500
   
   @app.route('/status', methods=['GET'])
   @require_api_key
   def status():
       return jsonify({'status': 'ready', 'service': 'wol-api'})
   
   if __name__ == '__main__':
       app.run(host='0.0.0.0', port=9999)
   ```
   
   - Create Dockerfile for the service
   - Add to docker-compose.yml under a new "services" section or phase1-core

### Phase 3: Smart Boot Automation (n8n/Home Assistant)
1. **Create n8n Workflow Templates**:
   - **Calendar-Based Booting**:
     * Trigger: Google/Microsoft Calendar webhook (or polling)
     * Condition: Event starting in next 60 minutes with keywords like "work", "study", "homelab"
     * Action: Call WoL API endpoint
     * Delay: Boot 10 minutes before event start
   
   - **Presence-Based Booting**:
     * Trigger: Home Assistant device tracker (phone leaves work zone)
     * Condition: Time between 6 AM - 10 PM (avoid middle of night)
     * Action: Call WoL API
     * Debounce: Only trigger once per departure
   
   - **Scheduled Maintenance**:
     * Trigger: Cron (weekly Sundays 2 AM)
     * Action: Boot, run updates/services, then graceful shutdown after completion
   
   - **Usage Pattern Learning**:
     * Trigger: Daily at midnight
     * Action: Analyze yesterday's service usage logs (from Loki/Prometheus)
     * Condition: If usage detected between 7-9 AM → Schedule boot for 6:45 AM today

2. **Home Assistant Integrations**:
   - Create binary_sensor for server power state (via ping check)
   - Create automation: "When I arrive home AND server is off → Send notification 'Would you like to boot server?'"
   - Create toggle input_boolean for "Server Boot Mode": Auto, Manual, Disabled

### Phase 4: Secure Remote Access Methods
1. **Tailscale Funnel Method** (Recommended):
   ```bash
   # On any Tailscale device (could be phone/laptop)
   tailscale funnel --https=9999:9999 localhost:9999
   # This exposes https://<random>.ts.net -> localhost:9999 (WOL API)
   ```
   
   - Create automated script to maintain tunnel
   - Use systemd service to keep funnel running

2. **Telegram Bot Integration**:
   - Create bot via @BotFather
   - n8n workflow: Telegram Trigger (/wol command) → Validate user → Call WoL API
   - Add confirmation step: "Boot server? [Yes]/[No]"

3. **Web Interface Option**:
   - Simple protected page in Homelab dashboard (Homepage)
   - Button that triggers Wol via secure API call
   - Shows boot status and last boot time

### Phase 5: UPS Integration (Optional but Recommended)
1. **Install NUT (Network UPS Tools)**:
   ```bash
   # Install server component
   apt-get install nut
   
   # Configure ups.conf for your UPS model
   # Configure upsd.users for admin/mon users
   # Configure upsmon.conf for monitoring mode
   ```
   
2. **Create Power Loss Workflow**:
   - Trigger: UPS goes on battery (via nut-server notification or script)
   - Action: 
     * Send immediate alerts
     * Begin graceful shutdown of non-essential services
     * If power not restored in 2 minutes → Initiate host shutdown
   
3. **Power Restoration Boot**:
   - Trigger: UPS returns to line power
   - Delay: Wait 2 minutes for stability
   * Action: Boot homelab server

### Phase 6: Monitoring & Feedback Loop
1. **Boot Status Tracking**:
   - Create Prometheus metric: `homelab_boot_timestamp` (updated on successful boot)
   - Create Grafana panel showing: "Last Boot", "Uptime", "Boot Source (scheduled/manual/remote)"
   
2. **Boot Success Verification**:
   - n8n workflow: After sending WoL → Wait 90 seconds → Ping host → If success → Log successful boot
   - If failed after 3 attempts → Send alert: "WoL failed to boot server"

3. **Usage Analytics**:
   - Track boot frequency by method (scheduled, remote, manual)
   - Correlate with service usage to optimize boot schedules
   - Create "boot efficiency" metric: (time server actually used) / (time server powered on)

## Success Criteria
- Server can be powered on remotely via authenticated WoL packet
- Smart boot schedules reduce unnecessary power-on time by >50% compared to always-on
- Multiple secure remote triggering methods available (Tailscale, Telegram, Web)
- System provides feedback on boot success and suggests optimizations
- Integration with UPS for graceful handling of power events
- Zero-touch operation after initial configuration

## Files to Create/Modify
```
context/feature-specs/02-smart-remote-boot.md          (this file)
usr/local/bin/wol-server                               (WoL helper script)
etc/wol/mac.address                                    (Secure MAC storage)
wol-api/                                               (Flask API service)
  - Dockerfile
  - wol-api.py
  - requirements.txt
phase1-core/docker-compose.yml                         (add wol-api service)
n8n/workflows/                                         (Workflow JSON exports)
  - calendar-based-boot.json
  - presence-based-boot.json
  - maintenance-boot.json
  - usage-learning-boot.json
homeassistant/config/                                  (HA automations)
  - automations.yaml
  - scripts/wol_trigger.sh
scripts/deploy-wol-infrastructure.sh                   (Deployment helper)
scripts/ups-power-management.sh                        (Optional UPS integration)
```

## Dependencies
- WoL-capable network adapter and BIOS/UEFI
- ethtool installed
- wakeonlan package installed
- For API method: Python 3.7+, Flask or FastAPI
- For n8n/Home Assistant: Existing installations in phase3-ai-gaming
- For Tailscale: Tailscale client installed and logged in
- For Telegram: Bot token from @BotFather
- For UPS: nut package and compatible UPS hardware

## Estimated Effort
Single AI execution to deploy core WoL infrastructure with multiple triggering methods and basic smart automation. Advanced UPS integration and machine learning-based scheduling would be additional iterations.