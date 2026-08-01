#!/bin/bash
# Create a local HTTPS certificate for Actual Budget if one is not present.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${REPO_ROOT}/.env}"

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
fi

: "${DATA_PATH:?DATA_PATH must be set in .env or the environment}"
: "${DOMAIN:?DOMAIN must be set in .env or the environment}"

CERT_DIR="${DATA_PATH}/phase3-ai-gaming/data/actual"
KEY_FILE="${CERT_DIR}/selfhost.key"
CRT_FILE="${CERT_DIR}/selfhost.crt"

mkdir -p "${CERT_DIR}"

if [[ -s "${KEY_FILE}" && -s "${CRT_FILE}" ]]; then
  echo "Actual HTTPS certificate already exists."
  exit 0
fi

if ! command -v openssl >/dev/null 2>&1; then
  echo "ERROR: openssl is required to generate ${KEY_FILE} and ${CRT_FILE}." >&2
  exit 1
fi

openssl req \
  -x509 \
  -nodes \
  -days 825 \
  -newkey rsa:2048 \
  -keyout "${KEY_FILE}" \
  -out "${CRT_FILE}" \
  -subj "/CN=${DOMAIN}" \
  -addext "subjectAltName=DNS:${DOMAIN},IP:127.0.0.1"

chmod 600 "${KEY_FILE}"
chmod 644 "${CRT_FILE}"

echo "Created Actual HTTPS certificate:"
echo "  ${KEY_FILE}"
echo "  ${CRT_FILE}"
