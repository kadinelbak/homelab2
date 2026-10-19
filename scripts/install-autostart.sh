#!/usr/bin/env bash
# Install the boot-time units for the homelab. Re-run after changing them.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

sudo install -m 0644 "${repo_root}/systemd/system/homelab-autostart.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable homelab-autostart.service

# User timers (nextcloud-nightly-sync) only run after a reboot if kadin lingers.
sudo loginctl enable-linger kadin
