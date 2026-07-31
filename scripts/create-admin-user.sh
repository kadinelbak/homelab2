#!/usr/bin/env bash
set -euo pipefail

username="${1:-kelbakkouri}"

if [[ "$EUID" -ne 0 ]]; then
  echo "Run with sudo: sudo bash scripts/create-admin-user.sh ${username}" >&2
  exit 1
fi

if ! id "${username}" >/dev/null 2>&1; then
  adduser --gecos "" "${username}"
else
  echo "User ${username} already exists; skipping adduser."
fi

for group in sudo docker; do
  if getent group "${group}" >/dev/null; then
    usermod -aG "${group}" "${username}"
  fi
done

if id kadin >/dev/null 2>&1 && [[ -d /home/kadin/.ssh ]]; then
  install -d -m 700 -o "${username}" -g "${username}" "/home/${username}/.ssh"
  if [[ -f /home/kadin/.ssh/authorized_keys ]]; then
    install -m 600 -o "${username}" -g "${username}" \
      /home/kadin/.ssh/authorized_keys "/home/${username}/.ssh/authorized_keys"
  fi
fi

echo
echo "Created or updated ${username}."
echo "Groups:"
id "${username}"
echo
echo "Next tests:"
echo "  su - ${username}"
echo "  docker ps"
echo "  sudo whoami"
