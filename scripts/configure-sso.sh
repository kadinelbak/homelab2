#!/usr/bin/env bash
# =============================================================================
# Declarative Authentik SSO provisioning
#
# Requires:
#   AUTHENTIK_URL=https://authentik.example.com
#   AUTHENTIK_API_TOKEN=<real authentik API token>
#
# Usage:
#   bash scripts/configure-sso.sh
#   bash scripts/configure-sso.sh --dry-run
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env"
SPEC_FILE="${REPO_ROOT}/config/authentik/providers.json"
OUTPUT_FILE="${REPO_ROOT}/config/authentik/client-metadata.env"
DRY_RUN=false

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    -h|--help)
      sed -n '1,16p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

[[ -f "$ENV_FILE" ]] || {
  echo "ERROR: .env not found at ${ENV_FILE}" >&2
  exit 1
}

[[ -f "$SPEC_FILE" ]] || {
  echo "ERROR: SSO spec not found at ${SPEC_FILE}" >&2
  exit 1
}

export ENV_FILE SPEC_FILE OUTPUT_FILE DRY_RUN

python3 - <<'PY'
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

env_file = Path(os.environ["ENV_FILE"])
spec_file = Path(os.environ["SPEC_FILE"])
output_file = Path(os.environ["OUTPUT_FILE"])
dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"


def load_env_file(path):
    values = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value and value[0] in "\"'":
            quote = value[0]
            end = value.find(quote, 1)
            value = value[1:end] if end != -1 else value[1:]
        else:
            value = value.split(" #", 1)[0].strip()
        values[key] = value
    return values


file_env = load_env_file(env_file)
for key, value in file_env.items():
    os.environ.setdefault(key, value)

base_url = os.environ.get("AUTHENTIK_URL", "").rstrip("/")
token = os.environ.get("AUTHENTIK_API_TOKEN", "")
if not base_url:
    raise SystemExit("ERROR: AUTHENTIK_URL is required")
if not token or token.startswith("CHANGE_ME"):
    raise SystemExit("ERROR: AUTHENTIK_API_TOKEN is required. Do not use AUTHENTIK_SECRET_KEY here.")

headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}


def die(message):
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def expand(value):
    if isinstance(value, str):
        def repl(match):
            key = match.group(1)
            if key not in os.environ:
                die(f"Environment variable {key} is required by {spec_file}")
            return os.environ[key]
        return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", repl, value)
    if isinstance(value, list):
        return [expand(item) for item in value]
    if isinstance(value, dict):
        return {key: expand(item) for key, item in value.items()}
    return value


def request(method, path, body=None):
    url = f"{base_url}/api/v3{path}"
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        die(f"{method} {url} failed with HTTP {exc.code}: {detail}")
    except urllib.error.URLError as exc:
        die(f"{method} {url} failed: {exc.reason}")


def list_endpoint(path, query=None):
    query = query or {}
    encoded = urllib.parse.urlencode(query)
    data = request("GET", f"{path}?{encoded}" if encoded else path)
    if isinstance(data, dict) and "results" in data:
        return data["results"]
    if isinstance(data, list):
        return data
    return []


def first_by_field(path, field, value, query=None):
    for item in list_endpoint(path, query):
        if item.get(field) == value:
            return item
    return None


def flow_pk(slug):
    flow = first_by_field("/flows/instances/", "slug", slug, {"slug": slug})
    if not flow:
        flow = first_by_field("/flows/instances/", "slug", slug, {"search": slug})
    if not flow:
        die(f"Authentik flow '{slug}' was not found")
    return flow["pk"]


def provider_by_name(name):
    return first_by_field("/providers/oauth2/", "name", name, {"search": name})


def application_by_slug(slug):
    app = first_by_field("/core/applications/", "slug", slug, {"slug": slug})
    if app:
        return app
    return first_by_field("/core/applications/", "slug", slug, {"search": slug})


def scope_mapping_pks(scope_names):
    pks = []
    for scope_name in scope_names:
        mapping = first_by_field(
            "/propertymappings/provider/scope/",
            "scope_name",
            scope_name,
            {"scope_name": scope_name},
        )
        if not mapping:
            mapping = first_by_field(
                "/propertymappings/provider/scope/",
                "scope_name",
                scope_name,
                {"search": scope_name},
            )
        if not mapping:
            die(f"Authentik OAuth scope mapping '{scope_name}' was not found")
        pks.append(mapping["pk"])
    return pks


