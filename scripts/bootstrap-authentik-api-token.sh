#!/usr/bin/env bash
# Create an Authentik API token without using the GUI and store it in .env.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env"
TOKEN_IDENTIFIER="${AUTHENTIK_API_TOKEN_IDENTIFIER:-homelab-sso-provisioner}"
TOKEN_USER="${AUTHENTIK_API_USER:-kelbakkouri}"

[[ -f "${ENV_FILE}" ]] || {
  echo "ERROR: .env not found at ${ENV_FILE}" >&2
  exit 1
}

current_token="$(
  awk -F= '/^AUTHENTIK_API_TOKEN=/ {print $2}' "${ENV_FILE}" | tail -n 1
)"
if [[ -n "${current_token}" && "${current_token}" != CHANGE_ME* ]]; then
  echo "AUTHENTIK_API_TOKEN already exists in .env."
  exit 0
fi

raw_output="$(
  docker exec \
    -e AUTHENTIK_API_USER="${TOKEN_USER}" \
    -e AUTHENTIK_API_TOKEN_IDENTIFIER="${TOKEN_IDENTIFIER}" \
    authentik_server \
    ak shell -c '
import os
from authentik.core.models import Token, TokenIntents, User

username = os.environ["AUTHENTIK_API_USER"]
identifier = os.environ["AUTHENTIK_API_TOKEN_IDENTIFIER"]
user = User.objects.filter(username=username).first()
if user is None:
    user = User.objects.filter(is_superuser=True).order_by("username").first()
if user is None:
    raise SystemExit("No Authentik user found for API token")

token, _ = Token.objects.get_or_create(
    identifier=identifier,
    defaults={
        "user": user,
        "intent": TokenIntents.INTENT_API,
        "expiring": False,
        "description": "Homelab declarative SSO provisioner",
    },
)
changed = False
if token.user_id != user.pk:
    token.user = user
    changed = True
if token.intent != TokenIntents.INTENT_API:
    token.intent = TokenIntents.INTENT_API
    changed = True
if token.expiring:
    token.expiring = False
    changed = True
if changed:
    token.save()
print(f"TOKEN:{token.key}")
'
)"

token="$(printf '%s\n' "${raw_output}" | sed -n 's/^TOKEN://p' | tail -n 1)"
if [[ -z "${token}" ]]; then
  echo "ERROR: failed to create Authentik API token" >&2
  exit 1
fi

AUTHENTIK_API_TOKEN="${token}" python3 - "${ENV_FILE}" <<'PY'
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
token = os.environ["AUTHENTIK_API_TOKEN"]
lines = path.read_text(encoding="utf-8").splitlines()
updated = False
rendered = []
for line in lines:
    if line.startswith("AUTHENTIK_API_TOKEN="):
        rendered.append(f"AUTHENTIK_API_TOKEN={token}")
        updated = True
    else:
        rendered.append(line)
if not updated:
    if rendered and rendered[-1].strip():
        rendered.append("")
    rendered.append(f"AUTHENTIK_API_TOKEN={token}")
path.write_text("\n".join(rendered) + "\n", encoding="utf-8")
path.chmod(0o600)
PY

echo "Stored Authentik API token in .env."
