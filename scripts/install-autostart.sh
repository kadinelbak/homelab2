#!/usr/bin/env bash
# Install the host-level config for the homelab: Docker daemon settings and the
# systemd units that start, update and check the stacks. Re-run after changing
# any of them.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# live-restore keeps containers running while dockerd restarts or upgrades.
# It applies on reload; the log limits apply to containers created afterwards.
sudo install -m 0644 "${repo_root}/config/docker/daemon.json" /etc/docker/daemon.json
sudo systemctl reload docker

for unit in homelab-autostart.service homelab-update.service homelab-update.timer \
            homelab-check.service homelab-check.timer; do
  sudo install -m 0644 "${repo_root}/systemd/system/${unit}" /etc/systemd/system/
done
sudo systemctl daemon-reload
sudo systemctl enable homelab-autostart.service
sudo systemctl enable --now homelab-update.timer homelab-check.timer

# User timers (nextcloud-nightly-sync) only run after a reboot if kadin lingers.
sudo loginctl enable-linger kadin