def save_or_update_provider(app, auth_flow, invalidation_flow):
    provider_name = f"{app['name']} OIDC"
    client_id = os.environ.get(app["client_id_env"], "")
    client_secret = os.environ.get(app["client_secret_env"], "")
    if not client_id or client_id.startswith("CHANGE_ME"):
        die(f"{app['client_id_env']} must be set before provisioning {app['slug']}")
    if not client_secret or client_secret.startswith("CHANGE_ME"):
        die(f"{app['client_secret_env']} must be set before provisioning {app['slug']}")

    redirect_uris = [
        {"matching_mode": "strict", "url": url}
        for url in expand(app["redirect_uris"])
    ]

    body = {
        "name": provider_name,
        "authorization_flow": auth_flow,
        "invalidation_flow": invalidation_flow,
        "client_type": "confidential",
        "client_id": client_id,
        "client_secret": client_secret,
        "include_claims_in_id_token": True,
        "issuer_mode": app.get("issuer_mode", "global"),
        "sub_mode": app.get("sub_mode", "hashed_user_id"),
        "redirect_uris": redirect_uris,
        "property_mappings": scope_mapping_pks(app.get("scopes", ["openid", "email", "profile"])),
        "access_code_validity": "minutes=5",
        "access_token_validity": app.get("access_token_validity", "hours=8"),
        "refresh_token_validity": "days=30",
    }

    existing = provider_by_name(provider_name)
    if dry_run:
        action = "update" if existing else "create"
        print(f"DRY-RUN: would {action} OAuth2 provider {provider_name}")
        return existing or {"pk": None, "client_id": client_id}

    if existing:
        provider = request("PATCH", f"/providers/oauth2/{existing['pk']}/", body)
        print(f"Updated provider: {provider_name}")
        return provider

    provider = request("POST", "/providers/oauth2/", body)
    print(f"Created provider: {provider_name}")
    return provider


def save_or_update_application(app, provider_pk):
    body = {
        "name": app["name"],
        "slug": app["slug"],
        "provider": provider_pk,
        "meta_launch_url": expand(app["launch_url"]),
        "open_in_new_tab": True,
        "meta_description": app.get("description", ""),
        "meta_icon": app.get("icon", "circle"),
    }

    existing = application_by_slug(app["slug"])
    if dry_run:
        action = "update" if existing else "create"
        print(f"DRY-RUN: would {action} application {app['slug']}")
        return

    if existing:
        request("PATCH", f"/core/applications/{existing['slug']}/", body)
        print(f"Updated application: {app['slug']}")
    else:
        request("POST", "/core/applications/", body)
        print(f"Created application: {app['slug']}")


def main():
    spec = json.loads(spec_file.read_text(encoding="utf-8"))
    spec = expand(spec)

    auth_flow = flow_pk(spec.get("authorization_flow_slug", "default-provider-authorization-implicit-consent"))
    invalidation_flow = flow_pk(spec.get("invalidation_flow_slug", "default-provider-invalidation-flow"))

    metadata_lines = [
        "# Generated by scripts/configure-sso.sh",
        "# Client secrets are intentionally not written here.",
        f"AUTHENTIK_URL={base_url}",
    ]

    for app in spec["applications"]:
        provider = save_or_update_provider(app, auth_flow, invalidation_flow)
        provider_pk = provider.get("pk")
        if provider_pk is not None:
            save_or_update_application(app, provider_pk)
        metadata_lines.append(f"{app['slug'].upper().replace('-', '_')}_OIDC_CLIENT_ID={os.environ[app['client_id_env']]}")
        metadata_lines.append(f"{app['slug'].upper().replace('-', '_')}_OIDC_ISSUER={base_url}/application/o/{app['slug']}/")

    if not dry_run:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text("\n".join(metadata_lines) + "\n", encoding="utf-8")
        os.chmod(output_file, 0o600)
        print(f"Wrote client metadata: {output_file}")


if __name__ == "__main__":
    main()
PY
